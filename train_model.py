"""
train_model.py
──────────────
Run this ONCE to train the complaint classifier and save it.

Command:  python train_model.py

What it does:
1. Loads all labelled complaint samples from training_data.py
2. Splits into 80% train / 20% test
3. Builds a TF-IDF vectorizer (converts text → numbers)
4. Trains a Multinomial Naive Bayes classifier on those numbers
5. Evaluates accuracy and shows a classification report
6. Saves the trained model to  model/classifier.pkl
7. Saves the vectorizer to     model/vectorizer.pkl
   (Both files are needed together — vectorizer converts text,
    classifier makes predictions)
"""

import os
import pickle
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score
from training_data import TRAINING_DATA
import numpy as np

# ── 1. Prepare data ───────────────────────────────────────────
texts  = [text  for text, label in TRAINING_DATA]
labels = [label for text, label in TRAINING_DATA]

print(f"\n{'─'*55}")
print(f"  GrievanceIQ — Complaint Classifier Training")
print(f"{'─'*55}")
print(f"  Total samples : {len(texts)}")
from collections import Counter
for dept, cnt in sorted(Counter(labels).items()):
    print(f"    {dept:<12} : {cnt} samples")

# ── 2. Train / test split (80/20, stratified) ─────────────────
X_train, X_test, y_train, y_test = train_test_split(
    texts, labels,
    test_size=0.20,
    random_state=42,
    stratify=labels          # ensures all departments in both splits
)

# ── 3. Build pipeline ─────────────────────────────────────────
#
# TF-IDF (Term Frequency – Inverse Document Frequency):
#   - Converts raw text into a matrix of numbers
#   - Words that appear often in ONE document but rarely across
#     all documents get a high score (they are distinctive)
#   - Common words like "the", "is", "and" get low scores
#
# ngram_range=(1,2): considers single words AND pairs of words
#   e.g. "mess food" is treated as one feature, not just "mess" + "food"
#   This helps a lot for complaints like "bus pass" vs "library pass"
#
# MultinomialNB: Naive Bayes classifier
#   - Very fast, works extremely well for text classification
#   - Calculates probability: P(category | words in text)
#   - Returns the category with the highest probability
#   - Also gives confidence scores (probabilities) per category
#
pipeline = Pipeline([
    ('tfidf', TfidfVectorizer(
        ngram_range=(1, 2),      # unigrams + bigrams
        min_df=1,                # include rare words (small dataset)
        sublinear_tf=True,       # apply log(1+tf) scaling
        strip_accents='unicode',
        analyzer='word',
        lowercase=True
    )),
    ('clf', MultinomialNB(alpha=0.1))  # alpha=smoothing
])

# ── 4. Cross-validation (k=5 folds) ──────────────────────────
print(f"\n  Running 5-fold cross-validation...")
cv_scores = cross_val_score(pipeline, texts, labels, cv=5, scoring='accuracy')
print(f"  CV Accuracy: {cv_scores.mean()*100:.1f}% ± {cv_scores.std()*100:.1f}%")

# ── 5. Train on full training split ──────────────────────────
pipeline.fit(X_train, y_train)

# ── 6. Evaluate on held-out test set ─────────────────────────
y_pred = pipeline.predict(X_test)
accuracy = accuracy_score(y_test, y_pred)

print(f"\n  Test Set Accuracy: {accuracy*100:.1f}%")
print(f"\n  Classification Report:")
print(classification_report(y_test, y_pred, target_names=sorted(set(labels))))

print(f"\n  Confusion Matrix (rows=actual, cols=predicted):")
departments = sorted(set(labels))
cm = confusion_matrix(y_test, y_pred, labels=departments)
# Pretty-print the confusion matrix
header = f"{'':12}" + "".join(f"{d[:8]:>10}" for d in departments)
print(f"  {header}")
for i, dept in enumerate(departments):
    row = f"  {dept:<12}" + "".join(f"{cm[i][j]:>10}" for j in range(len(departments)))
    print(row)

# ── 7. Re-train on ALL data for the final saved model ─────────
#   (More data = better model. Test set was just to evaluate it.)
pipeline.fit(texts, labels)

# ── 8. Save model ─────────────────────────────────────────────
os.makedirs('model', exist_ok=True)
model_path = os.path.join('model', 'grievance_model.pkl')

with open(model_path, 'wb') as f:
    pickle.dump(pipeline, f)

print(f"\n  ✅ Model saved to: {model_path}")
print(f"  The model is a Pipeline that includes both the")
print(f"  TF-IDF vectorizer and the Naive Bayes classifier.")
print(f"\n  Run  python app.py  to start the application.\n")

# ── 9. Quick sanity test ──────────────────────────────────────
print(f"{'─'*55}")
print(f"  Sanity test — 6 sample predictions:")
print(f"{'─'*55}")

test_cases = [
    ("The wifi in the hostel is not working", "IT"),
    ("My exam marks are wrong and professor is not responding", "Academic"),
    ("The mess food has insects and warden is not listening", "Hostel"),
    ("Library book issued to me has torn pages and missing chapters", "Library"),
    ("College bus is always late and driver drives rashly", "Transport"),
    ("My scholarship has not been credited and fees are pending", "Finance"),
]

for text, expected in test_cases:
    predicted = pipeline.predict([text])[0]
    probs     = pipeline.predict_proba([text])[0]
    confidence = max(probs) * 100
    match = "✓" if predicted == expected else "✗"
    print(f"  {match} [{predicted:<10}] {confidence:5.1f}%  \"{text[:55]}\"")

print(f"{'─'*55}\n")