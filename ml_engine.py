"""
AegisRisk ML engine.

* Trains Gradient Boosting (XGBoost if installed), Random Forest, Logistic Regression
  and an Isolation Forest on a synthetic, *overlapping* dataset (so metrics are realistic,
  not a perfect 100%).
* Every metric shown in the UI is computed here from the held-out test set.
* Explanations are exact Shapley values (7 features -> 128 coalitions) measured against a
  "typical legitimate transaction" baseline, so they always sum to the model's score shift.
* PSI drift is computed against live transactions stored in the database.
* Retraining folds in analyst feedback labels.
"""
import itertools
import math
import re
import threading
from datetime import datetime

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, IsolationForest, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, auc, confusion_matrix, f1_score,
                             precision_recall_curve, precision_score, recall_score,
                             roc_auc_score)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

try:  # optional: pip install xgboost
    from xgboost import XGBClassifier
except Exception:  # pragma: no cover
    XGBClassifier = None

FEATURES = ["Amount vs. normal spend", "Distance from usual city (km)", "Device risk",
            "Night-time (12-5 AM)", "Transactions in last 2 min", "Merchant risk"]
FRIENDLY = ["Unusual amount", "Location jump", "Device", "Time of day", "Rapid activity",
            "Merchant"]

CITIES = {"Chennai": (13.0827, 80.2707), "Hyderabad": (17.3850, 78.4867),
          "Mumbai": (19.0760, 72.8777), "Delhi": (28.6139, 77.2090),
          "Bangalore": (12.9716, 77.5946), "Kolkata": (22.5726, 88.3639),
          "Pune": (18.5204, 73.8567), "Jaipur": (26.9124, 75.7873)}

MERCHANT_RISK = {"Crypto Onramp": 0.9, "Gift Cards": 0.8, "Wire Transfer": 0.7,
                 "Online Electronics": 0.5, "Luxury Boutique": 0.5, "Travel": 0.3,
                 "Food Delivery": 0.1, "Fuel": 0.1, "Groceries": 0.05, "Utilities": 0.05}
MERCHANTS = list(MERCHANT_RISK)


