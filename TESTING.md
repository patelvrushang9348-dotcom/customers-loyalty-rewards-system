# Testing

## Automated
```bash
python -m unittest discover -s tests -v
```
Result at time of writing: **29 tests, all passing** (about 16 s; most of it is password hashing).

| Group | What is covered |
|---|---|
| Code helpers | uniqueness of 2,000 generated codes, checksum rejects typos and wrong pepper, input normalisation, hash is not plaintext |
| Auth | duplicate email, validation, protected routes, customer cannot use admin API, JSON-only writes, admin login throttle |
| Redemption | points awarded once, reuse by same and other customer, lowercase/no-dash input, fake codes, codes stored hashed only, lockout after 5 failures (even for a valid code), voided batch, void keeps redeemed codes, expiry, suspended customer, **8 simultaneous redemptions of one code, exactly one succeeds** |
| Rewards | claim deducts points, cannot overspend, out-of-stock does not charge, cancel refunds and restocks, **concurrent claims cannot oversell the last item**, ledger sums to balance |
| Admin | batch validation, duplicate SKU, stats and fraud log reflect activity |

### Do the tests catch real bugs?
Two protections were deliberately broken to check (mutation test):
1. Removing the "already redeemed" check and the conditional `WHERE status='unused'` -> 3 redemption tests failed.
2. Disabling the lockout threshold -> the lockout test failed.
Both changes were reverted.

## Manual smoke test (run against the real server, `python run.py`)
| Step | Expected | Result |
|---|---|---|
| `GET /`, `/admin`, `/static/*.js`, `/static/app.css` | 200 | Pass |
| Response headers include CSP and `X-Frame-Options: DENY` | present | Pass |
| `init_env.py` then `seed_demo.py` | `.env` and `demo_codes.csv` created | Pass |
| Register, redeem a demo code | +20 points | Pass |
| Redeem same code again | "already redeemed" error | Pass |
| Admin login, `GET /api/admin/stats` | shows 20 generated, 1 redeemed, 1 failed attempt | Pass |
| JavaScript files parse (`node --check`) | no syntax errors | Pass |

## Not yet tested (be honest in your demo)
- Visual behaviour of the two pages in real browsers and on mobile. Please click through once: register, enter a code from `demo_codes.csv`, claim a reward, then in `/admin` generate a batch, fulfil the claim, and view the Fraud log.
- Running under gunicorn and Docker (gunicorn was not installed in the build sandbox).
