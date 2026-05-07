"""
app.py — GrievanceIQ Backend
────────────────────────────
Run AFTER training the model:
    1.  python train_model.py     (once)
    2.  python app.py             (every time to start the server)
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import os
import uuid
from datetime import datetime, date
from ai_classifier import classify   # ← new ML-based classifier

app = Flask(__name__)
app.secret_key = 'grievance_secret_key_2024'

# ─────────────────────────────────────────────
# FILE UPLOAD CONFIGURATION
# ─────────────────────────────────────────────

UPLOAD_FOLDER   = 'uploads'
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'pdf'}
MAX_FILE_MB     = 5
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_MB * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_file(file):
    if not file or file.filename == '':
        return None
    if not allowed_file(file.filename):
        return None
    ext          = file.filename.rsplit('.', 1)[1].lower()
    safe_name    = secure_filename(file.filename.rsplit('.', 1)[0])
    unique_name  = f"{uuid.uuid4().hex[:8]}-{safe_name}.{ext}"
    file.save(os.path.join(UPLOAD_FOLDER, unique_name))
    return unique_name

# ─────────────────────────────────────────────
# DEPARTMENT CONFIGURATION
# ─────────────────────────────────────────────

DEPARTMENTS = {
    'Hostel':    {'label': 'Hostel / Warden',     'icon': '🏠', 'email': 'warden@college.edu',    'password': 'warden123'},
    'IT':        {'label': 'IT Department',        'icon': '💻', 'email': 'it@college.edu',         'password': 'it123'},
    'Academic':  {'label': 'Academic / Exam Cell', 'icon': '📚', 'email': 'academic@college.edu',   'password': 'academic123'},
    'Library':   {'label': 'Library',              'icon': '📖', 'email': 'library@college.edu',    'password': 'library123'},
    'Transport': {'label': 'Transport',            'icon': '🚌', 'email': 'transport@college.edu',  'password': 'transport123'},
    'Finance':   {'label': 'Finance / Fees',       'icon': '💰', 'email': 'finance@college.edu',    'password': 'finance123'},
    'General':   {'label': 'General Admin',        'icon': '📋', 'email': 'admin@college.edu',      'password': 'admin123'},
}

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

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            email      TEXT    UNIQUE NOT NULL,
            password   TEXT    NOT NULL,
            role       TEXT    NOT NULL DEFAULT 'student',
            department TEXT    DEFAULT NULL
        )
    ''')

    # complaints table — now includes admin_remark, resolve_by, is_overdue
    c.execute('''
        CREATE TABLE IF NOT EXISTS complaints (
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
            user_id        INTEGER NOT NULL,
            submitted_at   TEXT    NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS reroute_log (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id   INTEGER NOT NULL,
            from_dept      TEXT    NOT NULL,
            to_dept        TEXT    NOT NULL,
            rerouted_by    INTEGER NOT NULL,
            rerouted_at    TEXT    NOT NULL,
            note           TEXT    DEFAULT '',
            FOREIGN KEY(complaint_id) REFERENCES complaints(id),
            FOREIGN KEY(rerouted_by) REFERENCES users(id)
        )
    ''')

    # NEW — CC table for Feature 2
    c.execute('''
        CREATE TABLE IF NOT EXISTS complaint_cc (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id INTEGER NOT NULL,
            cc_dept      TEXT    NOT NULL,
            FOREIGN KEY(complaint_id) REFERENCES complaints(id)
        )
    ''')

    # Super admin
    existing = c.execute("SELECT id FROM users WHERE email='admin@college.edu'").fetchone()
    if not existing:
        c.execute(
            'INSERT INTO users (name,email,password,role,department) VALUES (?,?,?,?,?)',
            ('Super Admin', 'admin@college.edu',
             generate_password_hash('admin123'), 'superadmin', None)
        )

    # Department heads
    for dept_key, dept_info in DEPARTMENTS.items():
        if dept_key == 'General':
            continue
        existing = c.execute('SELECT id FROM users WHERE email=?', (dept_info['email'],)).fetchone()
        if not existing:
            c.execute(
                'INSERT INTO users (name,email,password,role,department) VALUES (?,?,?,?,?)',
                (dept_info['label'] + ' Head', dept_info['email'],
                 generate_password_hash(dept_info['password']), 'admin', dept_key)
            )

    conn.commit()
    conn.close()


def check_overdue_complaints():
    """Flag complaints as overdue if resolve_by has passed and not yet resolved."""
    today = date.today().isoformat()
    conn = get_db()
    conn.execute('''
        UPDATE complaints SET is_overdue = 1
        WHERE resolve_by IS NOT NULL
          AND resolve_by < ?
          AND status != 'Resolved'
          AND is_overdue = 0
    ''', (today,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# AUTHENTICATION
# ─────────────────────────────────────────────

@app.route('/')
def home():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email'].strip()
        password = request.form['password'].strip()

        conn = get_db()
        user = conn.execute(
            'SELECT * FROM users WHERE email = ?', (email,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id']         = user['id']
            session['user_name']       = user['name']
            session['user_role']       = user['role']
            session['user_department'] = user['department']
            flash(f"Welcome, {user['name']}!", 'success')
            if user['role'] in ('admin', 'superadmin'):
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid email or password.', 'error')

    return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name     = request.form['name'].strip()
        email    = request.form['email'].strip()
        password = request.form['password'].strip()

        conn = get_db()
        try:
            conn.execute(
                'INSERT INTO users (name,email,password,role) VALUES (?,?,?,?)',
                (name, email, generate_password_hash(password), 'student')
            )
            conn.commit()
            flash('Account created! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('This email is already registered.', 'error')
        finally:
            conn.close()

    return render_template('signup.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
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

    stats = {'Pending': 0, 'In Progress': 0, 'Resolved': 0}
    for c in complaints:
        if c['status'] in stats:
            stats[c['status']] += 1

    return render_template('student_dashboard.html',
                           complaints=complaints,
                           stats=stats,
                           departments=DEPARTMENTS)


@app.route('/submit', methods=['GET', 'POST'])
def submit_complaint():
    if 'user_id' not in session or session['user_role'] != 'student':
        return redirect(url_for('login'))

    if request.method == 'POST':
        title       = request.form['title'].strip()
        description = request.form['description'].strip()
        category    = request.form['category'].strip()

        uploaded_file = request.files.get('attachment')
        attachment_name = save_file(uploaded_file)

        if uploaded_file and uploaded_file.filename != '' and attachment_name is None:
            flash('Invalid file. Only JPG, PNG, PDF allowed (max 5 MB). Complaint not submitted.', 'error')
            return render_template('submit_complaint.html', departments=DEPARTMENTS)

        result = classify(title, description, category)

        conn = get_db()
        conn.execute(
            '''INSERT INTO complaints
               (title,description,category,ai_category,ai_confidence,
                ai_source,routed_to,status,attachment,user_id,submitted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (title, description, category,
             result['category'],
             result['confidence'],
             result['source'],
             result['routed_to'],
             'Pending',
             attachment_name,
             session['user_id'],
             datetime.now().strftime('%Y-%m-%d %H:%M'))
        )
        conn.commit()
        conn.close()

        if result['mismatch_msg']:
            flash(result['mismatch_msg'], 'warning')
        else:
            flash('Complaint submitted and routed successfully!', 'success')

        return redirect(url_for('student_dashboard'))

    return render_template('submit_complaint.html', departments=DEPARTMENTS)


# ─────────────────────────────────────────────
# ADMIN ROUTES
# ─────────────────────────────────────────────

@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or session['user_role'] not in ('admin', 'superadmin'):
        return redirect(url_for('login'))

    check_overdue_complaints()

    is_super  = (session['user_role'] == 'superadmin')
    user_dept = session.get('user_department')

    filter_dept   = request.args.get('category', '')
    filter_status = request.args.get('status', '')

    conn = get_db()

    if is_super:
        # Direct complaints
        base_q = '''SELECT c.*, u.name as student_name, u.email as student_email,
                           NULL as cc_dept_label
                    FROM complaints c JOIN users u ON c.user_id=u.id WHERE 1=1'''
        base_p = []
        if filter_dept:
            base_q += ' AND c.routed_to=?'
            base_p.append(filter_dept)
        if filter_status:
            base_q += ' AND c.status=?'
            base_p.append(filter_status)

        # CC'd complaints
        cc_q = '''SELECT c.*, u.name as student_name, u.email as student_email,
                         cc.cc_dept as cc_dept_label
                  FROM complaints c JOIN users u ON c.user_id=u.id
                  JOIN complaint_cc cc ON cc.complaint_id=c.id WHERE 1=1'''
        cc_p = []
        if filter_dept:
            cc_q += ' AND cc.cc_dept=?'
            cc_p.append(filter_dept)
        if filter_status:
            cc_q += ' AND c.status=?'
            cc_p.append(filter_status)

    else:
        base_q = '''SELECT c.*, u.name as student_name, u.email as student_email,
                           NULL as cc_dept_label
                    FROM complaints c JOIN users u ON c.user_id=u.id
                    WHERE c.routed_to=?'''
        base_p = [user_dept]
        if filter_status:
            base_q += ' AND c.status=?'
            base_p.append(filter_status)

        cc_q = '''SELECT c.*, u.name as student_name, u.email as student_email,
                         cc.cc_dept as cc_dept_label
                  FROM complaints c JOIN users u ON c.user_id=u.id
                  JOIN complaint_cc cc ON cc.complaint_id=c.id
                  WHERE cc.cc_dept=?'''
        cc_p = [user_dept]
        if filter_status:
            cc_q += ' AND c.status=?'
            cc_p.append(filter_status)

    # Fetch both separately and merge in Python — avoids SQLite UNION syntax issues
    direct = conn.execute(base_q + ' ORDER BY c.submitted_at DESC', base_p).fetchall()
    ccd    = conn.execute(cc_q   + ' ORDER BY c.submitted_at DESC', cc_p).fetchall()
    complaints = list(direct) + list(ccd)

    # Build CC map
    cc_map = {}
    for row in complaints:
        cid = row['id']
        if cid not in cc_map:
            ccs = conn.execute(
                'SELECT cc_dept FROM complaint_cc WHERE complaint_id=?', (cid,)
            ).fetchall()
            cc_map[cid] = [r['cc_dept'] for r in ccs]

    conn.close()

    stats = {'Pending': 0, 'In Progress': 0, 'Resolved': 0, 'Total': len(complaints)}
    for c in complaints:
        if c['status'] in stats:
            stats[c['status']] += 1

    return render_template('admin_dashboard.html',
                           complaints=complaints,
                           cc_map=cc_map,
                           stats=stats,
                           departments=DEPARTMENTS,
                           is_super=is_super,
                           user_dept=user_dept,
                           selected_category=filter_dept,
                           selected_status=filter_status,
                           today=date.today().isoformat())

@app.route('/admin/update/<int:cid>', methods=['POST'])
def update_status(cid):
    if 'user_id' not in session or session['user_role'] not in ('admin', 'superadmin'):
        return redirect(url_for('login'))

    new_status   = request.form['status']
    admin_remark = request.form.get('admin_remark', '').strip()
    resolve_by   = request.form.get('resolve_by', '').strip()

    conn = get_db()

    if session['user_role'] == 'admin':
        row = conn.execute('SELECT routed_to FROM complaints WHERE id=?', (cid,)).fetchone()
        if not row:
            flash('Complaint not found.', 'error')
            conn.close()
            return redirect(url_for('admin_dashboard'))

        # Allow if primary dept OR if CC'd
        is_primary = (row['routed_to'] == session['user_department'])
        is_ccd     = conn.execute(
            'SELECT id FROM complaint_cc WHERE complaint_id=? AND cc_dept=?',
            (cid, session['user_department'])
        ).fetchone()

        if not is_primary and not is_ccd:
            flash('Unauthorized.', 'error')
            conn.close()
            return redirect(url_for('admin_dashboard'))

    updates = ['status = ?']
    values  = [new_status]

    if admin_remark:
        updates.append('admin_remark = ?')
        values.append(admin_remark)

    if resolve_by:
        updates.append('resolve_by = ?')
        values.append(resolve_by)

    if new_status == 'Resolved':
        updates.append('is_overdue = 0')

    values.append(cid)
    conn.execute(f'UPDATE complaints SET {", ".join(updates)} WHERE id=?', values)
    conn.commit()
    conn.close()
    flash(f'Complaint #{cid} updated to "{new_status}".', 'success')
    return redirect(url_for('admin_dashboard'))

# ─────────────────────────────────────────────
# FILE SERVING
# ─────────────────────────────────────────────

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session['user_role'] in ('admin', 'superadmin'):
        return send_from_directory(UPLOAD_FOLDER, filename)

    conn = get_db()
    row = conn.execute(
        'SELECT user_id FROM complaints WHERE attachment=?', (filename,)
    ).fetchone()
    conn.close()

    if row and row['user_id'] == session['user_id']:
        return send_from_directory(UPLOAD_FOLDER, filename)

    flash('Access denied.', 'error')
    return redirect(url_for('student_dashboard'))


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print("\n✅ Database initialized (passwords are now hashed).")
    print("\n📋 Login Accounts:")
    print("   Super Admin  →  admin@college.edu / admin123")
    for key, d in DEPARTMENTS.items():
        if key != 'General':
            print(f"   {d['label']:<22} →  {d['email']}")
    print("\n🚀 Starting server at http://127.0.0.1:5000\n")
    app.run(debug=True)