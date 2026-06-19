# AI-Based Grievance Redressal System
## GrievanceIQ – Complete Project Guide

---

# Table of Contents

1. Project Overview
2. Objectives
3. Project Structure
4. Setup & Configuration
5. System Architecture
6. Security & Privacy Design
7. Core Features
8. Database Design
9. System Workflows
10. Technology Stack
11. AI/ML Module
12. Results & Performance
13. Application Execution
14. Future Enhancements
15. Conclusion

---

# 1. Project Overview

GrievanceIQ is an AI-assisted grievance redressal platform developed for educational institutions. The system enables students to securely submit complaints, track progress, participate in public issue reporting, and optionally report issues anonymously while preserving accountability.

The platform combines:

- Complaint management
- Machine learning-based complaint routing
- OTP-based email verification
- Role-based access control
- Anonymous complaint submission
- Public issue aggregation through upvoting

The goal is to reduce manual complaint handling effort while improving transparency, accountability, and response efficiency.

---

# 2. Objectives

- Digitize institutional grievance handling.
- Automatically route complaints to appropriate departments.
- Reduce manual sorting effort.
- Protect student privacy during sensitive reporting.
- Provide transparency through complaint tracking.
- Enable collective issue reporting using public feeds.

---

# 3. Project Structure

```text
Grievance/
│
├── app2.py
├── ai_classifier.py
├── train_model.py
├── training_data.py
├── requirements.txt
├── .env
├── .gitignore
│
├── model/
│   └── grievance_model.pkl
│
└── templates/
    ├── base.html
    ├── login.html
    ├── signup.html
    ├── verify_otp.html
    ├── student_dashboard.html
    ├── submit_complaint.html
    ├── public_feed.html
    ├── complaint_detail.html
    ├── admin_dashboard.html
    └── accountability_check.html
```

---

# 4. Setup & Configuration

## Python Version

```bash
python --version
```

Recommended: Python 3.11+

## Environment Variables

Create a `.env` file:

```env
FLASK_SECRET_KEY=your_secret_key
SECRET_PEPPER=your_secret_pepper
SMTP_EMAIL=your_email@gmail.com
SMTP_PASSWORD=your_google_app_password
```

## Install Dependencies

```bash
pip install flask python-dotenv scikit-learn numpy
```

---

# 5. System Architecture

```text
Student/Admin Browser
          │
          ▼
      Flask App
      (app2.py)
          │
 ┌────────┼────────┐
 │        │        │
 ▼        ▼        ▼
SMTP   Authentication   Complaint Engine
OTP      & Sessions
                    │
                    ▼
            AI Classifier
        (TF-IDF + Naive Bayes)
                    │
                    ▼
     Privacy-Preserving Identity Hashing
      SHA-256(enrollment + pepper)
                    │
                    ▼
             SQLite Database
```

---

# 6. Security & Privacy Design

## Password Security

Passwords are stored using Werkzeug password hashing rather than plain text storage.

## OTP Verification

Student registration requires email verification through a 6-digit OTP.

## Anonymous Complaint Mechanism

Anonymous complaints do not store the student's direct identity inside complaint records.

Instead:

```text
Enrollment Number
        +
SECRET_PEPPER
        ↓
SHA-256 Hash
        ↓
crypto_token
```

This token is stored instead of a user reference.

## Accountability Verification

Authorized administrators can verify complaint ownership through controlled accountability checks without exposing identities in the complaint table.

---

# 7. Core Features

## Student Registration

- OTP-based verification
- Enrollment validation
- Email uniqueness checks

## Role-Based Authentication

Supported roles:

- Student
- Department Admin
- Central Admin

## AI-Based Complaint Routing

Complaint text is analyzed and automatically assigned to the most suitable department.

## Anonymous Reporting

Students may submit complaints anonymously while maintaining accountability through cryptographic identity hashing.

## Complaint Withdrawal

Students can withdraw complaints submitted by them.

## Public Feed

Public complaints can be viewed by students.

## Upvoting

Students can upvote public complaints to indicate common issues.
---

