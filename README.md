# Box Rewards: Customer Loyalty Rewards System

A loyalty system for a factory that sells products in boxes. Each box has a unique, single-use code printed inside. Customers enter the code to earn points and exchange points for rewards. The factory owner prints codes, manages the reward catalogue, fulfils claims and watches for fraud from a dashboard.

**Deployed link:** _add yours here (e.g. Render / Railway / Fly.io) or remove this line._

## Features

**Customers** (`/`): register and log in; enter the box code to earn points; browse and claim rewards; view points history and claim status.

**Factory owner** (`/admin`):
- Overview: codes printed and redeemed, redemption rate, points issued and outstanding (liability), claims waiting, failed attempts and lockouts in the last 24h, a 14-day redemption chart, and a per-product breakdown.
- Batches: generate up to 10,000 codes per batch for a product and download them as a CSV for the printer. Void a whole batch if it is recalled or compromised.
- Products: set points per box; deactivate products.
- Rewards: manage the catalogue, points cost and stock (blank means unlimited).
- Claims: mark claims fulfilled, or cancel them with an automatic refund and restock.
- Customers: see failed attempts per customer; suspend and reinstate accounts.
- Fraud log: every redemption outcome and failed login, filterable.

## Tech stack

Python 3.10+ / Flask 3 · SQLite (standard library `sqlite3`, WAL mode) · vanilla HTML/CSS/JS (no build step) · `unittest` · gunicorn for production. Reasons are in [ARCHITECTURE.md](ARCHITECTURE.md).

## Setup and run

```bash
git clone <your-repo-url> && cd loyalty-rewards
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python scripts/init_env.py        # creates .env with random secrets and prints the admin password
python scripts/seed_demo.py       # optional: demo products, rewards and 20 sample codes (demo_codes.csv)
python run.py                     # http://127.0.0.1:5000
```

- Customer site: http://127.0.0.1:5000/
- Owner dashboard: http://127.0.0.1:5000/admin (username `owner`, password printed by `init_env.py`)
- Production: `gunicorn -w 2 -b 0.0.0.0:8000 run:app`, or use the included `Dockerfile`.

Configuration is via environment variables; see [.env.example](.env.example). **The app refuses to start if `SECRET_KEY` or `CODE_PEPPER` are missing or still placeholders.**

> Back up `CODE_PEPPER` separately from the database. Codes are validated against it, so losing it invalidates every printed code.

## Running the tests

```bash
python -m unittest discover -s tests -v
```

29 automated tests, including concurrency tests (8 customers redeeming one code at the same instant; 4 customers claiming the last item). See [TESTING.md](TESTING.md).

## Database connection

`app/db.py` opens one SQLite connection per request (`DATABASE_PATH` in `.env`), enables foreign keys and WAL, and wraps writes in `BEGIN IMMEDIATE` transactions. The schema in `app/schema.sql` is created automatically on first start. Delete the `.db` file to reset.

## API summary

| Area | Endpoints |
|---|---|
| Customer | `POST /api/register`, `/api/login`, `/api/logout` · `GET /api/me` · `POST /api/redeem` · `GET /api/rewards` · `POST /api/rewards/<id>/claim` · `GET /api/history` |
| Admin | `POST /api/admin/login`, `/logout` · `GET /api/admin/stats` · `GET/POST /api/admin/products` · `POST /api/admin/batches` · `GET /api/admin/batches` · `POST /api/admin/batches/<id>/void` · `GET/POST/PUT /api/admin/rewards` · `GET /api/admin/claims` · `POST /api/admin/claims/<id>/status` · `GET /api/admin/customers` · `POST /api/admin/customers/<id>/status` · `GET /api/admin/events` |

## Known limitations

See the end of [ASSUMPTIONS.md](ASSUMPTIONS.md). The main ones: no email verification or password reset, IP throttling depends on correct proxy configuration, SQLite suits one server (not horizontal scaling), and the UI has not been tested in a real browser across devices.
