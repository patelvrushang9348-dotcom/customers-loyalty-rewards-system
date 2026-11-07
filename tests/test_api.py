"""Run with:  python -m unittest discover -s tests -v"""
import os
import tempfile
import threading
import unittest

from app import create_app
from app.security import (generate_code, format_code, hash_code, is_well_formed, normalize)

PEPPER = "test-pepper-test-pepper"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = {
            "TESTING": True, "DATABASE_PATH": os.path.join(self.tmp.name, "t.db"),
            "SECRET_KEY": "test-secret", "CODE_PEPPER": PEPPER,
            "ADMIN_USERNAME": "owner", "ADMIN_PASSWORD": "adminpass123",
            "MAX_FAILED_ATTEMPTS_PER_USER": 5, "MAX_FAILED_ATTEMPTS_PER_IP": 20,
            "LOCKOUT_WINDOW_MINUTES": 15, "CODE_VALID_DAYS": 365,
        }
        self.app = create_app(self.cfg)
        self.admin = self.app.test_client()
        r = self.admin.post("/api/admin/login", json={"username": "owner", "password": "adminpass123"})
        self.assertEqual(r.status_code, 200)

    def tearDown(self):
        self.tmp.cleanup()

    # helpers
    def new_customer(self, email="a@example.com", name="Asha"):
        c = self.app.test_client()
        r = c.post("/api/register", json={"email": email, "name": name, "password": "password123"})
        self.assertEqual(r.status_code, 201, r.json)
        return c

    def make_product(self, sku="SKU1", points=10):
        r = self.admin.post("/api/admin/products", json={"name": "Biscuits " + sku, "sku": sku, "points": points})
        self.assertEqual(r.status_code, 201, r.json)
        return r.json["id"]

    def make_batch(self, pid, qty=5, **extra):
        r = self.admin.post("/api/admin/batches", json={"product_id": pid, "quantity": qty, **extra})
        self.assertEqual(r.status_code, 201, r.json)
        return r.json

    def make_reward(self, cost=10, stock=None):
        r = self.admin.post("/api/admin/rewards", json={"name": "Mug", "points_cost": cost, "stock": stock})
        self.assertEqual(r.status_code, 201, r.json)
        return r.json["id"]


class CodeHelperTests(unittest.TestCase):
    def test_generated_codes_validate_and_are_unique(self):
        codes = {generate_code(PEPPER) for _ in range(2000)}
        self.assertEqual(len(codes), 2000)
        self.assertTrue(all(is_well_formed(c, PEPPER) for c in codes))

    def test_checksum_rejects_typos_and_wrong_pepper(self):
        c = generate_code(PEPPER)
        bad = ("A" if c[0] != "A" else "B") + c[1:]
        self.assertFalse(is_well_formed(bad, PEPPER))
        self.assertFalse(is_well_formed(c, "another-pepper-entirely"))
        self.assertFalse(is_well_formed(c[:-1], PEPPER))

    def test_normalize_accepts_lowercase_and_dashes(self):
        c = generate_code(PEPPER)
        self.assertEqual(normalize(format_code(c).lower() + " "), c)

    def test_hash_is_not_plaintext_and_is_pepper_dependent(self):
        c = generate_code(PEPPER)
        self.assertNotIn(c, hash_code(c, PEPPER))
        self.assertNotEqual(hash_code(c, PEPPER), hash_code(c, "other-pepper-other"))


class AuthTests(Base):
    def test_duplicate_email_and_validation(self):
        self.new_customer()
        c = self.app.test_client()
        self.assertEqual(c.post("/api/register", json={"email": "a@example.com", "name": "X", "password": "password123"}).status_code, 409)
        self.assertEqual(c.post("/api/register", json={"email": "bad", "name": "X", "password": "password123"}).status_code, 400)
        self.assertEqual(c.post("/api/register", json={"email": "b@example.com", "name": "X", "password": "short"}).status_code, 400)

    def test_login_and_protected_routes(self):
        anon = self.app.test_client()
        self.assertEqual(anon.get("/api/me").status_code, 401)
        self.assertEqual(anon.post("/api/redeem", json={"code": "x"}).status_code, 401)
        self.new_customer()
        c = self.app.test_client()
        self.assertEqual(c.post("/api/login", json={"email": "a@example.com", "password": "nope"}).status_code, 401)
        self.assertEqual(c.post("/api/login", json={"email": "a@example.com", "password": "password123"}).status_code, 200)

    def test_customer_cannot_use_admin_api(self):
        c = self.new_customer()
        self.assertEqual(c.get("/api/admin/stats").status_code, 401)
        self.assertEqual(c.post("/api/admin/batches", json={"product_id": 1, "quantity": 1}).status_code, 401)

    def test_non_json_post_is_rejected(self):
        c = self.app.test_client()
        r = c.post("/api/login", data={"email": "a", "password": "b"})
        self.assertEqual(r.status_code, 400)

    def test_admin_login_throttle(self):
        c = self.app.test_client()
        for _ in range(10):
            c.post("/api/admin/login", json={"username": "owner", "password": "wrong"})
        r = c.post("/api/admin/login", json={"username": "owner", "password": "adminpass123"})
        self.assertEqual(r.status_code, 429)