def distance_km(a, b):
    if a == b or a not in CITIES or b not in CITIES:
        return 0.0
    (la1, lo1), (la2, lo2) = CITIES[a], CITIES[b]
    p1, p2 = math.radians(la1), math.radians(la2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def parse_hour(t):
    m = re.match(r"\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])?", str(t or ""))
    if not m:
        return datetime.now().hour
    h = int(m.group(1)) % 24
    if m.group(3):
        h = h % 12 + (12 if m.group(3).lower() == "pm" else 0)
    return h


def device_risk(device, usual):
    d = (device or "").lower()
    if any(k in d for k in ("unknown", "new", "emulator", "rooted", "vpn")):
        return 0.9
    if usual and d == usual.lower():
        return 0.1
    return 0.4 if "browser" in d else 0.1


def featurize(txn, profile):
    """Returns (vector, human-readable details)."""
    amount = float(txn.get("amount") or 0)
    normal_max = float(profile.get("normal_max") or 5000)
    home = txn.get("prev_location") or profile.get("home_city") or txn.get("location")
    dist = distance_km(txn.get("location"), home)
    hour = parse_hour(txn.get("time"))
    night = 1.0 if hour < 5 else 0.0
    dev = device_risk(txn.get("device"), profile.get("usual_device"))
    vel = float(txn.get("recent_count") or 1)
    merch = MERCHANT_RISK.get(txn.get("merchant"), 0.2)
    ratio = min(1.5, max(0.0, math.log(max(amount, 1) / normal_max) / math.log(20)))
    vec = [ratio, dist, dev, night, vel, merch]
    return vec, {"distance_km": round(dist), "hour": hour, "amount": amount, "velocity": int(vel),
                 "device_risk": dev, "merchant_risk": merch, "home": home}


def _gen(n, seed, fraud_rate=0.03):
    rng = np.random.default_rng(seed)
    nf = max(1, int(n * fraud_rate)); ns = n - nf
    cust_max = rng.lognormal(math.log(5000), 0.5, n)

    def block(m, fraud):
        if not fraud:
            amt = rng.lognormal(math.log(1800), 1.0, m)
            dist = np.where(rng.random(m) < 0.06, rng.uniform(300, 1500, m), rng.exponential(18, m))
            dev = rng.choice([0.1, 0.4, 0.9], m, p=[.82, .08, .10])
            night = (rng.random(m) < 0.08).astype(float)
            vel = np.clip(rng.poisson(0.7, m) + 1, 1, 6).astype(float)
            mer = rng.choice([.05, .1, .2, .5, .9], m, p=[.35, .25, .2, .17, .03])
        else:
            amt = rng.lognormal(math.log(40000), 1.1, m)
            dist = np.where(rng.random(m) < 0.55, np.clip(rng.normal(900, 400, m), 50, 2000), rng.exponential(30, m))
            dev = rng.choice([0.1, 0.4, 0.9], m, p=[.2, .12, .68])
            night = (rng.random(m) < 0.45).astype(float)
            vel = np.clip(rng.poisson(2.5, m) + 1, 1, 8).astype(float)
            mer = rng.choice([.05, .1, .2, .5, .9], m, p=[.05, .1, .15, .4, .3])
        return amt, dist, dev, night, vel, mer

    rows = []
    for fraud, m, off in ((0, ns, 0), (1, nf, ns)):
        amt, dist, dev, night, vel, mer = block(m, fraud)
        cm = cust_max[off:off + m]
        ratio = np.clip(np.log(np.maximum(amt, 1) / cm) / math.log(20), 0, 1.5)
        rows.append(np.column_stack([ratio, dist, dev, night, vel, mer]))
    X = np.vstack(rows)
    y = np.concatenate([np.zeros(ns), np.ones(nf)])
    return X, y


def psi(base, recent, bins=10):
    base, recent = np.asarray(base, float), np.asarray(recent, float)
    if len(recent) < 20 or len(base) < 20:
        return 0.0
    edges = np.unique(np.quantile(base, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    b = np.clip(np.histogram(base, edges)[0] / len(base), 1e-4, None)
    r = np.clip(np.histogram(recent, edges)[0] / len(recent), 1e-4, None)
    return float(np.sum((r - b) * np.log(r / b)))


class FraudEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self.version = 0
        self.history = []
        self.train()

    # ------------------------------------------------------------------ training
    def _primary(self):
        if XGBClassifier is not None:
            return XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.1,
                                 eval_metric="logloss", n_jobs=2, random_state=42), "XGBoost"
        return GradientBoostingClassifier(n_estimators=150, max_depth=3, random_state=42), "Gradient Boosting"

    @staticmethod
    def _evaluate(model, X, y, proba=None):
        probs = model.predict_proba(X)[:, 1] if proba is None else proba
        preds = (probs >= 0.5).astype(int)
        p, r, _ = precision_recall_curve(y, probs)
        return {"accuracy": round(accuracy_score(y, preds) * 100, 1),
                "precision": round(precision_score(y, preds, zero_division=0) * 100, 1),
                "recall": round(recall_score(y, preds) * 100, 1),
                "f1": round(f1_score(y, preds) * 100, 1),
                "roc_auc": round(roc_auc_score(y, probs) * 100, 1),
                "pr_auc": round(auc(r, p) * 100, 1)}

    def train(self, extra=None):
        with self.lock:
            X, y = _gen(15000, seed=42 + self.version)
            Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
            if extra is not None and len(extra[0]):
                ex, ey = np.asarray(extra[0], float), np.asarray(extra[1], float)
                Xtr = np.vstack([Xtr] + [ex] * 10)
                ytr = np.concatenate([ytr] + [ey] * 10)
            primary, name = self._primary()
            primary.fit(Xtr, ytr, sample_weight=1 + 4 * ytr)
            rf = RandomForestClassifier(n_estimators=120, max_depth=10, n_jobs=2, random_state=42)
            rf.fit(Xtr, ytr, sample_weight=1 + 4 * ytr)
            lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, class_weight="balanced"))
            lr.fit(Xtr, ytr)
            iso = IsolationForest(n_estimators=150, contamination=0.03, random_state=42).fit(Xtr)

            iso_score = -iso.score_samples(Xte)
            iso_pred = (iso.predict(Xte) == -1).astype(int)
            ip, ir, _ = precision_recall_curve(yte, iso_score)
            iso_m = {"accuracy": round(accuracy_score(yte, iso_pred) * 100, 1),
                     "precision": round(precision_score(yte, iso_pred, zero_division=0) * 100, 1),
                     "recall": round(recall_score(yte, iso_pred) * 100, 1),
                     "f1": round(f1_score(yte, iso_pred) * 100, 1),
                     "roc_auc": round(roc_auc_score(yte, iso_score) * 100, 1),
                     "pr_auc": round(auc(ir, ip) * 100, 1)}

            self.model, self.model_name = primary, name
            self.rf, self.lr, self.iso = rf, lr, iso
            self.X_train = Xtr
            self.reference = np.median(Xtr[ytr == 0], axis=0)
            self.iso_range = (float(np.percentile(-iso.score_samples(Xtr), 5)),
                              float(np.percentile(-iso.score_samples(Xtr), 99.5)))
            self.version += 1
            self.metrics = self._evaluate(primary, Xte, yte)
            tn, fp, fn, tp = confusion_matrix(yte, primary.predict(Xte)).ravel()
            self.confusion = {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}
            self.benchmarks = [
                {"model": "Logistic Regression", "role": "Baseline", **self._evaluate(lr, Xte, yte)},
                {"model": "Random Forest", "role": "Challenger", **self._evaluate(rf, Xte, yte)},
                {"model": name, "role": "Active in production", **self.metrics},
                {"model": "Isolation Forest", "role": "Unsupervised anomaly score", **iso_m}]
            imp = getattr(primary, "feature_importances_", np.zeros(len(FEATURES)))
            self.importance = sorted(({"feature": FEATURES[i], "importance": round(float(imp[i]), 3)}
                                      for i in range(len(FEATURES))), key=lambda d: -d["importance"])
            self.trained_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            self.n_train = int(len(Xtr))
            self.model_version = f"{name.replace(' ', '')}-v{self.version}"
            self.history.append({"version": self.model_version, "trained_at": self.trained_at,
                                 "samples": self.n_train, "pr_auc": self.metrics["pr_auc"],
                                 "recall": self.metrics["recall"], "feedback_rows": 0 if extra is None else len(extra[0])})

    # ------------------------------------------------------------------ inference
    def _proba(self, rows):
        return self.model.predict_proba(np.atleast_2d(rows))[:, 1]

    def shapley(self, x):
        """Exact Shapley values (in probability points) vs. the legit-baseline reference."""
        n = len(x); x = np.asarray(x, float); ref = self.reference
        masks = list(itertools.product([0, 1], repeat=n))
        rows = np.array([[x[i] if m[i] else ref[i] for i in range(n)] for m in masks])
        f = dict(zip(masks, self._proba(rows)))
        fact = math.factorial
        phi = np.zeros(n)
        for i in range(n):
            for m in masks:
                if m[i]:
                    continue
                k = sum(m)
                wgt = fact(k) * fact(n - k - 1) / fact(n)
                m2 = m[:i] + (1,) + m[i + 1:]
                phi[i] += wgt * (f[m2] - f[m])
        return phi * 100, float(f[tuple([0] * n)]) * 100

    def analyze(self, txn, profile):
        with self.lock:
            vec, d = featurize(txn, profile)
            prob = float(self._proba(vec)[0])
            score = round(max(0.5, min(99.5, prob * 100)), 1)
            lo, hi = self.iso_range
            raw = float(-self.iso.score_samples([vec])[0])
            anomaly = round(max(0.0, min(1.0, (raw - lo) / (hi - lo + 1e-9))), 3)
            phi, base = self.shapley(vec)

        explain_text = [
            f"{txn.get('amount', 0):,.0f} vs. usual max {profile.get('normal_max', 5000):,.0f}",
            f"{txn.get('location')} vs. usual {d['home']} (~{d['distance_km']} km)",
            "Unrecognised device" if d["device_risk"] > 0.5 else "Recognised device",
            f"Placed at hour {d['hour']:02d}:00",
            f"{d['velocity']} transaction(s) in last 2 min",
            f"{txn.get('merchant', 'Merchant')}"]
        factors = [{"factor": FRIENDLY[i], "detail": explain_text[i], "impact": round(float(phi[i]), 1),
                    "direction": "up" if phi[i] > 0 else "down"}
                   for i in range(len(phi)) if abs(phi[i]) >= 0.4]
        factors.sort(key=lambda f: -abs(f["impact"]))

        rules = []
        if d["device_risk"] > 0.5 and d["amount"] >= 25000:
            rules.append("New device + high-value payment")
        if d["distance_km"] >= 800:
            rules.append(f"Location jump of ~{d['distance_km']} km")
        if vec[3] and d["velocity"] >= 3:
            rules.append("Night-time burst of payments")
        if d["velocity"] >= 4:
            rules.append("Velocity limit exceeded (4+ in 2 min)")
        if d["merchant_risk"] >= 0.7 and d["amount"] >= 10000:
            rules.append("High-risk merchant category")

        if score >= 80:
            status, action = "HIGH RISK", "DECLINED – customer verification required"
        elif score >= 50 or len(rules) >= 2:
            status, action = "REVIEW", "HELD for manual review"
        else:
            status, action = "SAFE", "APPROVED"
        return {"risk_score": score, "status": status, "action": action, "anomaly_score": anomaly,
                "shap_factors": factors, "rules": rules, "features": [float(v) for v in vec],
                "model_version": self.model_version, "baseline_score": round(base, 1)}

    # ------------------------------------------------------------------ monitoring
    def drift(self, recent_vectors):
        R = np.asarray(recent_vectors, float)
        per = []
        for i, name in enumerate(FEATURES):
            v = psi(self.X_train[:, i], R[:, i]) if len(R) else 0.0
            per.append({"feature": name, "psi": round(v, 3)})
        worst = max([p["psi"] for p in per] or [0])
        health = "GOOD" if worst < 0.1 else ("WATCH" if worst < 0.25 else "RETRAIN")
        return {"features": per, "max_psi": worst, "health": health, "n_recent": int(len(R))}


engine = FraudEngine()
