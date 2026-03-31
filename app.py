from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'grievance_secret_key_2024'

# ─────────────────────────────────────────────
# DEPARTMENT CONFIGURATION
# Central place to manage all departments.
# To add a new department, just add it here.
# ─────────────────────────────────────────────

DEPARTMENTS = {
    'Hostel':    {'label': 'Hostel / Warden',    'icon': '🏠', 'email': 'warden@college.edu',    'password': 'warden123'},
    'IT':        {'label': 'IT Department',       'icon': '💻', 'email': 'it@college.edu',         'password': 'it123'},
    'Academic':  {'label': 'Academic / Exam Cell','icon': '📚', 'email': 'academic@college.edu',   'password': 'academic123'},
    'Library':   {'label': 'Library',             'icon': '📖', 'email': 'library@college.edu',    'password': 'library123'},
    'Transport': {'label': 'Transport',           'icon': '🚌', 'email': 'transport@college.edu',  'password': 'transport123'},
    'Finance':   {'label': 'Finance / Fees',      'icon': '💰', 'email': 'finance@college.edu',    'password': 'finance123'},
    'General':   {'label': 'General Admin',       'icon': '📋', 'email': 'admin@college.edu',      'password': 'admin123'},
}

# ─────────────────────────────────────────────
# AI KEYWORD LISTS — one per department
# ─────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    'Hostel': [
        'hostel', 'room', 'roommate', 'mess', 'food', 'canteen', 'water',
        'electricity', 'cleaning', 'warden', 'bed', 'mattress', 'bathroom',
        'toilet', 'laundry', 'noise', 'curfew', 'accommodation', 'block',
        'dormitory', 'dorm', 'inmate', 'lock', 'gate', 'visitor', 'pest',
        'cockroach', 'rat', 'dirty', 'drain', 'dustbin', 'geyser', 'fan',
    ],
    'IT': [
        'internet', 'wifi', 'wi-fi', 'computer', 'laptop', 'lab', 'software',
        'hardware', 'network', 'server', 'login', 'password', 'system',
        'printer', 'email', 'website', 'portal', 'slow', 'connection',
        'database', 'it', 'mouse', 'keyboard', 'monitor', 'projector',
        'cable', 'usb', 'antivirus', 'hack', 'virus', 'download', 'upload',
    ],
    'Academic': [
        'exam', 'marks', 'grade', 'attendance', 'teacher', 'professor',
        'lecture', 'class', 'course', 'syllabus', 'timetable', 'result',
        'assignment', 'project', 'faculty', 'study', 'semester', 'cgpa',
        'backlog', 'fail', 'revaluation', 'hall ticket', 'practical',
        'lab report', 'viva', 'internal', 'external', 'department',
    ],
    'Library': [
        'library', 'book', 'librarian', 'catalog', 'borrow', 'return',
        'fine', 'overdue', 'reading room', 'journal', 'magazine', 'e-book',
        'digital library', 'reservation', 'card', 'membership', 'noise',
        'seat', 'chair', 'ac', 'air condition', 'photocopy', 'xerox',
    ],
    'Transport': [
        'bus', 'transport', 'driver', 'route', 'vehicle', 'van', 'cab',
        'pick up', 'drop', 'schedule', 'timing', 'late', 'delay', 'stop',
        'conductor', 'pass', 'bus pass', 'travel', 'commute', 'road',
        'breakdown', 'accident', 'fare', 'ticket',
    ],
    'Finance': [
        'fee', 'fees', 'fine', 'payment', 'receipt', 'scholarship', 'refund',
        'challan', 'bank', 'account', 'money', 'dues', 'pending payment',
        'finance', 'scholarship', 'stipend', 'hostel fee', 'tuition',
        'online payment', 'transaction', 'demand note', 'late fee',
    ],
}


# ─────────────────────────────────────────────
# AI CATEGORY VERIFICATION
# ─────────────────────────────────────────────

def ai_verify_category(title, description, user_selected_category):
    """
    Keyword-based NLP to verify category.
    Scores each department by counting keyword matches.
    Returns the best-matching department key (e.g. 'Hostel', 'IT').
    If nothing matches, returns user's selection.
    """
    text = (title + ' ' + description).lower()
    scores = {dept: 0 for dept in CATEGORY_KEYWORDS}

    for dept, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                scores[dept] += 1

    best = max(scores, key=scores.get)

    # If no keywords matched at all, trust the student
    if scores[best] == 0:
        return user_selected_category if user_selected_category != 'Other' else 'General'

    return best


