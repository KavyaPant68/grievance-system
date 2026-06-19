"""
app.py — GrievanceIQ Backend
Features:
  - Live SMTP OTP email verification on signup
  - Zero-knowledge SHA-256 cryptographic anonymity for anonymous complaints
  - Crypto-token-based ownership verification for complaint withdrawal
  - Authenticated anonymity (non-anonymous complaints use normal user_id)
  - Scoped public feed, AI duplicate deflection, notification bell,
    complaint detail, AI feedback loop, CC departments, overdue flagging
"""

from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, send_from_directory, jsonify)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3, os, uuid, random, smtplib, pickle, hashlib
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import numpy as np
from ai_classifier import classify



# ─────────────────────────────────────────────
# CRYPTOGRAPHIC CONFIGURATION
# ─────────────────────────────────────────────

# SECRET_PEPPER is the hidden application-wide salt used in SHA-256 hashing.
# It is NEVER stored in the database. Even if the database is fully leaked,
# no one can reverse-engineer which enrollment number maps to which complaint
# without knowing this exact string.
# In production: load from environment variable → os.environ.get('SECRET_PEPPER')
from dotenv import load_dotenv
load_dotenv()  # reads .env file automatically

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev_fallback_key')

SECRET_PEPPER = os.environ.get('SECRET_PEPPER', 'fallback_pepper')

