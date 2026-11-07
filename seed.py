"""Create demo data: products, rewards and a batch of sample codes.

Usage: python seed.py        (writes demo_codes.txt with plain codes to try in the app)
"""
import app as appmod
import config
import db
from app import code_hash, new_code

PRODUCTS = [("CHOC", "Dark Chocolate Box (24 bars)", 120), ("TEA", "Herbal Tea Box (40 bags)", 60), ("BISC", "Butter Biscuit Box", 40)]
REWARDS = [("Factory cap", "Embroidered cap in factory colours", 300, 50),
           ("Free Tea Box", "One Herbal Tea Box, shipped free", 500, 30),
           ("Insulated bottle", "500 ml steel bottle", 900, 20),
           ("Family hamper", "Mixed hamper of our best sellers", 1800, 10)]


def main():
    app = appmod.create_app()
    conn = db.connect(app.config["DB_PATH"])
    if db.scalar(conn, "SELECT COUNT(*) FROM products"):
        print("Database already has data; skipping seed.")
        return
    admin = db.row(conn, "SELECT id FROM users WHERE role='admin'")
    for sku, name, pts in PRODUCTS:
        conn.execute("INSERT INTO products(sku,name,points) VALUES (?,?,?)", (sku, name, pts))
    for name, desc, cost, stock in REWARDS:
        conn.execute("INSERT INTO rewards(name,description,cost,stock) VALUES (?,?,?,?)", (name, desc, cost, stock))
    lines = []
    for pid, (sku, name, _) in enumerate(PRODUCTS, start=1):
        bid = conn.execute("INSERT INTO batches(product_id,quantity,note,created_by) VALUES (?,?,?,?)",
                           (pid, 5, "Demo batch", admin["id"] if admin else None)).lastrowid
        for i in range(1, 6):
            code, serial = new_code(), f"{sku}-{bid:04d}-{i:05d}"
            conn.execute("INSERT INTO codes(batch_id,serial,code_hash) VALUES (?,?,?)", (bid, serial, code_hash(code)))
            lines.append(f"{serial}\t{code}\t{name}")
    open(config.BASE_DIR / "demo_codes.txt", "w").write("\n".join(lines) + "\n")
    print(f"Seeded {len(PRODUCTS)} products, {len(REWARDS)} rewards, {len(lines)} demo codes -> demo_codes.txt")


if __name__ == "__main__":
    main()
