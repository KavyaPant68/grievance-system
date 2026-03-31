from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'grievance_secret_key_2024'

# ─────────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────────

def get_db():
    """Connect to the SQLite database."""
    conn = sqlite3.connect('grievance.db')
    conn.row_factory = sqlite3.Row  # So we can access columns by name
    return conn

def init_db():
    """Create tables if they don't exist, and add a default admin."""
    conn = get_db()
    cursor = conn.cursor()

    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT NOT NULL,
            email    TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role     TEXT NOT NULL DEFAULT 'student'
        )
    ''')

    # Complaints table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS complaints (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT NOT NULL,
            description  TEXT NOT NULL,
            category     TEXT NOT NULL,
            ai_category  TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'Pending',
            user_id      INTEGER NOT NULL,
            submitted_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    # Add a default admin account (password: admin123)
    cursor.execute('''
        INSERT OR IGNORE INTO users (name, email, password, role)
        VALUES ('Admin', 'admin@college.edu', 'admin123', 'admin')
    ''')

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# AI CATEGORY VERIFICATION (Keyword-Based NLP)
# ─────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    'Hostel': [
        'hostel', 'room', 'roommate', 'mess', 'food', 'canteen', 'water',
        'electricity', 'cleaning', 'warden', 'bed', 'mattress', 'bathroom',
        'toilet', 'laundry', 'noise', 'curfew', 'accommodation'
    ],
    'IT': [
        'internet', 'wifi', 'computer', 'laptop', 'lab', 'software', 'hardware',
        'network', 'server', 'login', 'password', 'system', 'printer', 'email',
        'website', 'portal', 'slow', 'connection', 'database', 'it'
    ],
    'Academic': [
        'exam', 'marks', 'grade', 'attendance', 'teacher', 'professor', 'lecture',
        'class', 'course', 'syllabus', 'timetable', 'result', 'assignment',
        'project', 'faculty', 'study', 'library', 'book', 'notes', 'academic'
    ]
}

def ai_verify_category(title, description, user_selected_category):
    """
    Simple keyword-based NLP to verify the category.
    Checks title + description for keywords from each category.
    Returns the AI's suggested category.
    """
    text = (title + ' ' + description).lower()
    scores = {'Hostel': 0, 'IT': 0, 'Academic': 0}

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                scores[category] += 1

    # Find the category with the highest score
    best_category = max(scores, key=scores.get)

    # If no keywords matched at all, trust the user's selection
    if scores[best_category] == 0:
        return user_selected_category

    return best_category


# ─────────────────────────────────────────────
# ROUTES: AUTHENTICATION
# ─────────────────────────────────────────────

@app.route('/')
def home():
    """Redirect to login page."""
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
            # Save user info in session
            session['user_id']   = user['id']
            session['user_name'] = user['name']
            session['user_role'] = user['role']
            flash(f"Welcome back, {user['name']}!", 'success')

            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid email or password. Please try again.', 'error')

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
            flash('This email is already registered. Please log in.', 'error')
        finally:
            conn.close()

    return render_template('signup.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ─────────────────────────────────────────────
# ROUTES: STUDENT
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

    # Count by status
    stats = {'Pending': 0, 'In Progress': 0, 'Resolved': 0}
    for c in complaints:
        if c['status'] in stats:
            stats[c['status']] += 1

    return render_template('student_dashboard.html', complaints=complaints, stats=stats)


@app.route('/submit', methods=['GET', 'POST'])
def submit_complaint():
    if 'user_id' not in session or session['user_role'] != 'student':
        return redirect(url_for('login'))

    if request.method == 'POST':
        title       = request.form['title'].strip()
        description = request.form['description'].strip()
        category    = request.form['category'].strip()

        # AI verification
        ai_category = ai_verify_category(title, description, category)

        conn = get_db()
        conn.execute(
            '''INSERT INTO complaints
               (title, description, category, ai_category, status, user_id, submitted_at)
               VALUES (?, ?, ?, ?, 'Pending', ?, ?)''',
            (title, description, category, ai_category, session['user_id'],
             datetime.now().strftime('%Y-%m-%d %H:%M'))
        )
        conn.commit()
        conn.close()

        if category != ai_category:
            flash(
                f'Complaint submitted! Note: You selected "{category}", but our AI '
                f'suggests it belongs to "{ai_category}". Admin will review.',
                'warning'
            )
        else:
            flash('Complaint submitted successfully!', 'success')

        return redirect(url_for('student_dashboard'))

    return render_template('submit_complaint.html')


# ─────────────────────────────────────────────
# ROUTES: ADMIN
# ─────────────────────────────────────────────

@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or session['user_role'] != 'admin':
        return redirect(url_for('login'))

    conn = get_db()
    complaints = conn.execute(
        '''SELECT c.*, u.name as student_name, u.email as student_email
           FROM complaints c
           JOIN users u ON c.user_id = u.id
           ORDER BY c.submitted_at DESC'''
    ).fetchall()
    conn.close()

    stats = {'Pending': 0, 'In Progress': 0, 'Resolved': 0, 'Total': len(complaints)}
    for c in complaints:
        if c['status'] in stats:
            stats[c['status']] += 1

    return render_template('admin_dashboard.html', complaints=complaints, stats=stats)


@app.route('/admin/update/<int:complaint_id>', methods=['POST'])
def update_status(complaint_id):
    if 'user_id' not in session or session['user_role'] != 'admin':
        return redirect(url_for('login'))

    new_status = request.form['status']
    conn = get_db()
    conn.execute(
        'UPDATE complaints SET status = ? WHERE id = ?',
        (new_status, complaint_id)
    )
    conn.commit()
    conn.close()

    flash(f'Complaint #{complaint_id} status updated to "{new_status}".', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/filter')
def filter_complaints():
    if 'user_id' not in session or session['user_role'] != 'admin':
        return redirect(url_for('login'))

    category = request.args.get('category', '')
    status   = request.args.get('status', '')

    query  = '''SELECT c.*, u.name as student_name, u.email as student_email
                FROM complaints c
                JOIN users u ON c.user_id = u.id
                WHERE 1=1'''
    params = []

    if category:
        query  += ' AND c.ai_category = ?'
        params.append(category)
    if status:
        query  += ' AND c.status = ?'
        params.append(status)

    query += ' ORDER BY c.submitted_at DESC'

    conn = get_db()
    complaints = conn.execute(query, params).fetchall()
    conn.close()

    stats = {'Pending': 0, 'In Progress': 0, 'Resolved': 0, 'Total': len(complaints)}
    for c in complaints:
        if c['status'] in stats:
            stats[c['status']] += 1

    return render_template('admin_dashboard.html', complaints=complaints, stats=stats,
                           selected_category=category, selected_status=status)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print("✅ Database initialized.")
    print("🚀 Starting server at http://127.0.0.1:5000")
    app.run(debug=True)