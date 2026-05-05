# AI-Based Grievance Redressal System
## Complete Beginner-Friendly Project Guide

---

## TABLE OF CONTENTS
1. Project Overview
2. Folder Structure
3. Setup Instructions
4. System Plan & Architecture
5. Step-by-Step Development Plan
6. Database Design
7. Code Explanation (File by File)
8. How Everything Connects
9. How to Run the Project
10. Testing the Project
11. Viva Q&A Prep

---

## 1. PROJECT OVERVIEW

**GrievanceIQ** is a web application where:
- **Students** can register, log in, and submit complaints
- **An AI module** checks if the complaint is in the correct category
- **Admins** can view all complaints and update their status

**Tech Stack:**
| Layer      | Technology          |
|------------|---------------------|
| Frontend   | HTML + CSS (Jinja2 templates) |
| Backend    | Python Flask        |
| Database   | SQLite              |
| AI Module  | Keyword-based NLP (Python) |

---

## 2. FOLDER STRUCTURE

After setup, your project folder should look like this:

```
grievance_system/
│
├── app.py                  ← Main backend (all routes + AI logic)
├── requirements.txt        ← List of Python packages needed
├── grievance.db            ← SQLite database (auto-created on first run)
│
└── templates/              ← All HTML files live here
    ├── base.html           ← Shared layout (navbar, styles)
    ├── login.html          ← Login page
    ├── signup.html         ← Signup page
    ├── student_dashboard.html  ← Student's complaint tracker
    ├── submit_complaint.html   ← Complaint submission form
    └── admin_dashboard.html    ← Admin management panel
```

**Important:** Flask requires HTML files to be inside a folder named `templates`.

---

## 3. SETUP INSTRUCTIONS (VS Code)

### Step 1: Install Python
- Download Python 3.10+ from https://python.org
- During install, check ✅ "Add Python to PATH"
- Verify: open terminal and type `python --version`

### Step 2: Create the Project Folder
```
1. Open VS Code
2. File → Open Folder → Create a new folder called "grievance_system"
3. Inside it, create another folder called "templates"
```

### Step 3: Copy All the Code Files
Place the files as shown in Section 2's folder structure.

### Step 4: Open Terminal in VS Code
```
Press: Ctrl + ` (backtick key, top-left of keyboard)
```

### Step 5: Install Flask
```bash
pip install flask
```
Or if you have multiple Python versions:
```bash
pip3 install flask
```

### Step 6: Run the Project
```bash
python app.py
```
You will see:
```
✅ Database initialized.
🚀 Starting server at http://127.0.0.1:5000
```

### Step 7: Open in Browser
Go to: **http://127.0.0.1:5000**

---

## 4. SYSTEM PLAN & ARCHITECTURE

```
[Student/Admin Browser]
        │
        │  HTTP Request (form submit, page load)
        ▼
[Flask Backend — app.py]
    ├── Authentication Module   → Handles login, signup, sessions
    ├── Complaint Module        → Handles form submission
    ├── AI Module               → Verifies category using keywords
    ├── Admin Module            → Manages complaint statuses
        │
        │  SQL queries
        ▼
[SQLite Database — grievance.db]
    ├── users table
    └── complaints table