class RedeemTests(Base):
    def setUp(self):
        super().setUp()
        self.pid = self.make_product(points=25)
        self.batch = self.make_batch(self.pid, qty=5)
        self.codes = self.batch["codes"]

    def test_valid_code_awards_points_once(self):
        c = self.new_customer()
        r = c.post("/api/redeem", json={"code": self.codes[0]})
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(r.json["points_earned"], 25)
        self.assertEqual(r.json["points_balance"], 25)
        again = c.post("/api/redeem", json={"code": self.codes[0]})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(c.get("/api/me").json["points_balance"], 25)

    def test_code_cannot_be_reused_by_another_customer(self):
        a, b = self.new_customer("a@example.com"), self.new_customer("b@example.com", "Bo")
        self.assertEqual(a.post("/api/redeem", json={"code": self.codes[1]}).status_code, 200)
        r = b.post("/api/redeem", json={"code": self.codes[1]})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(b.get("/api/me").json["points_balance"], 0)

    def test_input_formats_lowercase_no_dashes(self):
        c = self.new_customer()
        raw = self.codes[2].replace("-", "").lower()
        self.assertEqual(c.post("/api/redeem", json={"code": f"  {raw}  "}).status_code, 200)

    def test_fake_and_malformed_codes(self):
        c = self.new_customer()
        self.assertEqual(c.post("/api/redeem", json={"code": "HELLO"}).status_code, 400)
        # correct checksum but never issued -> well-formed yet not found
        ghost = generate_code(PEPPER)
        self.assertEqual(c.post("/api/redeem", json={"code": ghost}).status_code, 404)

    def test_codes_are_stored_hashed_only(self):
        import sqlite3
        conn = sqlite3.connect(self.cfg["DATABASE_PATH"])
        stored = [r[0] for r in conn.execute("SELECT code_hash FROM codes")]
        plain = {c.replace("-", "") for c in self.codes}
        self.assertTrue(plain.isdisjoint(stored))
        self.assertEqual(len(stored), 5)

    def test_lockout_after_repeated_failures_blocks_even_valid_code(self):
        c = self.new_customer()
        for _ in range(5):
            c.post("/api/redeem", json={"code": "WRONGCODE"})
        r = c.post("/api/redeem", json={"code": self.codes[0]})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(c.get("/api/me").json["points_balance"], 0)

    def test_voided_batch_codes_rejected(self):
        c = self.new_customer()
        self.assertEqual(self.admin.post(f"/api/admin/batches/{self.batch['batch_id']}/void").json["voided_codes"], 5)
        self.assertEqual(c.post("/api/redeem", json={"code": self.codes[0]}).status_code, 410)

    def test_void_keeps_already_redeemed_codes(self):
        c = self.new_customer()
        c.post("/api/redeem", json={"code": self.codes[0]})
        self.assertEqual(self.admin.post(f"/api/admin/batches/{self.batch['batch_id']}/void").json["voided_codes"], 4)
        self.assertEqual(c.get("/api/me").json["points_balance"], 25)

    def test_expired_code_rejected(self):
        import sqlite3
        conn = sqlite3.connect(self.cfg["DATABASE_PATH"])
        conn.execute("UPDATE batches SET expires_at='2000-01-01 00:00:00'")
        conn.commit()
        c = self.new_customer()
        self.assertEqual(c.post("/api/redeem", json={"code": self.codes[0]}).status_code, 410)

    def test_suspended_customer_cannot_redeem(self):
        c = self.new_customer()
        uid = c.get("/api/me").json["id"]
        self.admin.post(f"/api/admin/customers/{uid}/status", json={"status": "suspended"})
        self.assertEqual(c.post("/api/redeem", json={"code": self.codes[0]}).status_code, 403)

    def test_concurrent_redemption_of_one_code_succeeds_exactly_once(self):
        clients = [self.new_customer(f"u{i}@example.com", f"U{i}") for i in range(8)]
        results, barrier = [], threading.Barrier(len(clients))

        def go(cl):
            barrier.wait()
            results.append(cl.post("/api/redeem", json={"code": self.codes[3]}).status_code)

        threads = [threading.Thread(target=go, args=(cl,)) for cl in clients]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(results).count(200), 1, results)
        self.assertEqual(results.count(409), len(clients) - 1, results)
        total = sum(cl.get("/api/me").json["points_balance"] for cl in clients)
        self.assertEqual(total, 25)


