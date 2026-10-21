"""AegisRisk API + static frontend (Flask).  Run:  python app.py   |   gunicorn app:app"""
import csv
import io
import os
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, Response, g, jsonify, request, send_from_directory

from db import db, now, uid
from ml_engine import CITIES, MERCHANTS, engine, parse_hour

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"
IST = timezone(timedelta(hours=5, minutes=30))
STARTED = time.time()


# ============================================================ bootstrap / seed data
CUSTOMERS = [
    ("C10291", "Aarav Reddy", "customer@securebank.com", "Hyderabad", "Mobile Banking App", 1000, 5000, 85420, "4892"),
    ("C10344", "Meera Iyer", "meera@securebank.com", "Chennai", "iPhone 15 Pro", 2000, 9000, 142300, "1180"),
    ("C10418", "Rohan Gupta", "rohan@securebank.com", "Delhi", "Samsung S24", 1500, 7000, 64210, "7731"),
    ("C10502", "Ananya Das", "ananya@securebank.com", "Kolkata", "Mobile Banking App", 800, 3500, 28900, "2406"),
    ("C10587", "Kabir Shah", "kabir@securebank.com", "Mumbai", "iPhone 15 Pro", 3000, 15000, 310500, "9954"),
]
NORMAL_DEVICES = ["Mobile Banking App", "iPhone 15 Pro", "Samsung S24"]
BAD_DEVICES = ["Unknown Device", "Unknown Chrome Browser", "Android Emulator"]


def make_raw(cust, kind):
    cities = list(CITIES)
    away = random.choice([c for c in cities if c != cust["home_city"]])
    if kind == "fraud":
        return dict(amount=random.choice([48000, 62000, 85000, 94000, 120000]), location=away,
                    time=f"0{random.randint(1, 4)}:{random.randint(10, 59)} AM", device=random.choice(BAD_DEVICES),
                    recent_count=random.randint(3, 5), merchant=random.choice(["Crypto Onramp", "Gift Cards", "Online Electronics", "Wire Transfer"]))
    if kind == "suspicious":
        return dict(amount=random.choice([18000, 26000, 31000]), location=random.choice([away, cust["home_city"]]),
                    time=f"{random.randint(1, 11):02d}:{random.randint(10, 59)} PM", device=random.choice([cust["usual_device"], "Unknown Chrome Browser"]),
                    recent_count=random.randint(2, 3), merchant=random.choice(["Luxury Boutique", "Online Electronics", "Travel"]))
    return dict(amount=round(random.uniform(120, cust["normal_max"] * 0.9), -1), location=cust["home_city"],
                time=f"{random.randint(8, 11):02d}:{random.randint(0, 59):02d} AM", device=cust["usual_device"], recent_count=1,
                merchant=random.choice(["Food Delivery", "Groceries", "Fuel", "Utilities", "Travel"]))


def score(cust, raw, persist=True, created_at=None):
    raw = dict(raw)
    raw.setdefault("prev_location", cust["home_city"])
    res = engine.analyze(raw, cust)
    item = {**raw, **res, "id": raw.get("id") or uid("TXN", 7), "customer_id": cust["customer_id"],
            "customer_name": cust["full_name"]}
    if persist:
        db.save_txn(item, created_at)
        if item["status"] == "HIGH RISK":
            db.open_case(item["id"], notes=f"Auto-opened by model (score {item['risk_score']}%)")
    return item