```

### How Modules Connect:
1. User fills HTML form → browser sends data to Flask via HTTP POST
2. Flask route function receives data → processes it
3. If it's a complaint, the AI function is called first
4. Flask saves data to SQLite database
5. Flask renders a new HTML page with updated data

---

## 5. STEP-BY-STEP DEVELOPMENT PLAN

### Step 1: Authentication System
**Files:** login.html, signup.html, app.py (login/signup/logout routes)

- Student registers with name, email, password (stored in `users` table)
- On login, Flask checks email+password against database
- If correct, user info is saved in `session` (like a temporary cookie)
- Role-based redirect: admin goes to admin dashboard, student to student dashboard

### Step 2: Complaint Submission
**Files:** submit_complaint.html, app.py (submit_complaint route)

- Student fills title, description, and selects a category
- Flask receives form data via POST request
- AI function is called before saving

### Step 3: AI Category Verification
**Function:** `ai_verify_category()` in app.py

- Combines title + description into one string
- Checks against keyword lists for each category
- Returns the most likely category based on keyword matches
- If mismatch: admin is alerted with a warning badge

### Step 4: Admin Dashboard
**Files:** admin_dashboard.html, app.py (admin routes)

- Fetches all complaints joined with user info
- Shows stats (pending/in progress/resolved counts)
- Admin can filter by category or status
- Each row has a dropdown to change status

### Step 5: Status Tracking
**Column:** `status` in complaints table

- Values: `Pending` → `In Progress` → `Resolved`
- Admin updates via form submit
- Students can see updated status on their dashboard

---

## 6. DATABASE DESIGN

### users Table
| Column   | Type    | Description                  |
|----------|---------|------------------------------|
| id       | INTEGER | Auto-incremented primary key |
| name     | TEXT    | Full name of user            |
| email    | TEXT    | Unique email (login ID)      |
| password | TEXT    | Plain text password          |
| role     | TEXT    | 'student' or 'admin'         |

### complaints Table
| Column       | Type    | Description                        |
|--------------|---------|------------------------------------|
| id           | INTEGER | Auto-incremented primary key       |
| title        | TEXT    | Short complaint title              |
| description  | TEXT    | Detailed complaint text            |
| category     | TEXT    | Category chosen by student         |
| ai_category  | TEXT    | Category verified by AI            |
| status       | TEXT    | Pending / In Progress / Resolved   |
| user_id      | INTEGER | Foreign key → users.id             |
| submitted_at | TEXT    | Date and time of submission        |

### Default Admin Account
```
Email:    admin@college.edu
Password: admin123
Role:     admin
```
This is inserted automatically when you first run `app.py`.

---

## 7. CODE EXPLANATION (FILE BY FILE)

### app.py — The Brain of the System

#### Part A: Setup
```python
app = Flask(__name__)
app.secret_key = 'grievance_secret_key_2024'
```
- Creates the Flask app
- `secret_key` is needed to use sessions (user login state)

#### Part B: Database Functions
```python
def get_db():
    conn = sqlite3.connect('grievance.db')
    conn.row_factory = sqlite3.Row
    return conn
```
- Connects to SQLite file
- `row_factory = sqlite3.Row` lets us access results like `row['email']` instead of `row[1]`

```python
def init_db():
    # Creates tables + adds default admin
```
- Called once at startup
- `CREATE TABLE IF NOT EXISTS` means it won't fail if tables already exist
- `INSERT OR IGNORE` inserts admin only if not already there

#### Part C: AI Function
```python
CATEGORY_KEYWORDS = {
    'Hostel': ['hostel', 'room', 'food', 'mess', 'warden', ...],
    'IT': ['internet', 'wifi', 'computer', 'lab', ...],
    'Academic': ['exam', 'marks', 'teacher', 'attendance', ...]
}

def ai_verify_category(title, description, user_selected_category):
    text = (title + ' ' + description).lower()
    scores = {'Hostel': 0, 'IT': 0, 'Academic': 0}
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                scores[category] += 1
    best_category = max(scores, key=scores.get)
    if scores[best_category] == 0:
        return user_selected_category
    return best_category
```

**How it works:**
1. Merge title + description, convert to lowercase
2. Count how many keywords from each category appear in the text
3. Return the category with the highest score
4. If zero keywords matched, trust the user's selection

**Example:**
- Text: "WiFi is not working in the computer lab"
- IT keywords found: 'wifi', 'computer', 'lab' → score = 3
- Hostel keywords found: 0
- Academic keywords found: 0
- Result: IT ✓

#### Part D: Login Route
```python
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        # Query database
        # If found: save to session, redirect
        # If not: flash error
```
- `@app.route('/login')` means "when browser visits /login, run this function"
- `methods=['GET', 'POST']`: GET = page load, POST = form submission
- `session['user_id'] = user['id']` stores login state

#### Part E: Session Management
```python
session['user_id']   = user['id']
session['user_name'] = user['name']
session['user_role'] = user['role']
```
- Session is like a shopping cart — it persists between page visits
- On logout: `session.clear()` removes everything

### base.html — Shared Layout
- Contains navbar, flash messages, and shared CSS
- All other HTML files "extend" this file using:
  ```html
  {% extends "base.html" %}
  {% block content %}...your content...{% endblock %}
  ```
- Jinja2 template syntax `{{ variable }}` and `{% if %}` let Python send data to HTML

---

## 8. HOW EVERYTHING CONNECTS

### Flow 1: Student Login
```
1. Student visits http://127.0.0.1:5000/login
2. Browser sends GET request → Flask returns login.html
3. Student fills form → clicks Login
4. Browser sends POST request with {email, password}
5. Flask queries: SELECT * FROM users WHERE email=? AND password=?
6. If found: session saved → redirect to /dashboard
7. Flask queries complaints for this user → renders student_dashboard.html
```

### Flow 2: Submit a Complaint
```
1. Student visits /submit → Flask returns submit_complaint.html
2. Student fills title, description, selects "IT"
3. Form POSTs data to /submit
4. Flask calls: ai_verify_category("WiFi broken", "no internet in room", "IT")
5. AI returns: "IT" (matched keywords: wifi, internet)
6. Flask inserts into complaints table: category="IT", ai_category="IT"
7. Flash message: "Complaint submitted successfully!"
8. Redirect to /dashboard
```

### Flow 3: Admin Updates Status
```
1. Admin visits /admin → Flask JOINs complaints + users → renders admin_dashboard.html
2. Admin selects "In Progress" from dropdown next to complaint #3
3. Form POSTs to /admin/update/3 with status="In Progress"
4. Flask runs: UPDATE complaints SET status="In Progress" WHERE id=3
5. Redirect back to admin_dashboard with flash message
```

---

## 9. HOW TO RUN THE PROJECT

### First Time Setup
```bash
# 1. Open terminal in VS Code (Ctrl + `)
# 2. Navigate to your project folder
cd grievance_system

