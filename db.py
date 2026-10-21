"""
Portable database layer: SQLite by default, PostgreSQL when DATABASE_URL is set.
All SQL is written once with '?' placeholders; they become '%s' for PostgreSQL.
"""
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

DATABASE_URL = os.getenv("DATABASE_URL", "").replace("postgres://", "postgresql://", 1)
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "aegis.db"))
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "12"))

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
       password_hash TEXT NOT NULL, full_name TEXT NOT NULL, role TEXT NOT NULL, customer_id TEXT,
       created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS customers (customer_id TEXT PRIMARY KEY, full_name TEXT NOT NULL,
       email TEXT, phone TEXT, balance DOUBLE PRECISION DEFAULT 0, card_last4 TEXT, card_status TEXT DEFAULT 'ACTIVE',
       home_city TEXT, usual_device TEXT, normal_min DOUBLE PRECISION, normal_max DOUBLE PRECISION, created_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS transactions (txn_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, customer_name TEXT,
       amount DOUBLE PRECISION NOT NULL, location TEXT, prev_location TEXT, time_str TEXT, device TEXT,
       recent_count INTEGER DEFAULT 1, merchant TEXT, status TEXT NOT NULL, risk_score DOUBLE PRECISION,
       anomaly_score DOUBLE PRECISION, action TEXT, model_version TEXT, shap_json TEXT, rules_json TEXT,
       features_json TEXT, customer_response TEXT, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS cases (case_id TEXT PRIMARY KEY, txn_id TEXT NOT NULL, assigned_officer TEXT,
       status TEXT DEFAULT 'OPEN', priority TEXT DEFAULT 'HIGH', notes TEXT, created_at TEXT, updated_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS feedback (feedback_id TEXT PRIMARY KEY, txn_id TEXT NOT NULL, actual_label TEXT NOT NULL,
       analyst TEXT, created_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS audit_log (audit_id TEXT PRIMARY KEY, actor TEXT, action TEXT, detail TEXT, created_at TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_txn_created ON transactions(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_txn_customer ON transactions(customer_id)",
    "CREATE INDEX IF NOT EXISTS idx_txn_status ON transactions(status)",
]


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def uid(prefix, n=8):
    return f"{prefix}-{uuid.uuid4().hex[:n].upper()}"


class Database:
    def __init__(self):
        self.pg = bool(DATABASE_URL)
        if not self.pg:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        for stmt in SCHEMA:
            self.x(stmt)

    # -------------------------------------------------------------- core
    def _connect(self):
        if self.pg:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        con = sqlite3.connect(DB_PATH, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def x(self, sql, args=(), fetch=None):
        con = self._connect()
        try:
            cur = con.cursor()
            cur.execute(sql.replace("?", "%s") if self.pg else sql, args)
            out = None
            if fetch == "all":
                out = [dict(r) for r in cur.fetchall()]
            elif fetch == "one":
                r = cur.fetchone()
                out = dict(r) if r else None
            con.commit()
            return out
        finally:
            con.close()

    # -------------------------------------------------------------- auth
    def create_user(self, email, password, full_name, role, customer_id=None):
        uid_ = uid("USR", 6)
        self.x("INSERT INTO users VALUES (?,?,?,?,?,?,?)",
               (uid_, email.lower().strip(), generate_password_hash(password), full_name, role, customer_id, now()))
        return uid_

    def login(self, email, password):
        u = self.x("SELECT * FROM users WHERE email=?", (email.lower().strip(),), "one")
        if not u or not check_password_hash(u["password_hash"], password):
            return None
        token = secrets.token_urlsafe(32)
        exp = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        self.x("INSERT INTO sessions VALUES (?,?,?)", (token, u["user_id"], exp))
        return token, self.public_user(u)

    @staticmethod
    def public_user(u):
        return {k: u[k] for k in ("user_id", "email", "full_name", "role", "customer_id")}

    def user_for_token(self, token):
        if not token:
            return None
        row = self.x("""SELECT u.*, s.expires_at FROM sessions s JOIN users u ON u.user_id=s.user_id
                        WHERE s.token=?""", (token,), "one")
        if not row or row["expires_at"] < now():
            return None
        return self.public_user(row)

    def logout(self, token):
        self.x("DELETE FROM sessions WHERE token=?", (token,))

    def users(self):
        return self.x("SELECT user_id,email,full_name,role,customer_id,created_at FROM users ORDER BY created_at DESC",
                      fetch="all")

    def audit(self, actor, action, detail=""):
        self.x("INSERT INTO audit_log VALUES (?,?,?,?,?)", (uid("AUD"), actor, action, detail, now()))

    def audit_log(self, limit=60):
        return self.x("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,), "all")

    # -------------------------------------------------------------- customers
    def customer(self, cid):
        return self.x("SELECT * FROM customers WHERE customer_id=?", (cid,), "one")

    def customers(self):
        rows = self.x("SELECT * FROM customers ORDER BY customer_id", fetch="all")
        for r in rows:
            s = self.x("""SELECT COUNT(*) AS n,
                 SUM(CASE WHEN status IN ('HIGH RISK','BLOCKED') THEN 1 ELSE 0 END) AS flagged,
                 SUM(CASE WHEN status='REVIEW' THEN 1 ELSE 0 END) AS review
                 FROM transactions WHERE customer_id=?""", (r["customer_id"],), "one")
            r.update({"txn_count": int(s["n"] or 0), "flagged": int(s["flagged"] or 0), "review": int(s["review"] or 0)})
        return rows

    def add_customer(self, c):
        self.x("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (c["customer_id"], c["full_name"], c["email"], c["phone"], c["balance"], c["card_last4"], "ACTIVE",
                c["home_city"], c["usual_device"], c["normal_min"], c["normal_max"], now()))

    def set_balance(self, cid, delta):
        self.x("UPDATE customers SET balance = balance + ? WHERE customer_id=?", (delta, cid))

    def set_card(self, cid, status):
        self.x("UPDATE customers SET card_status=? WHERE customer_id=?", (status, cid))

    # -------------------------------------------------------------- transactions
    def recent_count(self, cid, seconds=120):
        since = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        r = self.x("SELECT COUNT(*) AS n FROM transactions WHERE customer_id=? AND created_at>=?", (cid, since), "one")
        return (r["n"] or 0) + 1

    def save_txn(self, t, created_at=None):
        self.x("""INSERT INTO transactions (txn_id,customer_id,customer_name,amount,location,prev_location,time_str,device,
                  recent_count,merchant,status,risk_score,anomaly_score,action,model_version,shap_json,rules_json,
                  features_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (t["id"], t["customer_id"], t.get("customer_name"), float(t["amount"]), t.get("location"),
                t.get("prev_location"), t.get("time"), t.get("device"), int(t.get("recent_count", 1)),
                t.get("merchant"), t["status"], t["risk_score"], t["anomaly_score"], t["action"], t["model_version"],
                json.dumps(t["shap_factors"]), json.dumps(t["rules"]), json.dumps(t["features"]), created_at or now()))

    @staticmethod
    def _txn(r):
        r["id"] = r.pop("txn_id")
        r["time"] = r.pop("time_str")
        r["shap_factors"] = json.loads(r.pop("shap_json") or "[]")
        r["rules"] = json.loads(r.pop("rules_json") or "[]")
        r.pop("features_json", None)
        return r

    def transactions(self, limit=50, status=None, since=None, cid=None):
        q, a = "SELECT * FROM transactions WHERE 1=1", []
        if status and status != "ALL":
            q += " AND status=?"; a.append(status)
        if since:
            q += " AND created_at>?"; a.append(since)
        if cid:
            q += " AND customer_id=?"; a.append(cid)
        q += " ORDER BY created_at DESC LIMIT ?"; a.append(int(limit))
        return [self._txn(r) for r in self.x(q, a, "all")]

    def txn(self, tid):
        r = self.x("SELECT * FROM transactions WHERE txn_id=?", (tid,), "one")
        return self._txn(r) if r else None

    def set_txn(self, tid, status, action=None, response=None):
        self.x("UPDATE transactions SET status=?, action=COALESCE(?,action), customer_response=COALESCE(?,customer_response) WHERE txn_id=?",
               (status, action, response, tid))

    def feature_rows(self, limit=400):
        rows = self.x("SELECT features_json FROM transactions ORDER BY created_at DESC LIMIT ?", (limit,), "all")
        return [json.loads(r["features_json"]) for r in rows if r["features_json"]]

    def all_for_analytics(self):
        return self.x("SELECT amount,location,device,merchant,status,created_at,time_str FROM transactions", fetch="all")

    def stats(self):
        r = self.x("""SELECT COUNT(*) AS total,
            SUM(CASE WHEN status IN ('HIGH RISK','BLOCKED') THEN 1 ELSE 0 END) AS flagged,
            SUM(CASE WHEN status='REVIEW' THEN 1 ELSE 0 END) AS review,
            SUM(CASE WHEN status IN ('HIGH RISK','BLOCKED','REVIEW') THEN amount ELSE 0 END) AS at_risk,
            SUM(CASE WHEN status='BLOCKED' THEN amount ELSE 0 END) AS blocked_amt FROM transactions""", fetch="one")
        total = int(r["total"] or 0); flagged = int(r["flagged"] or 0); review = int(r["review"] or 0)
        return {"total_transactions": total, "fraud_detected": flagged, "review_count": review,
                "safe_count": total - flagged - review,
                "fraud_rate": round(flagged / total * 100, 2) if total else 0,
                "amount_at_risk": float(r["at_risk"] or 0), "amount_blocked": float(r["blocked_amt"] or 0)}

    # -------------------------------------------------------------- cases & feedback
    def cases(self):
        return self.x("""SELECT c.*, t.customer_name, t.amount, t.location, t.device, t.risk_score
                         FROM cases c JOIN transactions t ON t.txn_id=c.txn_id ORDER BY c.created_at DESC""", fetch="all")

    def open_case(self, tid, officer="Risk Operations", notes="", priority="HIGH"):
        ex = self.x("SELECT * FROM cases WHERE txn_id=? AND status<>'CLOSED'", (tid,), "one")
        if ex:
            return ex
        c = {"case_id": uid("CASE", 6), "txn_id": tid, "assigned_officer": officer, "status": "OPEN",
             "priority": priority, "notes": notes, "created_at": now(), "updated_at": now()}
        self.x("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?)", tuple(c.values()))
        return c

    def update_case(self, cid, status=None, notes=None):
        self.x("UPDATE cases SET status=COALESCE(?,status), notes=COALESCE(?,notes), updated_at=? WHERE case_id=?",
               (status, notes, now(), cid))

    def add_feedback(self, tid, label, analyst):
        self.x("DELETE FROM feedback WHERE txn_id=?", (tid,))
        self.x("INSERT INTO feedback VALUES (?,?,?,?,?)", (uid("FB", 6), tid, label, analyst, now()))

    def feedback_training_rows(self):
        rows = self.x("""SELECT f.actual_label, t.features_json FROM feedback f
                         JOIN transactions t ON t.txn_id=f.txn_id""", fetch="all")
        X = [json.loads(r["features_json"]) for r in rows if r["features_json"]]
        y = [1 if r["actual_label"] == "FRAUD" else 0 for r in rows if r["features_json"]]
        return X, y

    def feedback_count(self):
        return self.x("SELECT COUNT(*) AS n FROM feedback", fetch="one")["n"]


db = Database()
