"""
ai_classifier.py
────────────────
This module is imported by app.py.
It loads the trained model and exposes one function:

    classify(title, description, user_category)
    → returns { 'category', 'confidence', 'all_scores',
                'source', 'mismatch', 'mismatch_msg' }

It also keeps the keyword fallback so the app never crashes
even if the model file is not found.
"""

import os
import pickle

# ── KEYWORD FALLBACK (used only if model is not found) ────────
KEYWORD_FALLBACK = {
    'Hostel':    ['hostel','room','roommate','mess','food','canteen','water',
                  'warden','bed','mattress','bathroom','toilet','laundry',
                  'electricity','cleaning','geyser','cockroach','rat','drain'],
    'IT':        ['internet','wifi','wi-fi','computer','laptop','lab','software',
                  'hardware','network','server','login','password','portal',
                  'printer','email','website','slow','connection','system'],
    'Academic':  ['exam','marks','grade','attendance','teacher','professor',
                  'lecture','class','course','syllabus','timetable','result',
                  'assignment','faculty','semester','cgpa','backlog','viva'],
    'Library':   ['library','book','librarian','catalog','borrow','return',
                  'fine','reading room','journal','magazine','e-book','xerox'],
    'Transport': ['bus','transport','driver','route','vehicle','van','commute',
                  'pickup','drop','schedule','timing','conductor','bus pass'],
    'Finance':   ['fee','fees','fine','payment','receipt','scholarship','refund',
                  'challan','bank','dues','tuition','transaction','demand note'],
}

CONFIDENCE_THRESHOLD = 0.45   # below this → flag as uncertain even if correct dept

MODEL_PATH = os.path.join('model', 'grievance_model.pkl')

# ── Load model at import time ──────────────────────────────────
_pipeline = None

def _load_model():
    global _pipeline
    if _pipeline is not None:
        return True
    if os.path.exists(MODEL_PATH):
        try:
            with open(MODEL_PATH, 'rb') as f:
                _pipeline = pickle.load(f)
            print(f"  [AI] Model loaded from {MODEL_PATH}")
            return True
        except Exception as e:
            print(f"  [AI] Warning: could not load model — {e}")
    else:
        print(f"  [AI] Model not found at {MODEL_PATH}.")
        print(f"       Run  python train_model.py  to create it.")
    return False

_load_model()


# ── KEYWORD FALLBACK FUNCTION ──────────────────────────────────
def _keyword_classify(text):
    scores = {dept: 0 for dept in KEYWORD_FALLBACK}
    text_lower = text.lower()
    for dept, keywords in KEYWORD_FALLBACK.items():
        for kw in keywords:
            if kw in text_lower:
                scores[dept] += 1
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return 'General', 0.0, scores
    total = sum(scores.values()) or 1
    confidence = scores[best] / total
    return best, confidence, scores


# ── MAIN PUBLIC FUNCTION ───────────────────────────────────────
def classify(title, description, user_category):
    """
    Classify a complaint using the trained ML model.

    Parameters
    ----------
    title           : str  — complaint title
    description     : str  — complaint body text
    user_category   : str  — what the student selected in the form

    Returns
    -------
    dict with keys:
        category      — predicted department (str)
        confidence    — 0.0–1.0 float
        confidence_pct— formatted string e.g. "92.3%"
        all_scores    — {dept: probability} for all departments
        source        — 'ml_model' | 'keyword_fallback'
        mismatch      — True if AI disagrees with user selection
        mismatch_msg  — human-readable explanation (str)
        routed_to     — final routing decision (str)
    """
    combined_text = f"{title} {description}"

    if _pipeline is not None:
        # ── ML MODEL PATH ──────────────────────────────────────
        probs      = _pipeline.predict_proba([combined_text])[0]
        classes    = _pipeline.classes_
        all_scores = {cls: float(prob) for cls, prob in zip(classes, probs)}

        predicted   = classes[probs.argmax()]
        confidence  = float(probs.max())
        source      = 'ml_model'

    else:
        # ── KEYWORD FALLBACK ───────────────────────────────────
        predicted, confidence, raw_scores = _keyword_classify(combined_text)
        total = sum(raw_scores.values()) or 1
        all_scores = {d: v/total for d, v in raw_scores.items()}
        source = 'keyword_fallback'

    # ── Handle "Other" — always go to General ─────────────────
    if user_category == 'Other':
        return {
            'category':       'General',
            'confidence':     1.0,
            'confidence_pct': '—',
            'all_scores':     all_scores,
            'source':         source,
            'mismatch':       False,
            'mismatch_msg':   '',
            'routed_to':      'General',
        }

    # ── Determine mismatch & routing ──────────────────────────
    #
    # ROUTING LOGIC:
    #   • If AI confidence ≥ threshold AND AI ≠ user → route by AI
    #     (model is confident; user likely mis-categorised)
    #   • If AI confidence < threshold → route by user
    #     (model is unsure; trust student's judgement)
    #   • If AI == user → no mismatch, route by user
    #
    mismatch = (predicted != user_category)

    if not mismatch:
        routed_to    = user_category
        mismatch_msg = ''

    elif confidence >= CONFIDENCE_THRESHOLD:
        # AI is confident and disagrees — route by AI
        routed_to    = predicted
        mismatch_msg = (
            f"You selected \"{user_category}\" but our AI is "
            f"{confidence*100:.0f}% confident this belongs to "
            f"\"{predicted}\". It has been routed accordingly. "
            f"The department head can re-route if needed."
        )
    else:
        # AI is unsure — trust the student
        routed_to    = user_category
        mismatch_msg = (
            f"Our AI suggested \"{predicted}\" ({confidence*100:.0f}% confidence) "
            f"but this is below our confidence threshold, so your selection "
            f"\"{user_category}\" has been used for routing."
        )

    return {
        'category':       predicted,
        'confidence':     confidence,
        'confidence_pct': f"{confidence*100:.1f}%",
        'all_scores':     all_scores,
        'source':         source,
        'mismatch':       mismatch,
        'mismatch_msg':   mismatch_msg,
        'routed_to':      routed_to,
    }