def bootstrap():
    if db.x("SELECT COUNT(*) AS n FROM users", fetch="one")["n"]:
        return
    random.seed(7)
    for c in CUSTOMERS:
        db.add_customer(dict(customer_id=c[0], full_name=c[1], email=c[2], phone="+91 98000 11223", balance=c[7],
                             card_last4=c[8], home_city=c[3], usual_device=c[4], normal_min=c[5], normal_max=c[6]))
    pw = lambda k, d: os.getenv(k, d)
    db.create_user("customer@gmail.com", pw("CUSTOMER_PASSWORD", "pass123"), "Aarav Reddy", "CUSTOMER", "C10291")
    db.create_user("aegisrisk.officer@gmail.com", pw("OFFICER_PASSWORD", "pass123"), "Chief Risk Officer", "RISK_OFFICER")
    db.create_user("admin@gmail.com", pw("ADMIN_PASSWORD", "pass123"), "System Administrator", "ADMIN")
    custs = [db.customer(c[0]) for c in CUSTOMERS]
    start = datetime.now(timezone.utc) - timedelta(days=7)
    for i in range(320):
        cust = random.choice(custs)
        kind = random.choices(["legit", "suspicious", "fraud"], [91, 6, 3])[0]
        raw = make_raw(cust, kind)
        ts = start + timedelta(seconds=random.randint(0, 7 * 86400 - 600))
        raw["time"] = ts.astimezone(IST).strftime("%I:%M %p")
        if kind == "legit" and random.random() < 0.15:
            raw["time"] = f"0{random.randint(1, 4)}:20 AM"
        item = score(cust, raw, persist=False)
        item["id"] = uid("TXN", 7)
        db.save_txn(item, ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
        if item["status"] == "HIGH RISK" and random.random() < 0.6:
            c = db.open_case(item["id"], notes="Auto-opened by model")
            db.update_case(c["case_id"], random.choice(["OPEN", "INVESTIGATING", "CLOSED"]))
    # the headline scenario: Aarav, 3:31 AM, Kolkata, unknown device
    hero = score(custs[0], dict(id="TXN98502", amount=85000, location="Kolkata", time="03:31 AM",
                                device="Unknown Device", recent_count=3, merchant="Online Electronics"))
    db.audit("system", "BOOTSTRAP", f"Seeded demo data; model {engine.model_version}")


bootstrap()


# ============================================================ helpers
@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = CORS_ORIGINS
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/<path:_>", methods=["OPTIONS"])
def preflight(_):
    return ("", 204)


def err(msg, code=400):
    return jsonify({"error": msg}), code


def auth(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
            user = db.user_for_token(token)
            if not user:
                return err("Please sign in again.", 401)
            if roles and user["role"] not in roles:
                return err("Your role cannot access this.", 403)
            g.user, g.token = user, token
            return fn(*a, **kw)
        return wrapper
    return deco


OFFICER = ("RISK_OFFICER", "ADMIN")
attempts = defaultdict(list)


# ============================================================ public
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify(status="ok", model=engine.model_version, demo_mode=DEMO_MODE,
                   uptime_s=int(time.time() - STARTED), database="postgresql" if db.pg else "sqlite")


@app.post("/api/auth/login")
def login():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0]
    attempts[ip] = [t for t in attempts[ip] if t > time.time() - 60]
    if len(attempts[ip]) >= 8:
        return err("Too many attempts. Wait a minute and try again.", 429)
    p = request.get_json(silent=True) or {}
    res = db.login(p.get("email", ""), p.get("password", ""))
    if not res:
        attempts[ip].append(time.time())
        return err("Email or password is incorrect.", 401)
    db.audit(res[1]["email"], "LOGIN", res[1]["role"])
    return jsonify(token=res[0], user=res[1])


@app.post("/api/auth/logout")
@auth()
def logout():
    db.logout(g.token)
    return jsonify(ok=True)


@app.get("/api/auth/me")
@auth()
def me():
    return jsonify(g.user)


# ============================================================ officer / admin
@app.get("/api/stats")
@auth(*OFFICER)
def stats():
    s = db.stats()
    since = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    s["txn_last_minute"] = len(db.transactions(limit=500, since=since))
    s.update(model=engine.model_version, pr_auc=engine.metrics["pr_auc"], roc_auc=engine.metrics["roc_auc"])
    return jsonify(s)


@app.get("/api/transactions")
@auth(*OFFICER)
def transactions():
    a = request.args
    return jsonify(db.transactions(min(int(a.get("limit", 50)), 500), a.get("risk"), a.get("since")))


@app.get("/api/transactions/<tid>")
@auth(*OFFICER)
def txn_detail(tid):
    t = db.txn(tid)
    return jsonify(t) if t else err("Transaction not found.", 404)


@app.post("/api/transactions/<tid>/block")
@auth(*OFFICER)
def block(tid):
    t = db.txn(tid)
    if not t:
        return err("Transaction not found.", 404)
    db.set_txn(tid, "BLOCKED", "BLOCKED by risk officer")
    db.set_card(t["customer_id"], "BLOCKED")
    c = db.open_case(tid, g.user["full_name"], "Card frozen by risk officer")
    db.audit(g.user["email"], "BLOCK_CARD", tid)
    return jsonify(db.txn(tid) | {"case_id": c["case_id"]})


@app.post("/api/predict")
@auth(*OFFICER)
def predict():
    """What-if scoring. persist=true stores it like a real transaction."""
    p = request.get_json(silent=True) or {}
    cust = db.customer(p.get("customer_id") or "C10291")
    if not cust:
        return err("Unknown customer.", 404)
    try:
        raw = dict(amount=float(p["amount"]), location=p.get("location", cust["home_city"]), time=p.get("time") or datetime.now(IST).strftime("%I:%M %p"),
                   device=p.get("device", cust["usual_device"]), recent_count=int(p.get("recent_count", 1)), merchant=p.get("merchant", "Groceries"))
    except (KeyError, ValueError):
        return err("Amount is required and must be a number.")
    item = score(cust, raw, persist=bool(p.get("persist")))
    if p.get("persist"):
        db.audit(g.user["email"], "INJECT_TXN", item["id"])
    return jsonify(item)


@app.post("/api/simulate")
@auth(*OFFICER)
def simulate():
    cust = db.customer(random.choice(CUSTOMERS)[0])
    kind = random.choices(["legit", "suspicious", "fraud"], [74, 14, 12])[0]
    raw = make_raw(cust, kind)
    raw["recent_count"] = max(raw["recent_count"], db.recent_count(cust["customer_id"]))
    return jsonify(score(cust, raw))


@app.get("/api/cases")
@auth(*OFFICER)
def cases():
    return jsonify(db.cases())


@app.post("/api/cases")
@auth(*OFFICER)
def open_case():
    tid = (request.get_json(silent=True) or {}).get("txn_id")
    if not db.txn(tid or ""):
        return err("Transaction not found.", 404)
    c = db.open_case(tid, g.user["full_name"], "Opened manually")
    db.audit(g.user["email"], "OPEN_CASE", tid)
    return jsonify(c)


@app.post("/api/cases/<cid>")
@auth(*OFFICER)
def update_case(cid):
    p = request.get_json(silent=True) or {}
    if p.get("status") not in (None, "OPEN", "INVESTIGATING", "CLOSED"):
        return err("Status must be OPEN, INVESTIGATING or CLOSED.")
    db.update_case(cid, p.get("status"), p.get("notes"))
    db.audit(g.user["email"], "UPDATE_CASE", f"{cid} -> {p.get('status')}")
    return jsonify(ok=True)


@app.post("/api/feedback")
@auth(*OFFICER)
def feedback():
    p = request.get_json(silent=True) or {}
    label = p.get("label", "").upper()
    if label not in ("FRAUD", "LEGITIMATE") or not db.txn(p.get("txn_id", "")):
        return err("Provide a valid txn_id and label (FRAUD or LEGITIMATE).")
    db.add_feedback(p["txn_id"], label, g.user["full_name"])
    if label == "LEGITIMATE":
        db.set_txn(p["txn_id"], "CONFIRMED_LEGIT")
    db.audit(g.user["email"], "FEEDBACK", f"{p['txn_id']}={label}")
    return jsonify(ok=True, feedback_total=db.feedback_count())


@app.get("/api/analytics")
@auth(*OFFICER)
def analytics():
    rows = [r for r in db.all_for_analytics() if r["status"] in ("HIGH RISK", "BLOCKED", "REVIEW")]
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    def tally(keyfn, order=None, top=None):
        c = defaultdict(int)
        for r in rows:
            c[keyfn(r)] += 1
        keys = order or [k for k, _ in sorted(c.items(), key=lambda kv: -kv[1])][:top]
        return {"labels": keys, "data": [c.get(k, 0) for k in keys]}

    def amt(r):
        a = r["amount"]
        return "< ₹5k" if a < 5000 else "₹5k–20k" if a < 20000 else "₹20k–50k" if a < 50000 else "₹50k+"

    def hour(r):
        h = parse_hour(r["time_str"]) // 3 * 3
        return f"{h:02d}:00"

    return jsonify(
        fraud_by_day=tally(lambda r: days[datetime.strptime(r["created_at"][:10], "%Y-%m-%d").weekday()], days),
        fraud_by_location=tally(lambda r: r["location"], top=8),
        fraud_by_device=tally(lambda r: r["device"], top=6),
        fraud_by_amount=tally(amt, ["< ₹5k", "₹5k–20k", "₹20k–50k", "₹50k+"]),
        fraud_by_merchant=tally(lambda r: r["merchant"], top=8),
        fraud_by_hour=tally(hour, [f"{h:02d}:00" for h in range(0, 24, 3)]))


@app.get("/api/geo-map")
@auth(*OFFICER)
def geo():
    agg = defaultdict(lambda: [0, 0.0, 0])
    for t in db.transactions(limit=500):
        a = agg[t["location"]]; a[0] += 1; a[1] += t["risk_score"] or 0
        a[2] += t["status"] in ("HIGH RISK", "BLOCKED")
    out = []
    for city, (la, lo) in CITIES.items():
        n, tot, hi = agg[city]
        avg = round(tot / n, 1) if n else 0
        out.append(dict(city=city, lat=la, lng=lo, txns=n, flagged=hi, avg_risk=avg,
                        risk="HIGH" if hi >= 3 or avg > 40 else "ELEVATED" if hi else "NORMAL"))
    return jsonify(out)


@app.get("/api/customers")
@auth(*OFFICER)
def customers():
    return jsonify(db.customers())


@app.get("/api/customers/<cid>")
@auth(*OFFICER)
def customer_detail(cid):
    c = db.customer(cid)
    if not c:
        return err("Customer not found.", 404)
    t = db.transactions(limit=25, cid=cid)
    worst = max(t, key=lambda x: x["risk_score"] or 0, default=None)
    return jsonify(customer=c, transactions=t, worst=worst)


@app.get("/api/monitoring")
@auth(*OFFICER)
def monitoring():
    d = engine.drift(db.feature_rows(400))
    d.update(model=engine.model_version, last_trained=engine.trained_at, training_samples=engine.n_train,
             feedback_labels=db.feedback_count(), history=engine.history[-6:])
    return jsonify(d)


@app.get("/api/model/metrics")
@auth(*OFFICER)
def model_metrics():
    return jsonify(model=engine.model_version, metrics=engine.metrics, benchmarks=engine.benchmarks,
                   importance=engine.importance, confusion=engine.confusion)


@app.post("/api/retrain")
@auth(*OFFICER)
def retrain():
    before = dict(engine.metrics)
    X, y = db.feedback_training_rows()
    engine.train(extra=(X, y) if X else None)
    db.audit(g.user["email"], "RETRAIN", f"{engine.model_version}, {len(X)} feedback rows")
    return jsonify(ok=True, model=engine.model_version, feedback_used=len(X), before=before, after=engine.metrics)


@app.get("/api/export/transactions.csv")
@auth(*OFFICER)
def export_csv():
    rows = db.transactions(limit=5000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "created_at", "customer", "amount", "location", "device", "merchant", "risk_score", "status", "action"])
    for r in rows:
        w.writerow([r["id"], r["created_at"], r["customer_name"], r["amount"], r["location"], r["device"], r["merchant"], r["risk_score"], r["status"], r["action"]])
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=aegisrisk_transactions.csv"})