# 8. Database Design

## Users Table

| Column | Purpose |
|----------|----------|
| id | Primary Key |
| name | User Name |
| email | Login Email |
| password | Password Hash |
| enrollment_no | Student Enrollment |
| academic_unit | Department |
| role | Access Role |

## Complaints Table

| Column | Purpose |
|----------|----------|
| id | Complaint ID |
| title | Complaint Title |
| description | Complaint Details |
| category | User Selected Category |
| ai_category | Predicted Category |
| ai_confidence | Prediction Confidence |
| routed_to | Final Department |
| status | Complaint Status |
| upvote_count | Public Support Count |
| is_anonymous | Anonymous Flag |
| is_public | Public Visibility |
| user_id | Named Complaint Owner |
| crypto_token | Anonymous Identity Token |
| submitted_at | Timestamp |
| is_overdue | Overdue Flag |

## Supporting Tables

- complaint_upvotes
- status_audit_log
- reroute_log
- notifications
- crypto_accountability_log

---

# 9. System Workflows

## Registration Workflow

1. Student fills registration form.
2. Enrollment format validated.
3. OTP generated.
4. OTP emailed.
5. Student enters OTP.
6. Account created.

## Complaint Workflow

1. Student submits complaint.
2. Rate limits checked.
3. AI classification executed.
4. Confidence evaluated.
5. Complaint stored.
6. Dashboard updated.

## Admin Workflow

1. Admin reviews complaint.
2. Status updated.
3. Audit log generated.
4. Notification generated.

---

# 10. Technology Stack

## Backend

- Python 3.11
- Flask

## Frontend

- HTML
- CSS
- Jinja2
- JavaScript
- Chart.js

## Database

- SQLite3

## Security

- Werkzeug Password Hashing
- SHA-256 Hashing
- Environment Variables

## Machine Learning

- Scikit-Learn
- TF-IDF Vectorizer
- Multinomial Naive Bayes

## Communication

- SMTP Email Services

---

# 11. AI/ML Module

## Dataset

Total labelled samples: 487

Departments:

- Academic
- Finance
- Hostel
- IT
- Library
- Transport

## Model Pipeline

### TF-IDF Vectorizer

Configuration:

```python
ngram_range=(1,2)
lowercase=True
sublinear_tf=True
```

Converts complaint text into numerical vectors.

### Multinomial Naive Bayes

Configuration:

```python
alpha=0.1
```

Predicts the most probable department.

## Cross Validation

5-fold cross validation is used to evaluate model stability.

## Confidence Threshold

Low-confidence predictions can defer to user-selected categories.

---

# 12. Results & Performance

## Model Metrics

| Metric | Value |
|----------|----------|
| Training Samples | 487 |
| Categories | 6 |
| Cross Validation Accuracy | 82.8% ± 4.4% |
| Test Accuracy | 86.7% |

## Department-wise F1 Scores

| Department | F1 Score |
|------------|----------|
| Academic | 0.83 |
| Finance | 0.84 |
| Hostel | 0.88 |
| IT | 0.86 |
| Library | 0.90 |
| Transport | 0.89 |

## Interpretation

The model demonstrates strong classification performance and is suitable for automated complaint routing within a campus grievance environment.

---

# 13. Application Execution

Run:

```bash
cd E:\Grievance
python app2.py
```

Open:

```text
http://127.0.0.1:5000
```

Stop Server:

```text
CTRL + C
```

---

# 14. Future Enhancements

- Mobile application support
- Cloud deployment
- PostgreSQL migration
- SMS notifications
- Multi-campus deployment
- Advanced NLP models (BERT)
- Resolution time prediction

---

# 15. Conclusion

GrievanceIQ combines complaint management, machine learning, privacy-preserving anonymous reporting, and role-based administration into a unified platform.

The system demonstrates practical implementation of Flask, SQLite, Scikit-Learn, authentication, email verification, analytics, and secure identity management to improve institutional grievance handling.

The project successfully meets its objective of creating a transparent, efficient, and intelligent grievance redressal ecosystem for educational institutions.
