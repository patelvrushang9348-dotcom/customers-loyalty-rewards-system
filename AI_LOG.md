# AI Log

> **Important:** the assignment asks you to explain every part of your submission. The entries below are the real interactions from the session that produced this code. Replace or extend them with your own prompts (5 to 10 total) and make sure you can explain each decision. Two genuine AI mistakes are included (entries 3 and 4).

## 1. Turning the brief into design decisions
**Prompt:** Pasted the assignment PDF and asked for the full code, backend and database connection.
**What the AI did:** Split the brief into its three required questions (proof of purchase, fraud/reuse, owner management) and chose a design: a unique single-use code printed inside each box, stored only as a keyed hash, redeemed through an atomic database update.
**My decision:** Accepted the design; every gap it filled was written into ASSUMPTIONS.md.

## 2. Choosing the stack under real constraints
**Prompt/Action:** Before writing code, checked what was installed (`pip list`).
**Finding:** Flask was available; SQLAlchemy and pytest were not, and the sandbox had no network.
**Decision:** Use stdlib `sqlite3` with a thin transaction helper, and `unittest`. Benefit: explicit SQL, one dependency to explain. Cost: no ORM and no Postgres support out of the box (documented).

## 3. AI mistake: fragile rollback in reward claims
**What went wrong:** The first version of `claim_reward` handled "out of stock" by manually running `ROLLBACK` then `BEGIN IMMEDIATE` inside the transaction context manager, so the manager's final `COMMIT` would not fail.
**How I noticed:** Re-reading the code after writing it. The manual transaction juggling inside a context manager is easy to break, and an exception between the two statements would leave the connection in an inconsistent state.
**Fix:** Introduced a small `_Abort` exception. Raising it inside `with transaction(db)` triggers the context manager's normal rollback; the route catches it and returns the error. A test (`test_out_of_stock_does_not_charge_points`) now verifies the deducted points are restored.

## 4. AI mistake: assuming gunicorn was available for the smoke test
**What went wrong:** The first end-to-end smoke test started the server with `gunicorn`, assuming it was installed because it is in `requirements.txt`.
**How I noticed:** Every `curl` returned status `000`, and the log said `gunicorn: not found`. The earlier "OK" printed by the script came from other commands, so it looked fine at a glance.
**Fix:** Re-ran the smoke test with `python run.py` (Flask's server). Recorded in TESTING.md that gunicorn/Docker were **not** exercised, so the claim is not overstated.

## 5. Verifying the tests actually test something
**Prompt/Action:** After all 29 tests passed on the first run, I did not trust them. I temporarily broke two protections (single-use check, lockout threshold) and re-ran the tests.
**Result:** 3 and 1 tests failed respectively, then the code was restored. This confirmed the tests guard the behaviour they claim to.

## 6. Concurrency
**Prompt/Action:** Asked for tests where multiple customers redeem the same code and claim the last reward at the same instant (threads released by a barrier).
**Result:** Exactly one winner each time; losing claimants were not charged. This is the evidence behind the "no double redemption" claim.
