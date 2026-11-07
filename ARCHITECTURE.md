# Architecture

## Stack and why

| Layer | Choice | Reason |
|---|---|---|
| Backend | **Python 3 + Flask** | Small, readable, easy to explain line by line. Test client makes API tests fast. |
| Database | **SQLite** (WAL mode) | No server to install, one file, real transactions and constraints. `BEGIN IMMEDIATE` gives the atomic redemption the design depends on. |
| Front end | **Vanilla JavaScript + CSS**, hash router, no build step | Nothing to compile. Any grader can open it. Works on phones. Served by Flask as static files. |
| Auth | Server-side signed session cookie (`HttpOnly`, `SameSite=Lax`), Werkzeug password hashing | No tokens in JavaScript, nothing to steal via XSS. |
| Tests | Python `unittest` | Standard library, no extra install. |
| Deploy | `gunicorn "app:create_app()"` | Standard WSGI. |

## Components

```mermaid
flowchart LR
  subgraph Browser
    UI[Customer + Owner UI<br/>HTML / CSS / JS]
  end
  subgraph Flask["Flask app (app.py)"]
    AUTH[Auth + sessions]
    RED[Redeem endpoint<br/>rate limits + atomic claim]
    ADM[Admin endpoints<br/>batches, rewards, claims, alerts]
  end
  DB[(SQLite file<br/>loyalty.db)]
  PRINT[Printer / packing line]
  UI -- "JSON over HTTPS<br/>+ X-Requested-With" --> AUTH
  UI --> RED
  UI --> ADM
  AUTH --> DB
  RED --> DB
  ADM --> DB
  ADM -. "CSV of codes (shown once)" .-> PRINT
```

## How a customer proves a purchase (and why reuse fails)

```mermaid
sequenceDiagram
  participant O as Owner
  participant S as Server
  participant D as Database
  participant C as Customer
  O->>S: Generate batch (product, qty)
  S->>D: Store HMAC(code) + serial, status=unused
  S-->>O: CSV of plain codes (only time they exist)
  Note over O: Codes printed inside boxes
  C->>S: Enter code (signed in)
  S->>D: Count recent failures (user + IP)
  alt over limit
    S-->>C: 429 locked for 15 min
  else ok
    S->>D: Look up HMAC(code)
    alt unknown / voided / already used
      S->>D: Log failed attempt
      S-->>C: 404 / 410 / 409
    else unused
      S->>D: BEGIN IMMEDIATE
      S->>D: UPDATE codes SET redeemed WHERE status='unused'
      Note over D: rowcount must be 1, else the other request won
      S->>D: Add points + ledger row, COMMIT
      S-->>C: +points
    end
  end
```

## Data model

```mermaid
erDiagram
  users ||--o{ ledger : "earns / spends"
  users ||--o{ claims : makes
  users ||--o{ attempts : "tries codes"
  users |o--o{ codes : redeems
  products ||--o{ batches : "printed as"
  batches ||--|{ codes : contains
  rewards ||--o{ claims : "claimed as"
  users ||--o{ audit : "admin actions"

  users { int id PK
    text email UK
    text password_hash
    text role "customer|admin"
    int points_balance "CHECK >= 0"
    int lifetime_points
    int blocked }
  products { int id PK
    text sku UK
    text name
    int points }
  batches { int id PK
    int product_id FK
    int quantity
    text status "active|voided" }
  codes { int id PK
    int batch_id FK
    text serial UK
    text code_hash UK "HMAC-SHA256"
    text status "unused|redeemed|voided"
    int redeemed_by FK }
  ledger { int id PK
    int user_id FK
    int delta
    text reason }
  rewards { int id PK
    text name
    int cost
    int stock "CHECK >= 0" }
  claims { int id PK
    int user_id FK
    int reward_id FK
    text status "pending|fulfilled|rejected" }
  attempts { int id PK
    int user_id FK
    text ip
    text outcome
    text code_hash }
  audit { int id PK
    int actor_id FK
    text action
    text detail }
```

Full DDL: [`schema.sql`](schema.sql).

## Fraud prevention: layers

| Threat | Defence |
|---|---|
| Reusing a code (same or different account) | Single atomic `UPDATE … WHERE status='unused'`. The `status` column and the `UNIQUE code_hash` live in the database, not in app memory. |
| Two requests at the same instant | `BEGIN IMMEDIATE` serialises writers. Tested with 8 parallel requests: exactly one succeeds. |
| Guessing codes | 60-bit random codes + 5 failures per 15 min per user + 20 per hour per IP. Even valid codes are refused while locked. |
| Stolen database | Only keyed hashes of codes are stored. Passwords are salted hashes. |
| Stolen or misprinted batch | Owner cancels unused codes in one click. |
| Credential stuffing | 10 failed logins per IP per 15 min. |
| Cross-site request forgery | `SameSite=Lax` cookie + required `X-Requested-With` header on every write. |
| XSS | All dynamic text is HTML-escaped in the UI. Strict Content-Security-Policy (no inline scripts). |
| Privilege escalation | Every `/api/admin/*` route uses `admin_required`. Tested: customers get 403, anonymous gets 401. |
| Over-spending points / stock | Guarded `UPDATE … WHERE points_balance >= cost` and `stock > 0`, plus `CHECK` constraints. |
| Detection | `attempts` table feeds the owner's **Fraud alerts** page: accounts with repeat failures, noisy IPs, codes many people try to reuse. `audit` records every owner action. |

## Database connection

`db.py` opens one SQLite connection per request (`sqlite3.connect(DB_PATH)`, autocommit, `foreign_keys=ON`, WAL, 15 s busy timeout). `DB_PATH` comes from `.env`. Open the file with any SQLite viewer (for example *DB Browser for SQLite*) or `sqlite3 loyalty.db`.

**Moving to PostgreSQL later:** only `db.py` and the `datetime('now')` / `date()` expressions in `app.py` and `schema.sql` are SQLite-specific. The rest is standard SQL. The atomic `UPDATE … WHERE status='unused'` pattern works unchanged in PostgreSQL.

## Known limitations

- SQLite allows one writer at a time. Fine for one factory; use PostgreSQL for very high traffic.
- Behind a reverse proxy, configure the proxy to pass the real client IP (otherwise IP limits see the proxy's address).
- No email verification or password reset yet.
- A lost code CSV cannot be recovered by design.
