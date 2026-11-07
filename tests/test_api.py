"""Automated tests. Run: python -m unittest discover -s tests -v"""
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(ADMIN_EMAIL="owner@test.com", ADMIN_PASSWORD="owner-pass-123", CODE_PEPPER="test-pepper")

import app as appmod  # noqa: E402
import db  # noqa: E402

H = {"X-Requested-With": "fetch"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = appmod.create_app(os.path.join(self.tmp.name, "t.db"))
        self.app.testing = True
        self.admin = self.client()
        self.post(self.admin, "/api/login", email="owner@test.com", password="owner-pass-123")
        self.pid = self.post(self.admin, "/api/admin/products", sku="CHOC", name="Chocolate", points=100) and 1

    def tearDown(self):
        self.tmp.cleanup()

    def client(self):
        return self.app.test_client()

    def post(self, c, url, **body):
        return c.post(url, json=body, headers=H)

    def customer(self, email="a@test.com"):
        c = self.client()
        r = self.post(c, "/api/register", email=email, name="Cust", password="password123")
        self.assertEqual(r.status_code, 201, r.json)
        return c

    def batch(self, qty=3):
        r = self.post(self.admin, "/api/admin/batches", product_id=self.pid, quantity=qty)
        self.assertEqual(r.status_code, 201, r.json)
        return r.json

    def balance(self, c):
        return c.get("/api/me").json["user"]["points"]


class RedeemTests(Base):
    def test_valid_code_awards_points_once(self):
        code = self.batch()["codes"][0]["code"]
        c = self.customer()
        r = self.post(c, "/api/codes/redeem", code=code)
        self.assertEqual((r.status_code, r.json["points_added"]), (200, 100))
        self.assertEqual(self.balance(c), 100)

    def test_code_input_is_forgiving_about_case_and_dashes(self):
        code = self.batch()["codes"][0]["code"]
        r = self.post(self.customer(), "/api/codes/redeem", code=code.lower().replace("-", " "))
        self.assertEqual(r.status_code, 200)

    def test_same_user_cannot_reuse_code(self):
        code = self.batch()["codes"][0]["code"]
        c = self.customer()
        self.post(c, "/api/codes/redeem", code=code)
        r = self.post(c, "/api/codes/redeem", code=code)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.balance(c), 100)

    def test_other_user_cannot_reuse_code(self):
        code = self.batch()["codes"][0]["code"]
        self.post(self.customer("a@test.com"), "/api/codes/redeem", code=code)
        b = self.customer("b@test.com")
        r = self.post(b, "/api/codes/redeem", code=code)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.balance(b), 0)

    def test_unknown_code_rejected(self):
        r = self.post(self.customer(), "/api/codes/redeem", code="AAAA-BBBB-CCCC")
        self.assertEqual(r.status_code, 404)

    def test_voided_batch_rejected(self):
        b = self.batch()
        self.assertEqual(self.post(self.admin, f"/api/admin/batches/{b['batch_id']}/void").json["cancelled"], 3)
        r = self.post(self.customer(), "/api/codes/redeem", code=b["codes"][0]["code"])
        self.assertEqual(r.status_code, 410)

    def test_requires_login(self):
        r = self.post(self.client(), "/api/codes/redeem", code="AAAA-BBBB-CCCC")
        self.assertEqual(r.status_code, 401)

    def test_lockout_after_repeated_wrong_codes(self):
        code = self.batch()["codes"][0]["code"]
        c = self.customer()
        for _ in range(5):
            self.assertEqual(self.post(c, "/api/codes/redeem", code="ZZZZ-ZZZZ-ZZZZ").status_code, 404)
        self.assertEqual(self.post(c, "/api/codes/redeem", code=code).status_code, 429)  # even a valid code is blocked
        self.assertEqual(self.balance(c), 0)

    def test_codes_stored_hashed_not_plain(self):
        code = self.batch()["codes"][0]["code"]
        conn = db.connect(self.app.config["DB_PATH"])
        stored = [r[0] for r in conn.execute("SELECT code_hash FROM codes")]
        self.assertNotIn(code, stored)
        self.assertNotIn(appmod.normalize(code), stored)
        self.assertTrue(all(len(h) == 64 for h in stored))

    def test_race_condition_only_one_winner(self):
        code = self.batch()["codes"][0]["code"]
        clients = [self.customer(f"u{i}@test.com") for i in range(8)]
        results = []

        def go(c):
            results.append(self.post(c, "/api/codes/redeem", code=code).status_code)

        threads = [threading.Thread(target=go, args=(c,)) for c in clients]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(results), [200] + [409] * 7)
        self.assertEqual(sum(self.balance(c) for c in clients), 100)


