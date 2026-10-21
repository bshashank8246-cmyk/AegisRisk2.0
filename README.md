# AegisRisk – fraud detection and risk operations

Flask API + ML scoring + animated, responsive risk command centre, in one deployable app.

The refreshed interface uses a dark intelligence-console theme, a gradient AegisRisk identity, animated sign-in visuals, responsive layouts, elevated dashboard cards, and accessible reduced-motion support.

* **Risk officers**: live payment stream, animated threat map, per-payment explanation (exact Shapley values), cases, analytics, model performance, drift monitoring, retraining with analyst feedback, simulator, CSV export.
* **Customers**: balance and card, make a payment (scored live), respond to fraud alerts ("Yes, it was me" / "Block my card").
* **Admins**: everything above plus user management and an audit log.

## Run it in VS Code

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python app.py                   # first start trains the model (~15 s) and seeds demo data
```
Open http://localhost:8000 . Demo logins (password `pass123`): `cro@securebank.com` (risk officer), `customer@securebank.com`, `admin@securebank.com`.

Check it works: `python smoke_test.py`.

> The old `.venv` folder was committed to your repo. Delete it from git (`git rm -r --cached .venv`) – the new `.gitignore` keeps it out.

## Deploy

**Render (easiest, one service for API + frontend)**
1. Create a GitHub repository and upload the **contents of this `AegisRisk` folder** to the repository root (so `render.yaml`, `app.py`, and `requirements.txt` are at the top level).
2. Render → **New + → Blueprint** → select the repository containing `render.yaml`.
3. Wait for the build and deploy to finish, then open the generated `onrender.com` URL.
4. In Render → your service → **Environment**, set `OFFICER_PASSWORD`, `ADMIN_PASSWORD`, and `CUSTOMER_PASSWORD` to passwords you know, then redeploy. Use the corresponding demo email address with the password you set. Do not use `pass123` on a public deployment.
5. The default SQLite demo database is ephemeral on Render's free service and may reset on redeploy/restart. For persistent records, create a Render PostgreSQL database and configure `DATABASE_URL` as described below.

**Railway / Heroku-style hosts** – the `Procfile` is ready. Set `DATABASE_URL` if you add Postgres.

**Docker** – `docker compose up --build` starts the app with PostgreSQL on http://localhost:8000 .

**Frontend on Netlify + backend on Render** – deploy the backend first. In `netlify.toml` replace `YOUR-BACKEND` with your Render URL, then deploy the repo to Netlify (publish directory `static`). The proxy rule forwards `/api/*`, so no CORS setup is needed. Alternatively set `window.AEGIS_API_BASE` in `static/js/config.js` and `CORS_ORIGINS` on the backend.

Always run **one** gunicorn worker (already configured): the model is held in memory, so retraining must reach the same process.

## Environment variables
See `.env.example`. Passwords apply only when the database is first created; change demo passwords before sharing a public link.

## API summary
`POST /api/auth/login` → token (send as `Authorization: Bearer …`). Officer/admin: `/api/stats`, `/api/transactions`, `/api/analytics`, `/api/geo-map`, `/api/customers`, `/api/cases`, `/api/monitoring`, `/api/model/metrics`, `POST /api/predict`, `POST /api/simulate`, `POST /api/retrain`, `POST /api/feedback`. Customer: `/api/customer/me`, `/api/customer/pay`, `/api/customer/respond`. Admin: `/api/admin/users`. Health: `/api/health`.

## What is real, and what is not
* Metrics, confusion matrix, benchmarks, drift (PSI) and explanations are **computed**, not hard-coded.
* Training data is **synthetic** (overlapping distributions, 3% fraud), so the scores demonstrate the pipeline, not real-world accuracy. To use real data, replace `_gen()` in `ml_engine.py` with your labelled transactions, keeping the six features in `featurize()`.
* The active model is scikit-learn Gradient Boosting; install `xgboost` and it is used automatically.
* "Demo traffic" generates sample payments so the live feed moves. Turn it off (or set `DEMO_MODE=0`) in a real deployment.
* PostgreSQL support is written to share SQL with SQLite, but was tested against SQLite only.
