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
from datetime import datetime
from ai_classifier import classify   # ← new ML-based classifier

app = Flask(__name__)
app.secret_key = 'grievance_secret_key_2024'

# ─────────────────────────────────────────────
# FILE UPLOAD CONFIGURATION
# ─────────────────────────────────────────────

UPLOAD_FOLDER   = 'uploads'                        # folder where files are saved
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'pdf'} # only these types allowed
MAX_FILE_MB     = 5                                 # reject files larger than 5 MB
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_MB * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)          # create folder if not there

def allowed_file(filename):
    """Returns True if the file extension is in the allowed list."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_file(file):
    """
    Saves an uploaded file safely and returns the stored filename.
    Uses uuid to make every filename unique — prevents overwrites.
    e.g.  screenshot.jpg  →  a3f1c29b-4d2e-screenshot.jpg
    """
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

    # complaints table now stores ai_confidence, ai_source, and attachment
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
            user_id        INTEGER NOT NULL,
            submitted_at   TEXT    NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    # Re-route log: tracks every re-routing action by admins
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

    # Super admin (hashed password)
    existing = c.execute("SELECT id FROM users WHERE email='admin@college.edu'").fetchone()
    if not existing:
        c.execute(
            'INSERT INTO users (name,email,password,role,department) VALUES (?,?,?,?,?)',
            ('Super Admin', 'admin@college.edu',
             generate_password_hash('admin123'), 'superadmin', None)
        )

    # Department heads (hashed passwords)
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

        # ── Handle file upload ─────────────────────────────────
        uploaded_file = request.files.get('attachment')  # 'attachment' matches form field name
        attachment_name = save_file(uploaded_file)        # returns filename or None

        if uploaded_file and uploaded_file.filename != '' and attachment_name is None:
            # File was provided but rejected (wrong type or too large)
            flash('Invalid file. Only JPG, PNG, PDF allowed (max 5 MB). Complaint not submitted.', 'error')
            return render_template('submit_complaint.html', departments=DEPARTMENTS)

        # ── Call ML classifier ─────────────────────────────────
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
             attachment_name,           # None if no file was uploaded
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

    is_super  = (session['user_role'] == 'superadmin')
    user_dept = session.get('user_department')

    filter_dept   = request.args.get('category', '')
    filter_status = request.args.get('status', '')

    query  = '''SELECT c.*, u.name as student_name, u.email as student_email
                FROM complaints c JOIN users u ON c.user_id=u.id WHERE 1=1'''
    params = []

    if not is_super:
        query += ' AND c.routed_to=?'
        params.append(user_dept)
    elif filter_dept:
        query += ' AND c.routed_to=?'
        params.append(filter_dept)

    if filter_status:
        query += ' AND c.status=?'
        params.append(filter_status)

    query += ' ORDER BY c.submitted_at DESC'

    conn = get_db()
    complaints = conn.execute(query, params).fetchall()
    conn.close()

    stats = {'Pending': 0, 'In Progress': 0, 'Resolved': 0, 'Total': len(complaints)}
    for c in complaints:
        if c['status'] in stats:
            stats[c['status']] += 1

    return render_template('admin_dashboard.html',
                           complaints=complaints,
                           stats=stats,
                           departments=DEPARTMENTS,
                           is_super=is_super,
                           user_dept=user_dept,
                           selected_category=filter_dept,
                           selected_status=filter_status)


@app.route('/admin/update/<int:cid>', methods=['POST'])
def update_status(cid):
    if 'user_id' not in session or session['user_role'] not in ('admin', 'superadmin'):
        return redirect(url_for('login'))

    new_status = request.form['status']
    conn = get_db()

    if session['user_role'] == 'admin':
        row = conn.execute('SELECT routed_to FROM complaints WHERE id=?', (cid,)).fetchone()
        if not row or row['routed_to'] != session['user_department']:
            flash('Unauthorized.', 'error')
            conn.close()
            return redirect(url_for('admin_dashboard'))

    conn.execute('UPDATE complaints SET status=? WHERE id=?', (new_status, cid))
    conn.commit()
    conn.close()
    flash(f'Complaint #{cid} updated to "{new_status}".', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/reroute/<int:cid>', methods=['POST'])
def reroute_complaint(cid):
    """
    Admin manually re-routes a complaint to a different department.
    Only superadmin or the currently-assigned department head can do this.
    """
    if 'user_id' not in session or session['user_role'] not in ('admin', 'superadmin'):
        return redirect(url_for('login'))

    new_dept = request.form['new_dept'].strip()
    note     = request.form.get('note', '').strip()

    if new_dept not in DEPARTMENTS:
        flash('Invalid department selected.', 'error')
        return redirect(url_for('admin_dashboard'))

    conn = get_db()
    row  = conn.execute('SELECT routed_to FROM complaints WHERE id=?', (cid,)).fetchone()

    if not row:
        flash('Complaint not found.', 'error')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    # Department head can only re-route their own complaints
    if session['user_role'] == 'admin' and row['routed_to'] != session['user_department']:
        flash('You can only re-route complaints assigned to your department.', 'error')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    old_dept = row['routed_to']

    conn.execute('UPDATE complaints SET routed_to=? WHERE id=?', (new_dept, cid))
    conn.execute(
        '''INSERT INTO reroute_log
           (complaint_id,from_dept,to_dept,rerouted_by,rerouted_at,note)
           VALUES (?,?,?,?,?,?)''',
        (cid, old_dept, new_dept, session['user_id'],
         datetime.now().strftime('%Y-%m-%d %H:%M'), note)
    )
    conn.commit()
    conn.close()

    from_label = DEPARTMENTS.get(old_dept, {}).get('label', old_dept)
    to_label   = DEPARTMENTS.get(new_dept, {}).get('label', new_dept)
    flash(f'Complaint #{cid} re-routed from {from_label} → {to_label}.', 'success')
    return redirect(url_for('admin_dashboard'))


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """
    Serves an uploaded file. Only logged-in admins and the
    student who submitted it can access attachments.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Admins can always view files
    if session['user_role'] in ('admin', 'superadmin'):
        return send_from_directory(UPLOAD_FOLDER, filename)

    # Students can only view their own attachments
    conn = get_db()
    row = conn.execute(
        'SELECT user_id FROM complaints WHERE attachment=?', (filename,)
    ).fetchone()
    conn.close()

    if row and row['user_id'] == session['user_id']:
        return send_from_directory(UPLOAD_FOLDER, filename)

    flash('Access denied.', 'error')
    return redirect(url_for('student_dashboard'))

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