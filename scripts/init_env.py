"""Generate a .env with strong random secrets.  Usage: python scripts/init_env.py"""
import os
import secrets
import shutil
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
target, example = os.path.join(root, ".env"), os.path.join(root, ".env.example")
if os.path.exists(target):
    sys.exit(".env already exists; not overwriting.")
admin_pw = secrets.token_urlsafe(12)
text = open(example, encoding="utf-8").read()
text = text.replace("SECRET_KEY=change-me-long-random-string", f"SECRET_KEY={secrets.token_hex(32)}")
text = text.replace("CODE_PEPPER=change-me-another-long-random-string", f"CODE_PEPPER={secrets.token_hex(32)}")
text = text.replace("ADMIN_PASSWORD=change-me-strong-password", f"ADMIN_PASSWORD={admin_pw}")
open(target, "w", encoding="utf-8").write(text)
print("Created .env")
print(f"Admin login -> username: owner   password: {admin_pw}")
print("Back up CODE_PEPPER somewhere safe: without it printed codes stop working.")