class RewardTests(Base):
    def setUp(self):
        super().setUp()
        self.post(self.admin, "/api/admin/rewards", name="Cap", cost=150, stock=1)

    def earn(self, c, n):
        for code in [x["code"] for x in self.batch(n)["codes"]]:
            self.post(c, "/api/codes/redeem", code=code)

    def test_claim_deducts_points(self):
        c = self.customer()
        self.earn(c, 2)
        r = self.post(c, "/api/rewards/1/claim")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.balance(c), 50)

    def test_cannot_claim_without_enough_points(self):
        c = self.customer()
        self.earn(c, 1)
        self.assertEqual(self.post(c, "/api/rewards/1/claim").status_code, 409)
        self.assertEqual(self.balance(c), 100)

    def test_out_of_stock(self):
        a, b = self.customer("a@test.com"), self.customer("b@test.com")
        self.earn(a, 2)
        self.earn(b, 2)
        self.assertEqual(self.post(a, "/api/rewards/1/claim").status_code, 201)
        self.assertEqual(self.post(b, "/api/rewards/1/claim").status_code, 409)
        self.assertEqual(self.balance(b), 200)

    def test_rejected_claim_refunds_points_and_stock(self):
        c = self.customer()
        self.earn(c, 2)
        self.post(c, "/api/rewards/1/claim")
        self.assertEqual(self.post(self.admin, "/api/admin/claims/1", status="rejected").status_code, 200)
        self.assertEqual(self.balance(c), 200)
        self.assertEqual(c.get("/api/rewards").json["items"][0]["stock"], 1)
        self.assertEqual(self.post(self.admin, "/api/admin/claims/1", status="fulfilled").status_code, 409)


class SecurityTests(Base):
    def test_customer_cannot_use_admin_api(self):
        c = self.customer()
        self.assertEqual(c.get("/api/admin/stats").status_code, 403)
        self.assertEqual(self.post(c, "/api/admin/batches", product_id=1, quantity=1).status_code, 403)

    def test_anonymous_cannot_use_admin_api(self):
        self.assertEqual(self.client().get("/api/admin/stats").status_code, 401)

    def test_csrf_header_required_for_writes(self):
        r = self.client().post("/api/login", json={"email": "x@y.com", "password": "x"})
        self.assertEqual(r.status_code, 403)

    def test_blocked_user_is_signed_out(self):
        c = self.customer()
        self.post(self.admin, "/api/admin/customers/2/block", blocked=True)
        self.assertIsNone(c.get("/api/me").json["user"])
        r = self.post(self.client(), "/api/login", email="a@test.com", password="password123")
        self.assertEqual(r.status_code, 401)

    def test_registration_validation(self):
        c = self.client()
        self.assertEqual(self.post(c, "/api/register", email="bad", name="x", password="password123").status_code, 400)
        self.assertEqual(self.post(c, "/api/register", email="a@b.com", name="x", password="short").status_code, 400)

    def test_duplicate_email_rejected(self):
        self.customer("dup@test.com")
        r = self.post(self.client(), "/api/register", email="DUP@test.com", name="x", password="password123")
        self.assertEqual(r.status_code, 409)

    def test_batch_size_limit(self):
        self.assertEqual(self.post(self.admin, "/api/admin/batches", product_id=1, quantity=999999).status_code, 400)


class AdminTests(Base):
    def test_stats_and_alerts(self):
        b = self.batch(2)
        c = self.customer()
        self.post(c, "/api/codes/redeem", code=b["codes"][0]["code"])
        s = self.admin.get("/api/admin/stats").json
        self.assertEqual((s["codes_total"], s["codes_redeemed"], s["points_issued"]), (2, 1, 100))
        self.assertEqual(len(s["daily"]), 14)
        other = self.customer("b@test.com")
        for _ in range(3):
            self.post(other, "/api/codes/redeem", code=b["codes"][0]["code"])
        a = self.admin.get("/api/admin/alerts").json
        self.assertEqual(a["users"][0]["email"], "b@test.com")
        self.assertEqual(a["shared_codes"][0]["tries"], 3)

    def test_audit_trail_records_admin_actions(self):
        self.batch(1)
        actions = [x["action"] for x in self.admin.get("/api/admin/alerts").json["audit"]]
        self.assertIn("batch.create", actions)


if __name__ == "__main__":
    unittest.main()