# 3. Install Flask (only once)
pip install flask

# 4. Run the app
python app.py
```

### Every Time After
```bash
python app.py
```
Then open your browser and go to: **http://127.0.0.1:5000**

### Stop the Server
Press `Ctrl + C` in the terminal.

---

## 10. TESTING THE PROJECT

### Test 1: Student Signup & Login
1. Go to http://127.0.0.1:5000/signup
2. Enter: Name=Test Student, Email=test@college.edu, Password=test123
3. You should see "Account created! Please log in."
4. Login with those credentials
5. ✅ You should land on the student dashboard

### Test 2: AI Category Verification
Submit these complaints and check what AI suggests:

| Title | Description | You Select | AI Should Suggest |
|-------|-------------|------------|-------------------|
| WiFi not working | Internet is very slow in lab | IT | IT ✓ |
| Bad food in mess | Hostel canteen food quality poor | Hostel | Hostel ✓ |
| Wrong marks given | Professor gave wrong attendance | Academic | Academic ✓ |
| WiFi broken | Hostel room internet issue | Academic | IT ⚠️ (mismatch test) |

### Test 3: Admin Login
1. Go to http://127.0.0.1:5000/login
2. Email: admin@college.edu | Password: admin123
3. ✅ Should land on admin dashboard
4. You should see complaints submitted by test students
5. Change a complaint status to "In Progress" → click Save
6. ✅ Badge should update

### Test 4: Routing & Session Protection
1. Log out
2. Try to visit http://127.0.0.1:5000/admin directly
3. ✅ Should redirect to login (session protection works)

---

## 11. VIVA Q&A PREP

**Q: What is Flask?**
A: Flask is a lightweight Python web framework that lets you build web applications. It handles URL routing, form data, and HTML template rendering.

**Q: What is a session in Flask?**
A: A session stores temporary data (like login info) on the server side between different page requests. We use `session['user_id']` to remember who is logged in.

**Q: How does the AI category verification work?**
A: It's a keyword-based NLP approach. We maintain a dictionary of words associated with each category (Hostel, IT, Academic). When a complaint is submitted, we scan the title and description for these keywords and count which category matches the most. This is called Rule-Based NLP or Bag-of-Words matching.

**Q: What is SQLite and why did you use it?**
A: SQLite is a serverless, file-based relational database. We used it because it requires no separate installation — it works directly with Python. The entire database is stored in one file (grievance.db).

**Q: What is a Foreign Key?**
A: A foreign key links two tables. In our complaints table, `user_id` is a foreign key that references `users.id`. This means every complaint is linked to the student who submitted it.

**Q: What is Jinja2?**
A: Jinja2 is Flask's built-in template engine. It lets you write Python-like logic inside HTML files using `{{ variable }}` and `{% if/for %}` syntax.

**Q: What is the difference between GET and POST?**
A: GET requests fetch/display a page. POST requests send form data to the server. Login and signup forms use POST because they send sensitive data.

**Q: What improvements could be made to the AI module?**
A: We could use actual Machine Learning models like Naive Bayes, TF-IDF vectorization, or even a pre-trained BERT model for more accurate classification. We could also train on a labelled dataset of past complaints.

**Q: How is complaint routing handled?**
A: The `ai_category` field determines which department a complaint belongs to. Admin can filter complaints by department (Hostel/IT/Academic) to route and respond accordingly.

---

*Project by: [Your Name] | AI-Based Grievance Redressal System*