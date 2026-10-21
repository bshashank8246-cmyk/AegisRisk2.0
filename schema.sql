-- AegisRisk schema (SQLite and PostgreSQL compatible). Created automatically on first start.

CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
       password_hash TEXT NOT NULL, full_name TEXT NOT NULL, role TEXT NOT NULL, customer_id TEXT,
       created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS customers (customer_id TEXT PRIMARY KEY, full_name TEXT NOT NULL,
       email TEXT, phone TEXT, balance DOUBLE PRECISION DEFAULT 0, card_last4 TEXT, card_status TEXT DEFAULT 'ACTIVE',
       home_city TEXT, usual_device TEXT, normal_min DOUBLE PRECISION, normal_max DOUBLE PRECISION, created_at TEXT);

CREATE TABLE IF NOT EXISTS transactions (txn_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, customer_name TEXT,
       amount DOUBLE PRECISION NOT NULL, location TEXT, prev_location TEXT, time_str TEXT, device TEXT,
       recent_count INTEGER DEFAULT 1, merchant TEXT, status TEXT NOT NULL, risk_score DOUBLE PRECISION,
       anomaly_score DOUBLE PRECISION, action TEXT, model_version TEXT, shap_json TEXT, rules_json TEXT,
       features_json TEXT, customer_response TEXT, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS cases (case_id TEXT PRIMARY KEY, txn_id TEXT NOT NULL, assigned_officer TEXT,
       status TEXT DEFAULT 'OPEN', priority TEXT DEFAULT 'HIGH', notes TEXT, created_at TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS feedback (feedback_id TEXT PRIMARY KEY, txn_id TEXT NOT NULL, actual_label TEXT NOT NULL,
       analyst TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS audit_log (audit_id TEXT PRIMARY KEY, actor TEXT, action TEXT, detail TEXT, created_at TEXT);

CREATE INDEX IF NOT EXISTS idx_txn_created ON transactions(created_at);

CREATE INDEX IF NOT EXISTS idx_txn_customer ON transactions(customer_id);

CREATE INDEX IF NOT EXISTS idx_txn_status ON transactions(status);