# ─────────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect('grievance.db')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables and seed default accounts."""
    conn = get_db()
    c = conn.cursor()

    # Users table — now includes a 'department' column
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

    # Complaints table
    c.execute('''
        CREATE TABLE IF NOT EXISTS complaints (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            title          TEXT NOT NULL,
            description    TEXT NOT NULL,
            category       TEXT NOT NULL,
            ai_category    TEXT NOT NULL,
            routed_to      TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'Pending',
            user_id        INTEGER NOT NULL,
            submitted_at   TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    # Seed super admin
    c.execute('''
        INSERT OR IGNORE INTO users (name, email, password, role, department)
        VALUES ('Super Admin', 'admin@college.edu', 'admin123', 'superadmin', NULL)
    ''')

    # Seed one department head account per department
    for dept_key, dept_info in DEPARTMENTS.items():
        if dept_key == 'General':
            continue  # Super admin already handles General
        c.execute('''
            INSERT OR IGNORE INTO users (name, email, password, role, department)
            VALUES (?, ?, ?, 'admin', ?)
        ''', (dept_info['label'] + ' Head', dept_info['email'], dept_info['password'], dept_key))

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# ROUTES — AUTHENTICATION
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
            'SELECT * FROM users WHERE email = ? AND password = ?',
            (email, password)
        ).fetchone()
        conn.close()

        if user:
            session['user_id']         = user['id']
            session['user_name']       = user['name']
            session['user_role']       = user['role']
            session['user_department'] = user['department']
            flash(f"Welcome, {user['name']}!", 'success')

            if user['role'] in ('admin', 'superadmin'):
                return redirect(url_for('admin_dashboard'))
            else:
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
                'INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)',
                (name, email, password, 'student')
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
# ROUTES — STUDENT
# ─────────────────────────────────────────────

@app.route('/dashboard')
def student_dashboard():
    if 'user_id' not in session or session['user_role'] != 'student':
        return redirect(url_for('login'))

    conn = get_db()
    complaints = conn.execute(
        'SELECT * FROM complaints WHERE user_id = ? ORDER BY submitted_at DESC',
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
        category    = request.form['category'].strip()   # what student chose

        # Determine where to route
        if category == 'Other':
            ai_category = 'General'
            routed_to   = 'General'
        else:
            ai_category = ai_verify_category(title, description, category)
            routed_to   = ai_category   # route by AI's decision

        conn = get_db()
        conn.execute(
            '''INSERT INTO complaints
               (title, description, category, ai_category, routed_to, status, user_id, submitted_at)
               VALUES (?, ?, ?, ?, ?, 'Pending', ?, ?)''',
            (title, description, category, ai_category, routed_to,
             session['user_id'], datetime.now().strftime('%Y-%m-%d %H:%M'))
        )
        conn.commit()
        conn.close()

        if category != 'Other' and category != ai_category:
            flash(
                f'Submitted! You selected "{category}" but AI routed it to '
                f'"{ai_category}" department. Admin will review if needed.',
                'warning'
            )
        else:
            flash('Complaint submitted and routed successfully!', 'success')

        return redirect(url_for('student_dashboard'))

    return render_template('submit_complaint.html', departments=DEPARTMENTS)


# ─────────────────────────────────────────────
# ROUTES — ADMIN / DEPARTMENT HEAD
# ─────────────────────────────────────────────

@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or session['user_role'] not in ('admin', 'superadmin'):
        return redirect(url_for('login'))

    is_super    = session['user_role'] == 'superadmin'
    user_dept   = session.get('user_department')

    # Filters from query string
    filter_dept   = request.args.get('category', '')
    filter_status = request.args.get('status', '')

    query  = '''SELECT c.*, u.name as student_name, u.email as student_email
                FROM complaints c
                JOIN users u ON c.user_id = u.id
                WHERE 1=1'''
    params = []

    if not is_super:
        # Department head only sees their own complaints
        query  += ' AND c.routed_to = ?'
        params.append(user_dept)
    else:
        # Super admin can filter by department
        if filter_dept:
            query  += ' AND c.routed_to = ?'
            params.append(filter_dept)

    if filter_status:
        query  += ' AND c.status = ?'
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


@app.route('/admin/update/<int:complaint_id>', methods=['POST'])
def update_status(complaint_id):
    if 'user_id' not in session or session['user_role'] not in ('admin', 'superadmin'):
        return redirect(url_for('login'))

    new_status = request.form['status']
    conn = get_db()

    # Department heads can only update complaints routed to them
    if session['user_role'] == 'admin':
        complaint = conn.execute(
            'SELECT routed_to FROM complaints WHERE id = ?', (complaint_id,)
        ).fetchone()
        if not complaint or complaint['routed_to'] != session['user_department']:
            flash('Unauthorized action.', 'error')
            conn.close()
            return redirect(url_for('admin_dashboard'))

    conn.execute('UPDATE complaints SET status = ? WHERE id = ?', (new_status, complaint_id))
    conn.commit()
    conn.close()

    flash(f'Complaint #{complaint_id} updated to "{new_status}".', 'success')
    return redirect(url_for('admin_dashboard'))


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print("\n✅ Database initialized with all department accounts.")
    print("\n📋 Department Login Accounts:")
    print("   Super Admin  →  admin@college.edu       / admin123")
    for key, d in DEPARTMENTS.items():
        if key != 'General':
            print(f"   {d['label']:<22} →  {d['email']:<30} / {d['password']}")
    print("\n🚀 Server starting at http://127.0.0.1:5000\n")
    app.run(debug=True)