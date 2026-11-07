"""Code generation / validation and fraud-control helpers."""
import hashlib
import hmac
import re
import secrets

from .db import now_str

# 31 unambiguous characters: no 0/O, 1/I/L. 31^12 ~ 7.9e17 possible payloads.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PAYLOAD_LEN = 12
CHECK_LEN = 2
CODE_LEN = PAYLOAD_LEN + CHECK_LEN


def _hmac(pepper: str, label: bytes, data: str) -> bytes:
    return hmac.new(pepper.encode(), label + data.encode(), hashlib.sha256).digest()


def _check_chars(payload: str, pepper: str) -> str:
    d = _hmac(pepper, b"check:", payload)
    return "".join(ALPHABET[d[i] % len(ALPHABET)] for i in range(CHECK_LEN))


def generate_code(pepper: str) -> str:
    payload = "".join(secrets.choice(ALPHABET) for _ in range(PAYLOAD_LEN))
    return payload + _check_chars(payload, pepper)


def format_code(code: str) -> str:
    """ABCDEFGHJKMNPQ -> ABCD-EFGH-JKMN-PQ (easier to read / print)."""
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def normalize(user_input: str) -> str:
    return re.sub(r"[\s\-]", "", (user_input or "").upper())


def is_well_formed(code: str, pepper: str) -> bool:
    """Cheap offline check (length, alphabet, checksum). Rejects typos and
    random guesses without touching the database."""
    if len(code) != CODE_LEN or any(ch not in ALPHABET for ch in code):
        return False
    return hmac.compare_digest(_check_chars(code[:PAYLOAD_LEN], pepper), code[PAYLOAD_LEN:])


def hash_code(code: str, pepper: str) -> str:
    """What we store. A database leak does not reveal usable codes."""
    return _hmac(pepper, b"hash:", code).hex()


# ---- security events / rate limiting ----------------------------------------

REDEEM_FAIL_KINDS = (
    "redeem_malformed", "redeem_invalid", "redeem_used", "redeem_voided", "redeem_expired",
)


def log_event(db, kind, customer_id=None, ip=None, detail=None):
    db.execute(
        "INSERT INTO security_events (kind, customer_id, ip, detail, created_at) VALUES (?,?,?,?,?)",
        (kind, customer_id, ip, detail, now_str()),
    )


def count_events(db, kinds, window_minutes, customer_id=None, ip=None) -> int:
    marks = ",".join("?" * len(kinds))
    sql = f"SELECT COUNT(*) FROM security_events WHERE kind IN ({marks}) AND created_at >= ?"
    args = [*kinds, now_str(offset_minutes=-window_minutes)]
    if customer_id is not None:
        sql += " AND customer_id = ?"
        args.append(customer_id)
    if ip is not None:
        sql += " AND ip = ?"
        args.append(ip)
    return db.execute(sql, args).fetchone()[0]


def redeem_locked(db, cfg, customer_id, ip) -> bool:
    w = cfg["LOCKOUT_WINDOW_MINUTES"]
    if count_events(db, REDEEM_FAIL_KINDS, w, customer_id=customer_id) >= cfg["MAX_FAILED_ATTEMPTS_PER_USER"]:
        return True
    if ip and count_events(db, REDEEM_FAIL_KINDS, w, ip=ip) >= cfg["MAX_FAILED_ATTEMPTS_PER_IP"]:
        return True
    return False


def login_locked(db, cfg, ip) -> bool:
    if not ip:
        return False
    return count_events(db, ("login_fail",), cfg["LOCKOUT_WINDOW_MINUTES"], ip=ip) >= 10
