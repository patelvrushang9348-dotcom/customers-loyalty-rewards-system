"""Optional demo data: 2 products, 3 rewards, one batch of 20 codes saved to demo_codes.csv.
Usage: python scripts/seed_demo.py   (run after init_env.py)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app  # noqa: E402

app = create_app()
c = app.test_client()
cfg = app.config
assert c.post("/api/admin/login", json={"username": cfg["ADMIN_USERNAME"], "password": cfg["ADMIN_PASSWORD"]}).status_code == 200, \
    "Admin login failed. Did the admin already exist with a different password?"
pids = []
for name, sku, pts in [("Choco Biscuits 500g", "CB-500", 20), ("Salted Crackers 250g", "SC-250", 10)]:
    r = c.post("/api/admin/products", json={"name": name, "sku": sku, "points": pts})
    pids.append(r.json.get("id"))
for name, desc, cost, stock in [("Branded mug", "Ceramic, 300ml", 60, 50), ("Tote bag", "Cotton", 100, 30), ("Free box of biscuits", "Any 500g box", 150, None)]:
    c.post("/api/admin/rewards", json={"name": name, "description": desc, "points_cost": cost, "stock": stock})
if pids[0]:
    r = c.post("/api/admin/batches", json={"product_id": pids[0], "quantity": 20, "note": "demo batch"})
    with open("demo_codes.csv", "w") as f:
        f.write("code\n" + "\n".join(r.json["codes"]) + "\n")
    print("Wrote demo_codes.csv (20 sample codes worth 20 points each). Do NOT commit it.")
print("Demo data ready.")
