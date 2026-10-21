"""Quick self-check:  python smoke_test.py   (uses a temporary database)"""
import os, tempfile
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
import app as A
c = A.app.test_client()
def tok(e): return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": e, "password": "pass123"}).json["token"]}
o, cu = tok("cro@securebank.com"), tok("customer@securebank.com")
assert c.get("/api/stats").status_code == 401
assert c.get("/api/stats", headers=cu).status_code == 403
assert c.get("/api/stats", headers=o).json["total_transactions"] > 0
r = c.post("/api/predict", headers=o, json={"amount": 90000, "location": "Delhi", "device": "Unknown Device", "merchant": "Crypto Onramp", "time": "02:10 AM", "recent_count": 4}).json
assert r["status"] == "HIGH RISK", r
assert c.post("/api/customer/pay", headers=cu, json={"amount": 300, "merchant": "Groceries"}).json["status"] == "SAFE"
assert c.get("/").status_code == 200
print("All checks passed")
