# Assumptions

Each entry is a gap in the brief, the option chosen and why.

## Proof of purchase
| # | Gap | Decision | Why |
|---|---|---|---|
| 1 | How does a customer prove they bought? | A unique code is printed **inside** each sealed box (under the flap, scratch-off or tamper-evident sticker). Possessing a valid code is the proof. | Cheapest option for a factory: it is just a printing job, no hardware, and the code is only visible after the box is opened. |
| 2 | Alternatives (receipt upload, QR to a website, serial numbers) | Not used. A QR code can encode the same code but is not required. | Receipts need manual review or OCR. Sequential serial numbers are guessable. |
| 3 | One code = one box = one redemption | Yes, strictly single-use. | Simple, auditable, and the strongest anti-reuse rule. |
| 4 | Points per box | Set per **product** (e.g. 20 pts for 500g biscuits) and copied at redemption time. | The owner can reward higher-margin products more. |
| 5 | Code expiry | Per batch, default 365 days (`CODE_VALID_DAYS`). | Limits how long a leaked or stockpiled code stays useful. |
| 6 | Code format | 14 characters from a 31-character alphabet with no 0/O/1/I/L, grouped `XXXX-XXXX-XXXX-XX`. The last 2 characters are an HMAC checksum. Input is case- and dash-insensitive. | Avoids misreading when printed. 12 random characters give about 7.9 × 10^17 combinations, so guessing is impractical. The checksum rejects typos offline. |

## Fraud and reuse
| # | Gap | Decision | Why |
|---|---|---|---|
| 7 | Storing codes | Only an HMAC-SHA256 hash (keyed with `CODE_PEPPER`) is stored. | A stolen database does not reveal usable codes. Trade-off: plaintext is shown once at generation and cannot be recovered later. |
| 8 | Brute-force guessing | After 5 failed attempts per account (or 20 per IP) in 15 minutes, redemption is locked. Thresholds are configurable. | Combined with the large code space this makes guessing infeasible. |
| 9 | Race conditions / double spend | Redemption and reward claims use `BEGIN IMMEDIATE` transactions plus conditional `UPDATE ... WHERE status='unused'` / `points_balance >= cost`. | Two simultaneous requests cannot both win. Covered by concurrency tests. |
| 10 | Compromised batch (stolen labels, print error) | The owner can void a batch. Unused codes die immediately, redeemed ones are kept. | Provides a recall mechanism. |
| 11 | Suspicious users | Failures are logged and shown per customer. The owner decides whether to suspend. There is no automatic ban. | Avoids punishing honest typos or a customer who bought a box that was already tampered with. |
| 12 | Multiple accounts | Not prevented. One person can register several emails. | Each still needs a real unique code, so the points earned are legitimate. A true fix needs phone/ID verification, which is out of scope. |
| 13 | Codes redeemed from a box that was never bought (retail theft or shop staff opening boxes) | Out of scope for software. | A code proves possession of the box contents, not payment. Tamper-evident printing is the mitigation. |

## Accounts and access
| # | Gap | Decision | Why |
|---|---|---|---|
| 14 | Customer identity | Email + password, no verification email. | Keeps the demo self-contained with no email service. |
| 15 | Admin accounts | One admin created from `.env` on first start. No UI for multiple admins. | The brief has a single factory owner. |
| 16 | Sessions | Signed, HttpOnly, SameSite=Lax cookies. State-changing endpoints accept JSON only. | Cheap CSRF protection without tokens. Set `COOKIE_SECURE=1` under HTTPS. |

## Rewards
| # | Gap | Decision | Why |
|---|---|---|---|
| 17 | What is a reward? | A catalogue item with a points cost and optional stock. Claiming deducts points immediately and creates a **pending** claim. The owner fulfils it manually (ships it offline). | The factory handles physical delivery its own way. |
| 18 | Cancelled claims | Points are refunded and stock is restored. | Fair to the customer. The ledger keeps an audit trail. |
| 19 | Point expiry, tiers, referrals | Not implemented. | Not requested. The ledger table makes them easy to add. |
| 20 | Accounting | `point_ledger` is append-only. `points_balance` is a cached total kept in sync in the same transaction. | Auditable. A test checks that the ledger sums to the balance. |

## Technical
| # | Gap | Decision | Why |
|---|---|---|---|
| 21 | Scale | Up to tens of thousands of codes and a few hundred customers on one server. | A single factory. SQLite in WAL mode is enough. |
| 22 | Batch size | Max 10,000 codes per batch. | Keeps the request and the single transaction small. |
| 23 | Time | All timestamps are UTC. | Avoids timezone bugs. |
| 24 | Currency / money | No money handled. Points only. | Out of scope. |

## Known limitations
- No email verification, password reset, or multi-admin management.
- IP-based throttling uses `request.remote_addr`; behind a proxy set `NUM_PROXIES` correctly or all users appear to share one IP.
- SQLite is single-node. A move to PostgreSQL would require porting `app/db.py` and the SQL (mostly standard).
- Plaintext codes appear once in the generation response and in the CSV the owner downloads. Handling that file securely is the owner's responsibility.
- The frontend was checked for JavaScript syntax and exercised through the API, but not tested in real browsers.