class RewardTests(Base):
    def setUp(self):
        super().setUp()
        pid = self.make_product(points=30)
        self.codes = self.make_batch(pid, qty=3)["codes"]
        self.c = self.new_customer()
        for code in self.codes:
            self.c.post("/api/redeem", json={"code": code})      # 90 points

    def test_claim_deducts_points_and_creates_pending_claim(self):
        rid = self.make_reward(cost=50, stock=2)
        r = self.c.post(f"/api/rewards/{rid}/claim")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json["points_balance"], 40)
        self.assertEqual(self.admin.get("/api/admin/claims?status=pending").json[0]["reward"], "Mug")

    def test_cannot_overspend(self):
        rid = self.make_reward(cost=100)
        self.assertEqual(self.c.post(f"/api/rewards/{rid}/claim").status_code, 402)
        self.assertEqual(self.c.get("/api/me").json["points_balance"], 90)

    def test_out_of_stock_does_not_charge_points(self):
        rid = self.make_reward(cost=10, stock=0)
        self.assertEqual(self.c.post(f"/api/rewards/{rid}/claim").status_code, 409)
        self.assertEqual(self.c.get("/api/me").json["points_balance"], 90)

    def test_cancel_refunds_points_and_restocks(self):
        rid = self.make_reward(cost=50, stock=1)
        cid = self.c.post(f"/api/rewards/{rid}/claim").json["claim_id"]
        self.assertEqual(self.admin.post(f"/api/admin/claims/{cid}/status", json={"status": "cancelled"}).status_code, 200)
        self.assertEqual(self.c.get("/api/me").json["points_balance"], 90)
        self.assertEqual([r for r in self.admin.get("/api/admin/rewards").json if r["id"] == rid][0]["stock"], 1)
        # cannot change a finished claim again
        self.assertEqual(self.admin.post(f"/api/admin/claims/{cid}/status", json={"status": "fulfilled"}).status_code, 409)

    def test_concurrent_claims_do_not_oversell_last_item(self):
        rid = self.make_reward(cost=10, stock=1)
        others = [self.new_customer(f"z{i}@example.com", f"Z{i}") for i in range(4)]
        # give each 10 points via their own code
        pid2 = self.make_product(sku="SKU2", points=10)
        codes = self.make_batch(pid2, qty=4)["codes"]
        for cl, code in zip(others, codes):
            cl.post("/api/redeem", json={"code": code})
        results, barrier = [], threading.Barrier(len(others))

        def go(cl):
            barrier.wait()
            results.append(cl.post(f"/api/rewards/{rid}/claim").status_code)

        ts = [threading.Thread(target=go, args=(cl,)) for cl in others]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(results.count(201), 1, results)
        balances = sorted(cl.get("/api/me").json["points_balance"] for cl in others)
        self.assertEqual(balances, [0, 10, 10, 10])      # losers were not charged

    def test_ledger_matches_balance(self):
        rid = self.make_reward(cost=50)
        self.c.post(f"/api/rewards/{rid}/claim")
        ledger = self.c.get("/api/history").json["ledger"]
        self.assertEqual(sum(x["delta"] for x in ledger), self.c.get("/api/me").json["points_balance"])


class AdminTests(Base):
    def test_batch_validation(self):
        pid = self.make_product()
        for bad in ({"product_id": pid, "quantity": 0}, {"product_id": pid, "quantity": 10001},
                    {"product_id": 999, "quantity": 1}, {"quantity": 5}):
            self.assertIn(self.admin.post("/api/admin/batches", json=bad).status_code, (400, 404))

    def test_duplicate_sku_rejected(self):
        self.make_product("DUP")
        r = self.admin.post("/api/admin/products", json={"name": "x", "sku": "DUP", "points": 5})
        self.assertEqual(r.status_code, 409)

    def test_stats_and_fraud_log_reflect_activity(self):
        pid = self.make_product(points=10)
        codes = self.make_batch(pid, qty=4)["codes"]
        c = self.new_customer()
        c.post("/api/redeem", json={"code": codes[0]})
        c.post("/api/redeem", json={"code": codes[0]})          # reuse -> failure
        s = self.admin.get("/api/admin/stats").json
        self.assertEqual((s["codes_generated"], s["codes_redeemed"]), (4, 1))
        self.assertEqual(s["points_issued"], 10)
        self.assertEqual(s["failed_attempts_24h"], 1)
        kinds = {e["kind"] for e in self.admin.get("/api/admin/events").json}
        self.assertTrue({"redeem_ok", "redeem_used"} <= kinds)
        cust = self.admin.get("/api/admin/customers").json[0]
        self.assertEqual(cust["failures_7d"], 1)


if __name__ == "__main__":
    unittest.main()
