# api/ml_intents.py — Minimal ML intent classifier (TF-IDF + LinearSVC)

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.pipeline import Pipeline
import numpy as np

# Labels we care about
LABELS = ["list", "describe", "keys", "partitions", "other"]

# Seed training phrases (expand over time)
SEED: List[Tuple[str, List[str]]] = [
    ("list", [
        "list tables", "show tables", "find tables for kyc", "what tables exist",
        "search tables containing party", "which tables are in schema",
        "tables with alert", "show me alert tables", "list all kyc tables",
    ]),
    ("describe", [
        "describe table stg_party_master", "columns of txn_alerts",
        "show schema of alert_history", "what are the columns in kyc_customer",
        "desc stg_transactions", "structure of table txn_alerts",
    ]),
    ("keys", [
        "keys of table txn_alerts", "primary key of party_master",
        "foreign keys on alert_history", "list constraints for stg_party_master",
        "unique keys of kyc_customer", "constraints on txn_alerts",
    ]),
    ("partitions", [
        "partition info of table alert_history", "how is txn_alerts partitioned",
        "show partitions for stg_transactions", "subpartitions of large_txn",
        "list partitions of alert_archive",
    ]),
    ("other", [
        "hello", "how are you", "what can you do", "help", "hi bot",
        "what is ofsaa", "explain aml alerts", "tell me a joke",
    ]),
]

@dataclass
class IntentResult:
    label: str
    confidence: float

_model: Pipeline | None = None

def _train_model() -> Pipeline:
    X, y = [], []
    for label, samples in SEED:
        X.extend(samples)
        y.extend([label] * len(samples))
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, lowercase=True)),
        ("clf", LinearSVC()),
    ])
    pipe.fit(X, y)
    return pipe

def predict_intent(text: str) -> IntentResult:
    """
    Predict one of LABELS using a light TF-IDF + LinearSVC model.
    Confidence is a pseudo-probability derived from the decision margins.
    """
    global _model
    if _model is None:
        _model = _train_model()

    dec = _model.decision_function([text])[0]  # shape: (n_classes,)
    # Normalize margins into a softmax-like score for readability
    exps = np.exp(dec - dec.max())
    probs = exps / exps.sum()
    idx = int(dec.argmax())
    label = _model.classes_[idx]
    conf = float(probs[idx])
    return IntentResult(label=label, confidence=conf)