SMTP_EMAIL    = os.environ.get('SMTP_EMAIL', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')

def generate_crypto_token(enrollment_no: str) -> str:
    """
    Generates a deterministic, irreversible 64-character SHA-256 hex token.

    How it works:
      - Combines the student's unique enrollment number with SECRET_PEPPER
      - Runs it through SHA-256 (a one-way cryptographic hash function)
      - Returns a fixed 64-character hex string

    Properties:
      - DETERMINISTIC: Same enrollment + pepper always produces the same token
        (so ownership can be re-verified later without storing the real identity)
      - IRREVERSIBLE: SHA-256 cannot be decrypted — no one can get the
        enrollment number back from the token
      - UNIQUE: Each enrollment number produces a completely different token

    Example:
      enrollment_no = '22BCA001'
      pepper        = 'GrievanceIQ@SRHU...'
      raw_input     = '22BCA001::GrievanceIQ@SRHU...'
      sha256(raw_input) → 'a3f1c29b4d2e...' (64 chars)
    """
    raw_input   = f"{enrollment_no.strip()}::{SECRET_PEPPER}"
    crypto_hash = hashlib.sha256(raw_input.encode('utf-8')).hexdigest()
    return crypto_hash  # 64-character lowercase hex string

# ─────────────────────────────────────────────
# SMTP EMAIL CONFIGURATION
# ─────────────────────────────────────────────
# Steps to configure:
#   1. Create a Gmail account for your app (e.g. grievanceiq.srhu@gmail.com)
#   2. Enable 2-Step Verification on that Google account
#   3. Go to: Google Account → Security → App Passwords
#   4. Generate an App Password for "Mail"
#   5. Paste it as SMTP_PASSWORD below (NOT your Gmail login password)
# In production: load both from environment variables.

SMTP_SERVER        = 'smtp.gmail.com'
SMTP_PORT          = 587
OTP_EXPIRY_MINUTES = 10

def send_otp_email(recipient_email: str, otp_code: str, student_name: str) -> bool:
    """
    Sends a real OTP verification email via Gmail SMTP with STARTTLS encryption.
    Returns True on success, False on any failure.
    """
    try:
        msg            = MIMEMultipart('alternative')
        msg['Subject'] = 'GrievanceIQ — Your Email Verification Code'
        msg['From']    = SMTP_EMAIL
        msg['To']      = recipient_email

        # Plain-text fallback for email clients that don't render HTML
        text_body = (
            f"Hello {student_name},\n\n"
            f"Your GrievanceIQ verification code is: {otp_code}\n\n"
            f"This code expires in {OTP_EXPIRY_MINUTES} minutes.\n"
            f"If you did not request this, ignore this email.\n\n"
            f"— GrievanceIQ System"
        )

        # HTML email body
        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;
                    padding:2rem;border:1px solid #e2e0da;border-radius:12px;">
            <h2 style="color:#1a1a2e;margin-bottom:.5rem;">
                Grievance<span style="color:#e63946;">IQ</span>
            </h2>
            <p style="color:#4a4a6a;margin-bottom:1.5rem;">
                Hello <strong>{student_name}</strong>,<br>
                Use the code below to verify your university email address.
            </p>
            <div style="background:#f8f7f4;border-radius:8px;padding:1.5rem;
                        text-align:center;margin-bottom:1.5rem;">
                <span style="font-size:2.8rem;font-weight:700;
                             letter-spacing:10px;color:#e63946;
                             font-family:'Courier New',monospace;">
                    {otp_code}
                </span>
            </div>
            <p style="color:#4a4a6a;font-size:.88rem;">
                ⏳ This code expires in <strong>{OTP_EXPIRY_MINUTES} minutes</strong>.<br>
                If you did not register on GrievanceIQ, simply ignore this email.
            </p>
            <hr style="border:none;border-top:1px solid #e2e0da;margin:1.5rem 0;">
            <p style="color:#9a9ab0;font-size:.78rem;">
                This is an automated message from the GrievanceIQ system.
                Do not reply to this email.
            </p>
        </div>
        """

        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        # Connect to Gmail SMTP with STARTTLS (encrypts the connection)
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()                          # identify to server
            server.starttls()                      # upgrade to encrypted connection
            server.ehlo()                          # re-identify over TLS
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, recipient_email, msg.as_string())

        print(f"[OTP EMAIL] Sent to {recipient_email}")
        return True

    except smtplib.SMTPAuthenticationError:
        print("[OTP EMAIL ERROR] Authentication failed. Check SMTP_EMAIL and SMTP_PASSWORD.")
        return False
    except smtplib.SMTPException as e:
        print(f"[OTP EMAIL ERROR] SMTP error: {e}")
        return False
    except Exception as e:
        print(f"[OTP EMAIL ERROR] Unexpected error: {e}")
        return False

# ─────────────────────────────────────────────
# FILE UPLOAD CONFIGURATION
# ─────────────────────────────────────────────
UPLOAD_FOLDER      = 'uploads'
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'pdf'}
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_file(file):
    if not file or file.filename == '':
        return None
    if not allowed_file(file.filename):
        return None
    ext         = file.filename.rsplit('.', 1)[1].lower()
    safe_name   = secure_filename(file.filename.rsplit('.', 1)[0])
    unique_name = f"{uuid.uuid4().hex[:8]}-{safe_name}.{ext}"
    file.save(os.path.join(UPLOAD_FOLDER, unique_name))
    return unique_name

# ─────────────────────────────────────────────
# DEPARTMENT + ACADEMIC UNIT CONFIGURATION
# ─────────────────────────────────────────────
DEPARTMENTS = {
    'Hostel':    {'label': 'Hostel / Warden',     'icon': '🏠', 'email': 'warden@college.edu',    'password': 'warden123'},
    'IT':        {'label': 'IT Department',        'icon': '💻', 'email': 'it@college.edu',         'password': 'it123'},
    'Academic':  {'label': 'Academic / Exam Cell', 'icon': '📚', 'email': 'academic@college.edu',   'password': 'academic123'},
    'Library':   {'label': 'Library',             'icon': '📖', 'email': 'library@college.edu',    'password': 'library123'},
    'Transport': {'label': 'Transport',            'icon': '🚌', 'email': 'transport@college.edu',  'password': 'transport123'},
    'Finance':   {'label': 'Finance / Fees',       'icon': '💰', 'email': 'finance@college.edu',    'password': 'finance123'},
    'General':   {'label': 'General Admin',        'icon': '📋', 'email': 'admin@college.edu',      'password': 'admin123'},
}

ACADEMIC_UNITS = [
    'Engineering',
    'Biosciences',
    'Management',
]

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect('grievance.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT    NOT NULL,
        email           TEXT    UNIQUE NOT NULL,
        enrollment_no   TEXT    UNIQUE,
        password        TEXT    NOT NULL,
        role            TEXT    NOT NULL DEFAULT 'student',
        department      TEXT    DEFAULT NULL,
        academic_unit   TEXT    DEFAULT NULL
    )''')

    # complaints table:
    #   For NON-anonymous complaints → user_id is stored, crypto_token is NULL
    #   For ANONYMOUS complaints     → user_id is NULL, crypto_token is the SHA-256 hash
    c.execute('''CREATE TABLE IF NOT EXISTS complaints (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        title          TEXT    NOT NULL,
        description    TEXT    NOT NULL,
        category       TEXT    NOT NULL,
        ai_category    TEXT    NOT NULL,
        ai_confidence  REAL    DEFAULT 0.0,
        ai_source      TEXT    DEFAULT 'keyword_fallback',
        routed_to      TEXT    NOT NULL,
        status         TEXT    NOT NULL DEFAULT 'Pending',
        attachment     TEXT    DEFAULT NULL,
        admin_remark   TEXT    DEFAULT NULL,
        resolve_by     TEXT    DEFAULT NULL,
        is_overdue     INTEGER DEFAULT 0,
        is_anonymous   INTEGER DEFAULT 0,
        is_public      INTEGER DEFAULT 0,
        academic_unit  TEXT    DEFAULT NULL,
        upvote_count   INTEGER DEFAULT 0,
        duplicate_of   INTEGER DEFAULT NULL,
        first_response_at TEXT DEFAULT NULL,
        resolved_at    TEXT    DEFAULT NULL,
        submitted_at   TEXT    NOT NULL,
        -- Identity columns: one of these two is populated, never both
        user_id        INTEGER DEFAULT NULL,   -- populated for non-anonymous complaints
        crypto_token   TEXT    DEFAULT NULL,   -- populated for anonymous complaints (SHA-256)
        FOREIGN KEY(user_id)      REFERENCES users(id),
        FOREIGN KEY(duplicate_of) REFERENCES complaints(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS reroute_log (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id INTEGER NOT NULL,
        from_dept    TEXT    NOT NULL,
        to_dept      TEXT    NOT NULL,
        rerouted_by  INTEGER NOT NULL,
        rerouted_at  TEXT    NOT NULL,
        note         TEXT    DEFAULT '',
        FOREIGN KEY(complaint_id) REFERENCES complaints(id),
        FOREIGN KEY(rerouted_by) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS complaint_cc (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id INTEGER NOT NULL,
        cc_dept      TEXT    NOT NULL,
        FOREIGN KEY(complaint_id) REFERENCES complaints(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL,
        complaint_id INTEGER NOT NULL,
        message      TEXT    NOT NULL,
        is_read      INTEGER DEFAULT 0,
        created_at   TEXT    NOT NULL,
        FOREIGN KEY(user_id)      REFERENCES users(id),
        FOREIGN KEY(complaint_id) REFERENCES complaints(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS complaint_upvotes (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id INTEGER NOT NULL,
        user_id      INTEGER NOT NULL,
        upvoted_at   TEXT    NOT NULL,
        UNIQUE(complaint_id, user_id),
        FOREIGN KEY(complaint_id) REFERENCES complaints(id),
        FOREIGN KEY(user_id)      REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS status_audit_log (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id         INTEGER NOT NULL,
        changed_by           INTEGER NOT NULL,
        from_status          TEXT    NOT NULL,
        to_status            TEXT    NOT NULL,
        admin_remark         TEXT    DEFAULT NULL,
        changed_at           TEXT    NOT NULL,
        time_in_status_hours REAL    DEFAULT NULL,
        FOREIGN KEY(complaint_id) REFERENCES complaints(id),
        FOREIGN KEY(changed_by)   REFERENCES users(id)
    )''')

    # Accountability log — records when a crypto token check was performed
    c.execute('''CREATE TABLE IF NOT EXISTS crypto_accountability_log (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        checked_by       INTEGER NOT NULL,
        enrollment_input TEXT    NOT NULL,   -- enrollment number that was checked
        matched_count    INTEGER DEFAULT 0,  -- how many complaints matched
        checked_at       TEXT    NOT NULL,
        reason           TEXT    DEFAULT '',
        FOREIGN KEY(checked_by) REFERENCES users(id)
    )''')

    # Central Admin
    existing = c.execute("SELECT id FROM users WHERE email='admin@college.edu'").fetchone()
    if not existing:
        c.execute('INSERT INTO users (name,email,password,role,department) VALUES (?,?,?,?,?)',
            ('Central Admin','admin@college.edu',generate_password_hash('admin123'),'superadmin',None))

    # Department heads
    for dept_key, dept_info in DEPARTMENTS.items():
        if dept_key == 'General':
            continue
        existing = c.execute('SELECT id FROM users WHERE email=?', (dept_info['email'],)).fetchone()
        if not existing:
            c.execute('INSERT INTO users (name,email,password,role,department) VALUES (?,?,?,?,?)',
                (dept_info['label']+' Head', dept_info['email'],
                 generate_password_hash(dept_info['password']), 'admin', dept_key))

    conn.commit()
    conn.close()

def check_overdue_complaints():
    today = date.today().isoformat()
    conn  = get_db()
    conn.execute('''UPDATE complaints SET is_overdue=1
        WHERE resolve_by IS NOT NULL AND resolve_by < ?
          AND status != 'Resolved' AND is_overdue=0''', (today,))
    conn.commit()
    conn.close()

def get_unread_count(user_id):
    conn = get_db()
    row  = conn.execute(
        'SELECT COUNT(*) as cnt FROM notifications WHERE user_id=? AND is_read=0', (user_id,)
    ).fetchone()
    conn.close()
    return row['cnt'] if row else 0

@app.context_processor
def inject_globals():
    count = 0
    if session.get('user_id') and session.get('user_role') == 'student':
        count = get_unread_count(session['user_id'])
    return dict(unread_count=count, departments=DEPARTMENTS, academic_units=ACADEMIC_UNITS)

# ─────────────────────────────────────────────
# STATUS CHANGE SERVICE (atomic)
# ─────────────────────────────────────────────
def process_status_change(cid, new_status, admin_remark, resolve_by, changed_by_id, conn):
    complaint  = conn.execute('SELECT * FROM complaints WHERE id=?', (cid,)).fetchone()
    old_status = complaint['status']
    if old_status == new_status:
        return

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    try:
        submitted       = datetime.strptime(complaint['submitted_at'], '%Y-%m-%d %H:%M')
        hours_in_status = (datetime.now() - submitted).total_seconds() / 3600
    except Exception:
        hours_in_status = None

    conn.execute(
        '''INSERT INTO status_audit_log
           (complaint_id,changed_by,from_status,to_status,admin_remark,changed_at,time_in_status_hours)
           VALUES (?,?,?,?,?,?,?)''',
        (cid, changed_by_id, old_status, new_status, admin_remark, now_str, hours_in_status))

    updates = ['status=?']
    values  = [new_status]
    if admin_remark:
        updates.append('admin_remark=?'); values.append(admin_remark)
    if resolve_by:
        updates.append('resolve_by=?');   values.append(resolve_by)
    if old_status == 'Pending' and new_status != 'Pending':
        updates.append('first_response_at=?'); values.append(now_str)
    if new_status == 'Resolved':
        updates.append('resolved_at=?');  values.append(now_str)
        updates.append('is_overdue=0')
    values.append(cid)
    conn.execute(f'UPDATE complaints SET {", ".join(updates)} WHERE id=?', values)

    # Notify student only if complaint has a user_id (non-anonymous)
    if complaint['user_id']:
        notif_msg = f'Your complaint "{complaint["title"]}" has been updated to "{new_status}".'
        if admin_remark:
            notif_msg += f' Admin note: {admin_remark}'
        conn.execute(
            'INSERT INTO notifications (user_id,complaint_id,message,is_read,created_at) VALUES (?,?,?,0,?)',
            (complaint['user_id'], cid, notif_msg, now_str))

# ─────────────────────────────────────────────
# AUTH — SIGNUP WITH LIVE OTP
# ─────────────────────────────────────────────
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email'].strip()
        password = request.form['password'].strip()
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id']         = user['id']
            session['user_name']       = user['name']
            session['user_role']       = user['role']
            session['user_department'] = user['department']
            session['academic_unit']   = user['academic_unit']
            session['enrollment_no']   = user['enrollment_no']  # stored for crypto token generation
            flash(f"Welcome back, {user['name']}!", 'success')
            if user['role'] in ('admin','superadmin'):
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('student_dashboard'))

        flash('Invalid email or password. Please try again.', 'error')
    return render_template('login.html')

@app.route('/signup', methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        name          = request.form['name'].strip()
        email         = request.form['email'].strip()
        enrollment_no = request.form['enrollment_no'].strip().upper()
        academic_unit = request.form['academic_unit'].strip()
        password      = request.form['password'].strip()

        # Validate academic unit is from allowed list
        if academic_unit not in ACADEMIC_UNITS:
            flash('Please select a valid Academic Unit.', 'error')
            return render_template('signup.html')

        # Enrollment number format: exactly 2 letters followed by 12 digits
        import re
        if not re.fullmatch(r'[A-Z]{2}\d{12}', enrollment_no):
            flash('Invalid enrollment number format. Expected: 2 letters followed by 12 digits (e.g. DD123456789012).', 'error')
            return render_template('signup.html')

        # Check uniqueness before sending OTP — no point sending email if duplicate
        conn = get_db()
        exists_email = conn.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        exists_enr   = conn.execute('SELECT id FROM users WHERE enrollment_no=?', (enrollment_no,)).fetchone()
        conn.close()

        if exists_email:
            flash('This email address is already registered. Please log in.', 'error')
            return render_template('signup.html')
        if exists_enr:
            flash('This enrollment number is already registered.', 'error')
            return render_template('signup.html')

        # Generate a 6-digit numeric OTP
        otp = str(random.randint(100000, 999999))

        # Freeze registration data in session — DB untouched until OTP verified
        session['pending_user'] = {
            'name':          name,
            'email':         email,
            'enrollment_no': enrollment_no,
            'academic_unit': academic_unit,
            'password_hash': generate_password_hash(password),  # hash now, store later
        }
        session['pending_otp']    = otp
        session['otp_created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Attempt to send real email
        sent = send_otp_email(email, otp, name)

        if sent:
            flash(
                f'A 6-digit verification code has been sent to {email}. '
                f'Please check your inbox (and spam folder).',
                'info'
            )
        else:
            # SMTP failed — show OTP in flash for development/demo only
            # Remove this else block before production deployment
            flash(
                f'[DEV FALLBACK] Email could not be sent. '
                f'For testing, your OTP is: {otp}',
                'warning'
            )

        return redirect(url_for('verify_otp'))

    return render_template('signup.html')

@app.route('/verify-otp', methods=['GET','POST'])
def verify_otp():
    # Guard: no pending registration in session
    if 'pending_user' not in session:
        flash('No pending registration found. Please sign up first.', 'error')
        return redirect(url_for('signup'))

    if request.method == 'POST':
        entered_otp = request.form.get('otp', '').strip()

        # Check OTP expiry
        created_at = datetime.strptime(session['otp_created_at'], '%Y-%m-%d %H:%M:%S')
        elapsed_minutes = (datetime.now() - created_at).total_seconds() / 60

        if elapsed_minutes > OTP_EXPIRY_MINUTES:
            # Clear all pending session data — registration must restart
            session.pop('pending_user', None)
            session.pop('pending_otp', None)
            session.pop('otp_created_at', None)
            flash(
                f'Your verification code expired after {OTP_EXPIRY_MINUTES} minutes. '
                f'Please register again.',
                'error'
            )
            return redirect(url_for('signup'))

        # Check OTP match
        if entered_otp != session['pending_otp']:
            flash('Incorrect verification code. Please try again.', 'error')
            return render_template('verify_otp.html',
                                   email=session['pending_user']['email'])

        # ── OTP is correct and not expired — commit to database ───
        u    = session['pending_user']
        conn = get_db()
        try:
            conn.execute(
                '''INSERT INTO users
                   (name, email, enrollment_no, password, role, academic_unit)
                   VALUES (?, ?, ?, ?, 'student', ?)''',
                (u['name'], u['email'], u['enrollment_no'],
                 u['password_hash'], u['academic_unit'])
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # Race condition: someone else registered same email between check and insert
            flash('An account with this email or enrollment number already exists.', 'error')
            conn.close()
            return redirect(url_for('login'))
        finally:
            conn.close()

        # Clear the session freeze — registration complete
        session.pop('pending_user', None)
        session.pop('pending_otp', None)
        session.pop('otp_created_at', None)

        flash('Email verified successfully! Your account has been created. Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('verify_otp.html',
                           email=session['pending_user']['email'])

@app.route('/resend-otp')
def resend_otp():
    if 'pending_user' not in session:
        return redirect(url_for('signup'))

    u   = session['pending_user']
    otp = str(random.randint(100000, 999999))
    session['pending_otp']    = otp
    session['otp_created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    sent = send_otp_email(u['email'], otp, u['name'])
    if sent:
        flash('A new verification code has been sent to your email.', 'success')
    else:
        flash(f'[DEV FALLBACK] New OTP: {otp}', 'warning')

    return redirect(url_for('verify_otp'))

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))

# ─────────────────────────────────────────────
# STUDENT ROUTES
# ─────────────────────────────────────────────
@app.route('/dashboard')
def student_dashboard():
    if 'user_id' not in session or session['user_role'] != 'student':
        return redirect(url_for('login'))

    check_overdue_complaints()

    conn = get_db()

    # Generate token for logged-in student
    my_token = generate_crypto_token(session['enrollment_no'])

    # Fetch:
    # 1. Normal complaints using user_id
    # 2. Anonymous complaints using crypto_token
    complaints = conn.execute(
        '''
        SELECT *
        FROM complaints
        WHERE user_id = ?
           OR crypto_token = ?
        ORDER BY submitted_at DESC
        ''',
        (session['user_id'], my_token)
    ).fetchall()

    conn.close()

    stats = {
        'Pending': 0,
        'In Progress': 0,
        'Resolved': 0
    }

    for c in complaints:
        if c['status'] in stats:
            stats[c['status']] += 1

    return render_template(
        'student_dashboard.html',
        complaints=complaints,
        stats=stats
    )

def safe_classify(title, description, category):
    try:
        from ai_classifier import classify
        return classify(title, description, category)
    except Exception as e:
        print(f"[AI] classify() failed — {e}")
        return {
            'category':     category,
            'routed_to':    category if category in DEPARTMENTS else 'General',
            'confidence':   0.0,
            'source':       'keyword_fallback',
            'mismatch_msg': None,
        }

@app.route('/submit', methods=['GET','POST'])
def submit_complaint():
    if 'user_id' not in session or session['user_role'] != 'student':
        return redirect(url_for('login'))

    # Check rate limit before even showing the form
    if request.method == 'GET':
        conn = get_db()
        my_token     = generate_crypto_token(session.get('enrollment_no', ''))
        named_count  = conn.execute(
            """SELECT COUNT(*) as cnt FROM complaints
               WHERE user_id=? AND submitted_at > datetime('now','-24 hours')""",
            (session['user_id'],)
        ).fetchone()['cnt']
        anon_count   = conn.execute(
            """SELECT COUNT(*) as cnt FROM complaints
               WHERE crypto_token=? AND submitted_at > datetime('now','-24 hours')""",
            (my_token,)
        ).fetchone()['cnt']
        conn.close()
        total_today  = named_count + anon_count
        if total_today >= 3:
            flash('You have reached the limit of 3 complaints per 24 hours. Please try again tomorrow.', 'error')
            return redirect(url_for('student_dashboard'))

    if request.method == 'POST':
        title         = request.form['title'].strip()
        description   = request.form['description'].strip()
        category      = request.form['category'].strip()
        is_anonymous  = 1 if request.form.get('is_anonymous') == 'on' else 0
        is_public     = 1 if request.form.get('is_public')    == 'on' else 0
        academic_unit = session.get('academic_unit', '')

        uploaded_file   = request.files.get('attachment')
        attachment_name = save_file(uploaded_file)
        if uploaded_file and uploaded_file.filename != '' and attachment_name is None:
            flash('Invalid file. Only JPG, PNG, PDF allowed (max 5 MB).', 'error')
            return render_template('submit_complaint.html')

        # Rate limit: max 3 complaints per 24 hours
        # Uses crypto_token for anonymous (user_id is NULL for them, so old check was bypassable)
        conn = get_db()
        is_anonymous_check = 1 if request.form.get('is_anonymous') == 'on' else 0
        if is_anonymous_check:
               my_token     = generate_crypto_token(session.get('enrollment_no', ''))
               recent_count = conn.execute(
                     """SELECT COUNT(*) as cnt FROM complaints
                     WHERE crypto_token=? AND submitted_at > datetime('now','-24 hours')""",
                  (my_token,)
                ).fetchone()['cnt']
        else:
            recent_count = conn.execute(
                  """SELECT COUNT(*) as cnt FROM complaints
                  WHERE user_id=? AND submitted_at > datetime('now','-24 hours')""",
                 (session['user_id'],)
            ).fetchone()['cnt']

        if recent_count >= 3:
            conn.close()
            flash('You have reached the submission limit of 3 complaints per 24 hours.', 'error')
            return redirect(url_for('student_dashboard'))

        result = safe_classify(title, description, category)

        # ── Determine identity storage strategy ───────────────────
        if is_anonymous:
            # ZERO-KNOWLEDGE ANONYMITY:
            # Store ONLY the SHA-256 crypto token, leave user_id as NULL.
            # No admin — not even Central Admin — can see who submitted this
            # through normal database queries.
            enrollment_no = session.get('enrollment_no', '')
            crypto_token  = generate_crypto_token(enrollment_no)
            db_user_id    = None   # explicitly NULL in database
        else:
            # STANDARD: store real user_id, no crypto token
            crypto_token  = None
            db_user_id    = session['user_id']


        # Save the complaint
        conn.execute(
            '''INSERT INTO complaints
               (title, description, category, ai_category, ai_confidence, ai_source,
                routed_to, status, attachment, is_anonymous, is_public, academic_unit,
                upvote_count, submitted_at, user_id, crypto_token)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)''',
            (title, description, category,
             result['category'], result['confidence'], result['source'],
             result['routed_to'], 'Pending', attachment_name,
             is_anonymous, is_public, academic_unit,
             datetime.now().strftime('%Y-%m-%d %H:%M'),
             db_user_id,    # NULL for anonymous
             crypto_token)  # SHA-256 hash for anonymous, NULL otherwise
        )
        conn.commit()
        conn.close()

        if result['mismatch_msg']:
            flash(result['mismatch_msg'], 'warning')
        else:
            anon_note = ' Your identity is cryptographically protected.' if is_anonymous else ''
            flash(f'Complaint submitted successfully!{anon_note}', 'success')

        return redirect(url_for('student_dashboard'))

    return render_template('submit_complaint.html')

# ─────────────────────────────────────────────
# COMPLAINT WITHDRAWAL (crypto-token ownership check)
# ─────────────────────────────────────────────
@app.route('/withdraw/<int:complaint_id>', methods=['POST'])
def withdraw_complaint(complaint_id):
    """
    Allows a student to permanently delete their own complaint.

    Ownership verification uses TWO different strategies depending on
    whether the complaint was submitted anonymously:

    NON-ANONYMOUS:
      Compare session['user_id'] with complaint.user_id (standard FK check)

    ANONYMOUS:
      Recalculate the SHA-256 token from session['enrollment_no'] + SECRET_PEPPER
      and compare it with complaint.crypto_token
      The real identity is NEVER exposed — just two hashes compared.
    """
    # Layer 1: Must be a logged-in student
    if 'user_id' not in session or session['user_role'] != 'student':
        flash('You must be logged in as a student to withdraw a complaint.', 'error')
        return redirect(url_for('login'))

    conn = get_db()
    complaint = conn.execute(
        'SELECT * FROM complaints WHERE id=?', (complaint_id,)
    ).fetchone()

    # Guard: complaint doesn't exist
    if not complaint:
        flash('Complaint not found.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    # Layer 2: Ownership verification
    is_owner = False

    if complaint['is_anonymous'] == 0:
        # Non-anonymous: standard user_id comparison
        is_owner = (complaint['user_id'] == session['user_id'])
    else:
        # Anonymous: recalculate token from enrollment number and compare
        enrollment_no       = session.get('enrollment_no', '')
        my_token            = generate_crypto_token(enrollment_no)
        stored_token        = complaint['crypto_token'] or ''
        is_owner            = (my_token == stored_token)
        # Note: no real identity is exposed in this comparison —
        # just two SHA-256 hashes checked for equality

    if not is_owner:
        flash('Access denied. You can only withdraw your own complaints.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    # Layer 3: Cannot withdraw a Resolved complaint
    if complaint['status'] == 'Resolved':
        flash('Resolved complaints cannot be withdrawn.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    # ── All checks passed — atomic deletion of all related rows ───
    title = complaint['title']

    conn.execute('DELETE FROM complaint_cc          WHERE complaint_id=?', (complaint_id,))
    conn.execute('DELETE FROM notifications         WHERE complaint_id=?', (complaint_id,))
    conn.execute('DELETE FROM complaint_upvotes     WHERE complaint_id=?', (complaint_id,))
    conn.execute('DELETE FROM reroute_log           WHERE complaint_id=?', (complaint_id,))
    conn.execute('DELETE FROM ai_feedback           WHERE complaint_id=?', (complaint_id,))
    conn.execute('DELETE FROM status_audit_log      WHERE complaint_id=?', (complaint_id,))
    conn.execute('DELETE FROM complaints            WHERE id=?',           (complaint_id,))

    conn.commit()
    conn.close()

    flash(f'Complaint "{title}" has been successfully withdrawn.', 'success')
    return redirect(url_for('student_dashboard'))

# ─────────────────────────────────────────────
# CRYPTO ACCOUNTABILITY CHECK (central admin only)
# ─────────────────────────────────────────────
@app.route('/admin/accountability-check', methods=['GET','POST'])
def accountability_check():
    """
    Zero-knowledge accountability mechanism for Central Admin.

    How it works:
      1. Admin inputs a suspected student's enrollment number
      2. System hashes it with SECRET_PEPPER → produces same token as the student would
      3. Checks if that token exists on any anonymous complaints
      4. Returns count and complaint IDs — WITHOUT ever storing/showing the
         enrollment number in the database

    This is 'zero-knowledge' because:
      - The real user_id is never stored on the complaint row
      - No reverse lookup is possible from the crypto_token alone
      - The admin must already suspect a specific student to check
      - The check itself is logged for audit
    """
    if session.get('user_role') != 'superadmin':
        flash('Only Central Admin can access the accountability check.', 'error')
        return redirect(url_for('admin_dashboard'))

    results = None
    checked_enrollment = ''

    if request.method == 'POST':
        checked_enrollment = request.form.get('enrollment_no', '').strip().upper()
        reason             = request.form.get('reason', '').strip()

        if not checked_enrollment:
            flash('Please enter an enrollment number to check.', 'error')
            return render_template('accountability_check.html',
                                   results=None, checked_enrollment='')

        # Generate the token for the suspected enrollment number
        suspected_token = generate_crypto_token(checked_enrollment)

        conn = get_db()

        # Find all anonymous complaints with this token
        matched_complaints = conn.execute(
            '''SELECT id, title, description, routed_to, status, submitted_at, upvote_count
               FROM complaints
               WHERE crypto_token=? AND is_anonymous=1
               ORDER BY submitted_at DESC''',
            (suspected_token,)
        ).fetchall()

        # Log this accountability check (audit trail)
        conn.execute(
            '''INSERT INTO crypto_accountability_log
               (checked_by, enrollment_input, matched_count, checked_at, reason)
               VALUES (?,?,?,?,?)''',
            (session['user_id'], checked_enrollment,
             len(matched_complaints),
             datetime.now().strftime('%Y-%m-%d %H:%M'), reason)
        )
        conn.commit()
        conn.close()

        results = matched_complaints
        if matched_complaints:
            flash(
                f'{len(matched_complaints)} anonymous complaint(s) traced to enrollment '
                f'number {checked_enrollment}. Check logged for audit.',
                'warning'
            )
        else:
            flash(
                f'No anonymous complaints found for enrollment number {checked_enrollment}.',
                'info'
            )

    return render_template('accountability_check.html',
                           results=results,
                           checked_enrollment=checked_enrollment)

# ─────────────────────────────────────────────
# PUBLIC FEED
# ─────────────────────────────────────────────
@app.route('/public-feed')
def public_feed():
    if 'user_id' not in session or session['user_role'] != 'student':
        return redirect(url_for('login'))

    academic_unit = session.get('academic_unit', '')
    conn = get_db()

    feed = conn.execute(
        '''SELECT c.*,
                  CASE WHEN c.is_anonymous=1 THEN 'Anonymous Student' ELSE u.name END as display_name
           FROM complaints c
           LEFT JOIN users u ON c.user_id=u.id
           WHERE c.is_public=1
             AND c.academic_unit=?
             AND c.duplicate_of IS NULL
             AND c.status != 'Resolved'
           ORDER BY c.upvote_count DESC, c.submitted_at DESC
           LIMIT 50''',
        (academic_unit,)
    ).fetchall()

    rows = conn.execute(
        'SELECT complaint_id FROM complaint_upvotes WHERE user_id=?', (session['user_id'],)
    ).fetchall()
    upvoted_ids = {r['complaint_id'] for r in rows}
    conn.close()

    return render_template('public_feed.html',
                           feed=feed, academic_unit=academic_unit,
                           upvoted_ids=upvoted_ids)

@app.route('/upvote/<int:cid>', methods=['POST'])
def upvote_complaint(cid):
    if 'user_id' not in session or session['user_role'] != 'student':
        return redirect(url_for('login'))
    conn = get_db()
    try:
        conn.execute(
            'INSERT OR IGNORE INTO complaint_upvotes (complaint_id,user_id,upvoted_at) VALUES (?,?,?)',
            (cid, session['user_id'], datetime.now().strftime('%Y-%m-%d %H:%M')))
        conn.execute('UPDATE complaints SET upvote_count=upvote_count+1 WHERE id=?', (cid,))
        conn.commit()
        flash('Vote recorded. Admin can now see this issue has more affected students.', 'success')
    except Exception:
        flash('You have already upvoted this complaint.', 'warning')
    conn.close()
    return redirect(url_for('public_feed'))

# ─────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────
@app.route('/notifications')
def notifications():
    if 'user_id' not in session or session['user_role'] != 'student':
        return redirect(url_for('login'))
    conn = get_db()
    notifs = conn.execute(
        '''SELECT n.*, c.title as complaint_title
           FROM notifications n JOIN complaints c ON n.complaint_id=c.id
           WHERE n.user_id=? ORDER BY n.created_at DESC''',
        (session['user_id'],)
    ).fetchall()
    conn.execute('UPDATE notifications SET is_read=1 WHERE user_id=?', (session['user_id'],))
    conn.commit()
    conn.close()
    return render_template('notifications.html', notifs=notifs)

@app.route('/notifications/count')
def notifications_count():
    if 'user_id' not in session:
        return jsonify({'count': 0})
    return jsonify({'count': get_unread_count(session['user_id'])})

# ─────────────────────────────────────────────
# COMPLAINT DETAIL
# ─────────────────────────────────────────────
@app.route('/complaint/<int:cid>')
def complaint_detail(cid):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()

    # LEFT JOIN because anonymous complaints have NULL user_id
    c = conn.execute(
        '''SELECT c.*,
                  COALESCE(u.name,  'Anonymous') as student_name,
                  COALESCE(u.email, '—')         as student_email
           FROM complaints c
           LEFT JOIN users u ON c.user_id=u.id
           WHERE c.id=?''', (cid,)
    ).fetchone()

    if not c:
        flash('Complaint not found.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    role = session['user_role']

    # Students: only own non-anonymous complaints, or anonymous ones they submitted
    if role == 'student':
        if c['is_anonymous']:
            enrollment_no = session.get('enrollment_no', '')
            my_token      = generate_crypto_token(enrollment_no)
            if my_token != (c['crypto_token'] or ''):
                flash('Access denied.', 'error')
                conn.close()
                return redirect(url_for('student_dashboard'))
        elif c['user_id'] != session['user_id']:
            flash('Access denied.', 'error')
            conn.close()
            return redirect(url_for('student_dashboard'))

    if role == 'admin':
        is_primary = (c['routed_to'] == session['user_department'])
        is_ccd     = conn.execute(
            'SELECT id FROM complaint_cc WHERE complaint_id=? AND cc_dept=?',
            (cid, session['user_department'])
        ).fetchone()
        if not is_primary and not is_ccd:
            flash('Access denied.', 'error')
            conn.close()
            return redirect(url_for('admin_dashboard'))

    reroutes = conn.execute(
        '''SELECT r.*, u.name as done_by_name
           FROM reroute_log r JOIN users u ON r.rerouted_by=u.id
           WHERE r.complaint_id=? ORDER BY r.rerouted_at ASC''', (cid,)
    ).fetchall()
    cc_rows  = conn.execute('SELECT cc_dept FROM complaint_cc WHERE complaint_id=?', (cid,)).fetchall()
    cc_depts = [r['cc_dept'] for r in cc_rows]
    conn.close()

    return render_template('complaint_detail.html',
        c=c, reroutes=reroutes, cc_depts=cc_depts,
        role=role)

# ─────────────────────────────────────────────
# ADMIN ROUTES
# ─────────────────────────────────────────────
@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or session['user_role'] not in ('admin','superadmin'):
        return redirect(url_for('login'))
    check_overdue_complaints()

    is_super  = (session['user_role'] == 'superadmin')
    user_dept = session.get('user_department')

    filter_dept   = request.args.get('category', '')
    filter_status = request.args.get('status', '')
    search_query  = request.args.get('search', '').strip()

    conn = get_db()

    def fetch(primary_where, cc_where, p_params, cc_params):
        # Anonymous complaints: show masked identity to ALL admins including superadmin
        # Only the accountability check tool can trace anonymous complaints
        name_expr = """
            CASE WHEN c.is_anonymous=1 THEN '🔒 Anonymous'
                 ELSE COALESCE(u.name, '—') END as student_name,
            CASE WHEN c.is_anonymous=1 THEN '—'
                 ELSE COALESCE(u.email, '—') END as student_email
        """
        bq = f'''SELECT c.*, {name_expr}, NULL as cc_dept_label
                 FROM complaints c LEFT JOIN users u ON c.user_id=u.id
                 WHERE {primary_where}'''
        cq = f'''SELECT c.*, {name_expr}, cc.cc_dept as cc_dept_label
                 FROM complaints c LEFT JOIN users u ON c.user_id=u.id
                 JOIN complaint_cc cc ON cc.complaint_id=c.id
                 WHERE {cc_where}'''

        if filter_status:
            bq += ' AND c.status=?';  p_params.append(filter_status)
            cq += ' AND c.status=?';  cc_params.append(filter_status)
        if search_query:
            bq += ' AND (c.title LIKE ? OR c.description LIKE ?)'; p_params  += [f'%{search_query}%', f'%{search_query}%']
            cq += ' AND (c.title LIKE ? OR c.description LIKE ?)'; cc_params += [f'%{search_query}%', f'%{search_query}%']

        bq += ' ORDER BY c.upvote_count DESC, c.submitted_at DESC'
        cq += ' ORDER BY c.upvote_count DESC, c.submitted_at DESC'

        direct     = list(conn.execute(bq, p_params).fetchall())
        ccd        = list(conn.execute(cq, cc_params).fetchall())
        direct_ids = {row['id'] for row in direct}
        return direct + [row for row in ccd if row['id'] not in direct_ids]

    if is_super:
        pw = 'c.routed_to=?' if filter_dept else '1=1'
        cw = 'cc.cc_dept=?'  if filter_dept else '1=1'
        pp = [filter_dept] if filter_dept else []
        cp = [filter_dept] if filter_dept else []
        complaints = fetch(pw, cw, pp, cp)
    else:
        complaints = fetch('c.routed_to=?', 'cc.cc_dept=?', [user_dept], [user_dept])

    cc_map = {}
    for row in complaints:
        cid = row['id']
        if cid not in cc_map:
            ccs = conn.execute('SELECT cc_dept FROM complaint_cc WHERE complaint_id=?', (cid,)).fetchall()
            cc_map[cid] = [r['cc_dept'] for r in ccs]
    conn.close()

    stats = {'Pending':0,'In Progress':0,'Resolved':0,'Total':len(complaints)}
    for c in complaints:
        if c['status'] in stats:
            stats[c['status']] += 1

    return render_template('admin_dashboard.html',
        complaints=complaints, cc_map=cc_map, stats=stats,
        is_super=is_super, user_dept=user_dept,
        selected_category=filter_dept, selected_status=filter_status,
        search_query=search_query, today=date.today().isoformat())

@app.route('/admin/update/<int:cid>', methods=['POST'])
def update_status(cid):
    if 'user_id' not in session or session['user_role'] not in ('admin','superadmin'):
        return redirect(url_for('login'))

    new_status   = request.form['status']
    admin_remark = request.form.get('admin_remark','').strip()
    resolve_by   = request.form.get('resolve_by','').strip()

    conn      = get_db()
    complaint = conn.execute('SELECT * FROM complaints WHERE id=?', (cid,)).fetchone()
    if not complaint:
        flash('Complaint not found.', 'error')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    if session['user_role'] == 'admin':
        is_primary = (complaint['routed_to'] == session['user_department'])
        is_ccd     = conn.execute(
            'SELECT id FROM complaint_cc WHERE complaint_id=? AND cc_dept=?',
            (cid, session['user_department'])).fetchone()
        if not is_primary and not is_ccd:
            flash('Unauthorized.', 'error')
            conn.close()
            return redirect(url_for('admin_dashboard'))

    process_status_change(cid, new_status, admin_remark, resolve_by, session['user_id'], conn)
    conn.commit()
    conn.close()
    flash(f'Complaint #{cid} updated to "{new_status}". Student notified automatically.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reroute/<int:cid>', methods=['POST'])
def reroute_complaint(cid):
    if 'user_id' not in session or session['user_role'] not in ('admin','superadmin'):
        return redirect(url_for('login'))

    new_dept = request.form['new_dept'].strip()
    note     = request.form.get('note','').strip()
    cc_depts = request.form.getlist('cc_depts')

    if new_dept not in DEPARTMENTS:
        flash('Invalid department.', 'error')
        return redirect(url_for('admin_dashboard'))

    conn = get_db()
    row  = conn.execute('SELECT * FROM complaints WHERE id=?', (cid,)).fetchone()
    if not row:
        flash('Complaint not found.', 'error')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    if session['user_role'] == 'admin' and row['routed_to'] != session['user_department']:
        flash('You can only re-route complaints in your department.', 'error')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    old_dept = row['routed_to']
    conn.execute('UPDATE complaints SET routed_to=? WHERE id=?', (new_dept, cid))
    conn.execute(
        'INSERT INTO reroute_log (complaint_id,from_dept,to_dept,rerouted_by,rerouted_at,note) VALUES (?,?,?,?,?,?)',
        (cid, old_dept, new_dept, session['user_id'], datetime.now().strftime('%Y-%m-%d %H:%M'), note))

    conn.execute('DELETE FROM complaint_cc WHERE complaint_id=?', (cid,))
    for cc in cc_depts:
        if cc and cc != new_dept and cc in DEPARTMENTS:
            conn.execute('INSERT INTO complaint_cc (complaint_id,cc_dept) VALUES (?,?)', (cid, cc))

    from_label = DEPARTMENTS.get(old_dept,{}).get('label', old_dept)
    to_label   = DEPARTMENTS.get(new_dept,{}).get('label', new_dept)

    # Only notify if non-anonymous complaint
    if row['user_id']:
        msg = f'Your complaint "{row["title"]}" was re-routed from {from_label} to {to_label}.'
        if note: msg += f' Reason: {note}'
        conn.execute(
            'INSERT INTO notifications (user_id,complaint_id,message,is_read,created_at) VALUES (?,?,?,0,?)',
            (row['user_id'], cid, msg, datetime.now().strftime('%Y-%m-%d %H:%M')))

    conn.commit()
    conn.close()
    flash(f'Complaint #{cid} re-routed from {from_label} → {to_label}.', 'success')
    return redirect(url_for('admin_dashboard'))

# ─────────────────────────────────────────────
# FILE SERVING
# ─────────────────────────────────────────────
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session['user_role'] in ('admin','superadmin'):
        return send_from_directory(UPLOAD_FOLDER, filename)
    conn = get_db()
    row  = conn.execute('SELECT user_id FROM complaints WHERE attachment=?', (filename,)).fetchone()
    conn.close()
    if row and row['user_id'] == session['user_id']:
        return send_from_directory(UPLOAD_FOLDER, filename)
    flash('Access denied.', 'error')
    return redirect(url_for('student_dashboard'))

if __name__ == '__main__':

    # Initialize database
    init_db()

    print("\n✅ Database initialized.")
    print("\n📋 Login Accounts:")
    print("   Central Admin →  admin@college.edu / admin123")

    for key, d in DEPARTMENTS.items():
        if key != 'General':
            print(f"   {d['label']:<22} →  {d['email']}")

    print("\n🚀 Starting server at http://127.0.0.1:5000\n")

    app.run(debug=True)