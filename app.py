"""
app.py — GrievanceIQ Backend
Features: OTP verification, authenticated anonymity,
          scoped public feed, AI duplicate deflection
"""

from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, send_from_directory, jsonify)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3, os, uuid, random, smtplib, pickle
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from ai_classifier import classify

app = Flask(__name__)
app.secret_key = 'grievance_secret_key_2024'

# ─────────────────────────────────────────────
# EMAIL CONFIGURATION  ← update these
# ─────────────────────────────────────────────
SMTP_SERVER   = 'smtp.gmail.com'
SMTP_PORT     = 587
SMTP_EMAIL    = 'your_grievanceiq_email@gmail.com'   # Gmail you create for the app
SMTP_PASSWORD = 'your_app_password_here'             # Gmail App Password (not login password)
OTP_EXPIRY_MINUTES = 10

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
# DEPARTMENT CONFIGURATION
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
    'Engineering', 'Bioscience', 'Management'
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
        academic_unit   TEXT    DEFAULT NULL,
        is_suspended    INTEGER DEFAULT 0
    )''')

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
        user_id        INTEGER NOT NULL,
        submitted_at   TEXT    NOT NULL,
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

    c.execute('''CREATE TABLE IF NOT EXISTS ai_feedback (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id     INTEGER NOT NULL,
        complaint_text   TEXT    NOT NULL,
        ai_predicted     TEXT    NOT NULL,
        correct_label    TEXT    NOT NULL,
        corrected_by     INTEGER NOT NULL,
        corrected_at     TEXT    NOT NULL,
        used_in_training INTEGER DEFAULT 0,
        FOREIGN KEY(complaint_id) REFERENCES complaints(id),
        FOREIGN KEY(corrected_by) REFERENCES users(id)
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

    c.execute('''CREATE TABLE IF NOT EXISTS anonymous_identity_log (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id INTEGER NOT NULL,
        user_id      INTEGER NOT NULL,
        revealed_by  INTEGER DEFAULT NULL,
        revealed_at  TEXT    DEFAULT NULL,
        reason       TEXT    DEFAULT NULL,
        FOREIGN KEY(complaint_id) REFERENCES complaints(id),
        FOREIGN KEY(user_id)      REFERENCES users(id)
    )''')

    # Super admin
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
# OTP EMAIL HELPER
# ─────────────────────────────────────────────
def send_otp_email(recipient_email, otp_code, student_name):
    """Sends OTP verification email via Gmail SMTP."""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'GrievanceIQ — Verify Your Email Address'
        msg['From']    = SMTP_EMAIL
        msg['To']      = recipient_email

        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 2rem;
                    border: 1px solid #e2e0da; border-radius: 12px;">
            <h2 style="color: #1a1a2e;">Hello, {student_name}!</h2>
            <p style="color: #4a4a6a;">
                You're registering on <strong>GrievanceIQ</strong>.
                Use the code below to verify your email address.
            </p>
            <div style="background: #f8f7f4; border-radius: 8px; padding: 1.5rem;
                        text-align: center; margin: 1.5rem 0;">
                <span style="font-size: 2.5rem; font-weight: 700;
                             letter-spacing: 8px; color: #e63946;">
                    {otp_code}
                </span>
            </div>
            <p style="color: #4a4a6a; font-size: .9rem;">
                This code expires in <strong>{OTP_EXPIRY_MINUTES} minutes</strong>.
                If you did not request this, simply ignore this email.
            </p>
        </div>
        """
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, recipient_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False

# ─────────────────────────────────────────────
# DUPLICATE DETECTION HELPER
# ─────────────────────────────────────────────
def check_duplicate(new_text, new_dept, user_academic_unit, conn):
    """
    Metadata-gated cosine similarity check.
    Only compares complaints in same dept + same academic unit + last 30 days.
    Returns (is_duplicate, similar_complaint_id, similarity_score).
    """
    candidates = conn.execute(
        '''SELECT c.id, c.title, c.description
           FROM complaints c
           JOIN users u ON c.user_id = u.id
           WHERE c.routed_to = ?
             AND c.academic_unit = ?
             AND c.submitted_at > datetime('now', '-30 days')
             AND c.duplicate_of IS NULL
             AND c.is_public = 1
             AND c.status != 'Resolved'
           LIMIT 50''',
        (new_dept, user_academic_unit)
    ).fetchall()

    if not candidates:
        return False, None, 0.0

    model_path = os.path.join('model', 'grievance_model.pkl')
    if not os.path.exists(model_path):
        return False, None, 0.0

    with open(model_path, 'rb') as f:
        pipeline = pickle.load(f)

    vectorizer = pipeline.named_steps['tfidf']
    corpus     = [f"{r['title']} {r['description']}" for r in candidates]

    new_vec    = vectorizer.transform([new_text])
    exist_vecs = vectorizer.transform(corpus)
    sims       = cosine_similarity(new_vec, exist_vecs)[0]
    max_idx    = int(np.argmax(sims))
    max_score  = float(sims[max_idx])

    THRESHOLD = 0.75
    if max_score >= THRESHOLD:
        return True, candidates[max_idx]['id'], max_score

    return False, None, 0.0

# ─────────────────────────────────────────────
# STATUS CHANGE SERVICE (atomic, all side effects)
# ─────────────────────────────────────────────
def process_status_change(cid, new_status, admin_remark, resolve_by, changed_by_id, conn):
    complaint  = conn.execute('SELECT * FROM complaints WHERE id=?', (cid,)).fetchone()
    old_status = complaint['status']
    if old_status == new_status:
        return

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    try:
        submitted         = datetime.strptime(complaint['submitted_at'], '%Y-%m-%d %H:%M')
        hours_in_status   = (datetime.now() - submitted).total_seconds() / 3600
    except Exception:
        hours_in_status   = None

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

    notif_msg = f'Your complaint "{complaint["title"]}" has been updated to "{new_status}".'
    if admin_remark:
        notif_msg += f' Admin note: {admin_remark}'
    conn.execute(
        'INSERT INTO notifications (user_id,complaint_id,message,is_read,created_at) VALUES (?,?,?,0,?)',
        (complaint['user_id'], cid, notif_msg, now_str))

# ─────────────────────────────────────────────
# AUTH — SIGNUP WITH OTP
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

        if user and user['is_suspended']:
            flash('Your account has been suspended. Contact the administrator.', 'error')
            return render_template('login.html')

        if user and check_password_hash(user['password'], password):
            session['user_id']         = user['id']
            session['user_name']       = user['name']
            session['user_role']       = user['role']
            session['user_department'] = user['department']
            session['academic_unit']   = user['academic_unit']
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
        enrollment_no = request.form['enrollment_no'].strip()
        academic_unit = request.form['academic_unit'].strip()
        password      = request.form['password'].strip()

        # Check email/enrollment not already registered
        conn = get_db()
        exists_email = conn.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        exists_enr   = conn.execute('SELECT id FROM users WHERE enrollment_no=?', (enrollment_no,)).fetchone()
        conn.close()

        if exists_email:
            flash('This email is already registered.', 'error')
            return render_template('signup.html')
        if exists_enr:
            flash('This enrollment number is already registered.', 'error')
            return render_template('signup.html')

        # Generate OTP
        otp = str(random.randint(100000, 999999))

        # Freeze registration data in session
        session['pending_user'] = {
            'name':          name,
            'email':         email,
            'enrollment_no': enrollment_no,
            'academic_unit': academic_unit,
            'password':      generate_password_hash(password),
        }
        session['pending_otp']      = otp
        session['otp_created_at']   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Send OTP email
        sent = send_otp_email(email, otp, name)
        if sent:
            flash(f'A 6-digit verification code has been sent to {email}. Check your inbox.', 'info')
        else:
            # Dev fallback — show OTP in flash if email fails (remove in production)
            flash(f'[DEV MODE] Email send failed. Your OTP is: {otp}', 'warning')

        return redirect(url_for('verify_otp'))

    return render_template('signup.html')

@app.route('/verify-otp', methods=['GET','POST'])
def verify_otp():
    if 'pending_user' not in session:
        flash('No pending registration found. Please sign up again.', 'error')
        return redirect(url_for('signup'))

    if request.method == 'POST':
        entered_otp = request.form['otp'].strip()

        # Check expiry
        created_at = datetime.strptime(session['otp_created_at'], '%Y-%m-%d %H:%M:%S')
        elapsed    = (datetime.now() - created_at).total_seconds() / 60
        if elapsed > OTP_EXPIRY_MINUTES:
            session.pop('pending_user', None)
            session.pop('pending_otp', None)
            session.pop('otp_created_at', None)
            flash(f'OTP expired after {OTP_EXPIRY_MINUTES} minutes. Please register again.', 'error')
            return redirect(url_for('signup'))

        if entered_otp != session['pending_otp']:
            flash('Incorrect OTP. Please try again.', 'error')
            return render_template('verify_otp.html',
                                   email=session['pending_user']['email'])

        # OTP correct — save user to database
        u    = session['pending_user']
        conn = get_db()
        try:
            conn.execute(
                '''INSERT INTO users (name,email,enrollment_no,password,role,academic_unit)
                   VALUES (?,?,?,?,?,?)''',
                (u['name'], u['email'], u['enrollment_no'],
                 u['password'], 'student', u['academic_unit']))
            conn.commit()
        except sqlite3.IntegrityError:
            flash('Account already exists. Please log in.', 'error')
            conn.close()
            return redirect(url_for('login'))
        finally:
            conn.close()

        # Clear pending session data
        session.pop('pending_user', None)
        session.pop('pending_otp', None)
        session.pop('otp_created_at', None)

        flash('Email verified! Your account has been created. Please log in.', 'success')
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
        flash('A new OTP has been sent to your email.', 'success')
    else:
        flash(f'[DEV MODE] New OTP: {otp}', 'warning')
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
    complaints = conn.execute(
        'SELECT * FROM complaints WHERE user_id=? ORDER BY submitted_at DESC',
        (session['user_id'],)
    ).fetchall()
    conn.close()
    stats = {'Pending':0,'In Progress':0,'Resolved':0}
    for c in complaints:
        if c['status'] in stats:
            stats[c['status']] += 1
    return render_template('student_dashboard.html', complaints=complaints, stats=stats)

@app.route('/submit', methods=['GET','POST'])
def submit_complaint():
    if 'user_id' not in session or session['user_role'] != 'student':
        return redirect(url_for('login'))

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
            flash('Invalid file type or size. Only JPG, PNG, PDF allowed (max 5 MB).', 'error')
            return render_template('submit_complaint.html')

        # Rate limit — max 3 complaints per 24 hours
        conn = get_db()
        recent_count = conn.execute(
            """SELECT COUNT(*) as cnt FROM complaints
               WHERE user_id=? AND submitted_at > datetime('now','-24 hours')""",
            (session['user_id'],)
        ).fetchone()['cnt']

        if recent_count >= 3:
            conn.close()
            flash('You have reached the submission limit of 3 complaints per 24 hours.', 'error')
            return redirect(url_for('student_dashboard'))

        result = classify(title, description, category)

        # ── Duplicate detection (only for public complaints) ──
        if is_public and academic_unit:
            new_text = f"{title} {description}"
            is_dup, dup_id, score = check_duplicate(
                new_text, result['routed_to'], academic_unit, conn
            )
            if is_dup:
                # Upvote existing complaint instead of creating new one
                try:
                    conn.execute(
                        'INSERT OR IGNORE INTO complaint_upvotes (complaint_id,user_id,upvoted_at) VALUES (?,?,?)',
                        (dup_id, session['user_id'], datetime.now().strftime('%Y-%m-%d %H:%M')))
                    conn.execute(
                        'UPDATE complaints SET upvote_count = upvote_count + 1 WHERE id=?',
                        (dup_id,))
                    conn.commit()
                    dup_count = conn.execute(
                        'SELECT upvote_count FROM complaints WHERE id=?', (dup_id,)
                    ).fetchone()['upvote_count']
                    conn.close()
                    flash(
                        f'A very similar complaint already exists in your department '
                        f'(similarity: {score*100:.0f}%). '
                        f'Your vote has been added — {dup_count} student(s) are now affected. '
                        f'The admin has been notified of the priority.',
                        'warning'
                    )
                    return redirect(url_for('public_feed'))
                except Exception:
                    pass  # Fall through and save as new complaint

        # Save complaint
        conn.execute(
            '''INSERT INTO complaints
               (title,description,category,ai_category,ai_confidence,ai_source,
                routed_to,status,attachment,is_anonymous,is_public,academic_unit,
                upvote_count,user_id,submitted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)''',
            (title, description, category,
             result['category'], result['confidence'], result['source'],
             result['routed_to'], 'Pending', attachment_name,
             is_anonymous, is_public, academic_unit,
             session['user_id'], datetime.now().strftime('%Y-%m-%d %H:%M')))
        conn.commit()
        conn.close()

        if result['mismatch_msg']:
            flash(result['mismatch_msg'], 'warning')
        else:
            flash('Complaint submitted successfully! It has been routed to the correct department.', 'success')
        return redirect(url_for('student_dashboard'))

    return render_template('submit_complaint.html')


# ─────────────────────────────────────────────
# COMPLAINT WITHDRAWAL
# ─────────────────────────────────────────────
@app.route('/withdraw/<int:complaint_id>', methods=['POST'])
def withdraw_complaint(complaint_id):
    """
    Allows a student to permanently delete their own complaint,
    but only if it has not yet been Resolved.

    Security layers:
      1. Session check  — must be a logged-in student
      2. Ownership check — complaint's user_id must match session user_id
      3. Status check   — cannot withdraw a Resolved complaint
    All three must pass before the DELETE executes.
    """

    # ── Layer 1: Session & role check ─────────────────────────────
    # If somehow a non-student hits this route, block immediately.
    if 'user_id' not in session or session['user_role'] != 'student':
        flash('You must be logged in as a student to withdraw a complaint.', 'error')
        return redirect(url_for('login'))

    conn = get_db()

    # ── Fetch the complaint row ────────────────────────────────────
    # Use parameterised query (?) to prevent SQL injection.
    complaint = conn.execute(
        'SELECT * FROM complaints WHERE id = ?', (complaint_id,)
    ).fetchone()

    # Guard: complaint doesn't exist at all
    if not complaint:
        flash('Complaint not found.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    # ── Layer 2: Ownership verification ───────────────────────────
    # Compare the complaint's stored user_id with the session user_id.
    # This prevents Student A from deleting Student B's complaints
    # by manually crafting a POST request to /withdraw/<id>.
    if complaint['user_id'] != session['user_id']:
        flash('Access denied. You can only withdraw your own complaints.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    # ── Layer 3: Status check ──────────────────────────────────────
    # A Resolved complaint has already been acted upon by the department.
    # Allowing withdrawal after resolution would corrupt the audit trail.
    if complaint['status'] == 'Resolved':
        flash('Resolved complaints cannot be withdrawn.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    # ── All checks passed — perform atomic deletion ────────────────
    # Delete dependent rows first (foreign key constraints) then the complaint.

    # Delete CC entries for this complaint
    conn.execute('DELETE FROM complaint_cc WHERE complaint_id = ?', (complaint_id,))

    # Delete notifications linked to this complaint
    conn.execute('DELETE FROM notifications WHERE complaint_id = ?', (complaint_id,))

    # Delete upvotes linked to this complaint
    conn.execute('DELETE FROM complaint_upvotes WHERE complaint_id = ?', (complaint_id,))

    # Delete reroute log entries
    conn.execute('DELETE FROM reroute_log WHERE complaint_id = ?', (complaint_id,))

    # Delete AI feedback entries
    conn.execute('DELETE FROM ai_feedback WHERE complaint_id = ?', (complaint_id,))

    # Delete audit log entries
    conn.execute('DELETE FROM status_audit_log WHERE complaint_id = ?', (complaint_id,))

    # Delete anonymous identity log entries
    conn.execute('DELETE FROM anonymous_identity_log WHERE complaint_id = ?', (complaint_id,))

    # Finally delete the complaint itself
    conn.execute('DELETE FROM complaints WHERE id = ?', (complaint_id,))

    # Commit all deletions as one atomic transaction.
    # If anything above fails, nothing gets deleted (all-or-nothing).
    conn.commit()
    conn.close()

    flash(
        f'Complaint "{complaint["title"]}" has been successfully withdrawn '
        f'and removed from the system.',
        'success'
    )
    return redirect(url_for('student_dashboard'))

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
           FROM complaints c JOIN users u ON c.user_id=u.id
           WHERE c.is_public=1
             AND c.academic_unit=?
             AND c.duplicate_of IS NULL
             AND c.status != 'Resolved'
           ORDER BY c.upvote_count DESC, c.submitted_at DESC
           LIMIT 50''',
        (academic_unit,)
    ).fetchall()

    # Check which complaints this student has already upvoted
    upvoted_ids = set()
    rows = conn.execute(
        'SELECT complaint_id FROM complaint_upvotes WHERE user_id=?', (session['user_id'],)
    ).fetchall()
    upvoted_ids = {r['complaint_id'] for r in rows}
    conn.close()

    return render_template('public_feed.html',
                           feed=feed,
                           academic_unit=academic_unit,
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
        conn.execute(
            'UPDATE complaints SET upvote_count = upvote_count + 1 WHERE id=?', (cid,))
        conn.commit()
        flash('Your vote has been recorded. The admin will see this issue has more affected students.', 'success')
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
    c = conn.execute(
        '''SELECT c.*, u.name as student_name, u.email as student_email
           FROM complaints c JOIN users u ON c.user_id=u.id WHERE c.id=?''', (cid,)
    ).fetchone()
    if not c:
        flash('Complaint not found.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    role = session['user_role']
    if role == 'student' and c['user_id'] != session['user_id']:
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
    existing_feedback = conn.execute('SELECT * FROM ai_feedback WHERE complaint_id=?', (cid,)).fetchone()
    conn.close()

    return render_template('complaint_detail.html',
        c=c, reroutes=reroutes, cc_depts=cc_depts,
        role=role, existing_feedback=existing_feedback)

@app.route('/complaint/<int:cid>/feedback', methods=['POST'])
def submit_ai_feedback(cid):
    if 'user_id' not in session or session['user_role'] not in ('admin','superadmin'):
        return redirect(url_for('login'))
    correct_label = request.form.get('correct_label','').strip()
    if not correct_label or correct_label not in DEPARTMENTS:
        flash('Please select a valid department.', 'error')
        return redirect(url_for('complaint_detail', cid=cid))
    conn = get_db()
    c = conn.execute('SELECT * FROM complaints WHERE id=?', (cid,)).fetchone()
    existing = conn.execute('SELECT id FROM ai_feedback WHERE complaint_id=?', (cid,)).fetchone()
    if existing:
        flash('Feedback already submitted for this complaint.', 'warning')
        conn.close()
        return redirect(url_for('complaint_detail', cid=cid))
    conn.execute(
        '''INSERT INTO ai_feedback
           (complaint_id,complaint_text,ai_predicted,correct_label,corrected_by,corrected_at,used_in_training)
           VALUES (?,?,?,?,?,?,0)''',
        (cid, f"{c['title']} {c['description']}", c['ai_category'],
         correct_label, session['user_id'], datetime.now().strftime('%Y-%m-%d %H:%M')))
    conn.commit()
    conn.close()
    flash(f'AI correction saved. The model will learn this next time train_model.py is run.', 'success')
    return redirect(url_for('complaint_detail', cid=cid))

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
        # For superadmin show real names; for dept admin mask anonymous
        if is_super:
            name_expr  = "u.name as student_name, u.email as student_email"
        else:
            name_expr  = """CASE WHEN c.is_anonymous=1 THEN '🔒 Masked Identity'
                                 ELSE u.name END as student_name,
                            CASE WHEN c.is_anonymous=1 THEN '—'
                                 ELSE u.email END as student_email"""

        bq = f'''SELECT c.*, {name_expr}, NULL as cc_dept_label
                 FROM complaints c JOIN users u ON c.user_id=u.id
                 WHERE {primary_where}'''
        cq = f'''SELECT c.*, {name_expr}, cc.cc_dept as cc_dept_label
                 FROM complaints c JOIN users u ON c.user_id=u.id
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
    msg = f'Your complaint "{row["title"]}" was re-routed from {from_label} to {to_label}.'
    if note: msg += f' Reason: {note}'
    conn.execute(
        'INSERT INTO notifications (user_id,complaint_id,message,is_read,created_at) VALUES (?,?,?,0,?)',
        (row['user_id'], cid, msg, datetime.now().strftime('%Y-%m-%d %H:%M')))
    conn.commit()
    conn.close()

    flash(f'Complaint #{cid} re-routed from {from_label} → {to_label}.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reveal_identity/<int:cid>', methods=['POST'])
def reveal_identity(cid):
    """Super admin only — reveals anonymous student identity with audit log."""
    if session.get('user_role') != 'superadmin':
        flash('Only super admin can reveal anonymous identities.', 'error')
        return redirect(url_for('admin_dashboard'))

    reason = request.form.get('reason','').strip()
    conn   = get_db()
    c      = conn.execute('SELECT user_id FROM complaints WHERE id=?', (cid,)).fetchone()
    if c:
        conn.execute(
            '''INSERT INTO anonymous_identity_log
               (complaint_id,user_id,revealed_by,revealed_at,reason)
               VALUES (?,?,?,?,?)''',
            (cid, c['user_id'], session['user_id'],
             datetime.now().strftime('%Y-%m-%d %H:%M'), reason))
        conn.commit()
    conn.close()
    flash('Identity revealed and logged for audit. Check the complaint detail page.', 'warning')
    return redirect(url_for('complaint_detail', cid=cid))

@app.route('/admin/suspend/<int:uid>', methods=['POST'])
def suspend_user(uid):
    """Super admin only — suspends a student account."""
    if session.get('user_role') != 'superadmin':
        flash('Only super admin can suspend accounts.', 'error')
        return redirect(url_for('admin_dashboard'))
    conn = get_db()
    conn.execute('UPDATE users SET is_suspended=1 WHERE id=?', (uid,))
    conn.commit()
    conn.close()
    flash(f'User account has been suspended.', 'warning')
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
    init_db()
    print("\n✅ Database initialized.")
    print("\n📋 Login Accounts:")
    print("   Super Admin  →  admin@college.edu / admin123")
    for key, d in DEPARTMENTS.items():
        if key != 'General':
            print(f"   {d['label']:<22} →  {d['email']}")
    print("\n🚀 Starting server at http://127.0.0.1:5000\n")
    app.run(debug=True)