# ============================================================ admin
@app.get("/api/admin/users")
@auth("ADMIN")
def admin_users():
    return jsonify(users=db.users(), audit=db.audit_log())


@app.post("/api/admin/users")
@auth("ADMIN")
def admin_create_user():
    p = request.get_json(silent=True) or {}
    email, name, role, pw = (p.get("email") or "").strip(), (p.get("full_name") or "").strip(), p.get("role"), p.get("password") or ""
    if not email or not name or role not in ("CUSTOMER", "RISK_OFFICER", "ADMIN") or len(pw) < 8:
        return err("Name, email, a valid role and a password of 8+ characters are required.")
    try:
        uid_ = db.create_user(email, pw, name, role, "C10291" if role == "CUSTOMER" else None)
    except Exception:
        return err("A user with that email already exists.", 409)
    db.audit(g.user["email"], "CREATE_USER", f"{email} ({role})")
    return jsonify(ok=True, user_id=uid_)


# ============================================================ customer
@app.get("/api/customer/me")
@auth("CUSTOMER")
def customer_me():
    cid = g.user["customer_id"]
    txns = db.transactions(limit=25, cid=cid)
    alerts = [t for t in txns if t["status"] in ("HIGH RISK", "REVIEW") and not t.get("customer_response")]
    return jsonify(customer=db.customer(cid), transactions=txns, alerts=alerts)


@app.post("/api/customer/pay")
@auth("CUSTOMER")
def customer_pay():
    cust = db.customer(g.user["customer_id"])
    p = request.get_json(silent=True) or {}
    try:
        amount = float(p.get("amount"))
    except (TypeError, ValueError):
        return err("Enter a valid amount.")
    if amount <= 0:
        return err("Amount must be greater than zero.")
    if cust["card_status"] == "BLOCKED":
        return err("Your card is blocked. Contact the bank to unblock it.", 403)
    if amount > cust["balance"]:
        return err("Insufficient balance.")
    device = cust["usual_device"] if p.get("device") in (None, "", "This device") else p["device"]
    raw = dict(amount=amount, location=p.get("location") or cust["home_city"], time=datetime.now(IST).strftime("%I:%M %p"),
               device=device, merchant=p.get("merchant") or "Groceries", recent_count=db.recent_count(cust["customer_id"]))
    item = score(cust, raw)
    if item["status"] == "SAFE":
        db.set_balance(cust["customer_id"], -amount)
    return jsonify(item)


@app.post("/api/customer/respond")
@auth("CUSTOMER")
def customer_respond():
    p = request.get_json(silent=True) or {}
    t = db.txn(p.get("txn_id", ""))
    if not t or t["customer_id"] != g.user["customer_id"]:
        return err("Transaction not found.", 404)
    if p.get("action") == "YES_IT_WAS_ME":
        db.set_txn(t["id"], "CONFIRMED_LEGIT", "Confirmed by customer", "YES_IT_WAS_ME")
        db.set_balance(t["customer_id"], -t["amount"])
    elif p.get("action") == "BLOCK_CARD":
        db.set_txn(t["id"], "BLOCKED", "Card blocked by customer", "BLOCK_CARD")
        db.set_card(t["customer_id"], "BLOCKED")
        db.open_case(t["id"], notes="Customer reported fraud and blocked card", priority="CRITICAL")
    else:
        return err("Unknown action.")
    db.audit(g.user["email"], "CUSTOMER_RESPONSE", f"{t['id']}: {p['action']}")
    return jsonify(ok=True, transaction=db.txn(t["id"]))


@app.errorhandler(404)
def nf(_):
    if request.path.startswith("/api/"):
        return err("Endpoint not found.", 404)
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"AegisRisk running on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
