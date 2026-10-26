import glob
import sqlite3
import sys

if len(sys.argv) != 2:
    sys.exit("Usage: venv311\\Scripts\\python.exe reset_user.py you@example.com")

email = sys.argv[1].strip().lower()
SKIP = ("venv", "chroma", "site-packages", "result_cache", "node_modules")

paths = []
for pattern in ("**/*.db", "**/*.sqlite", "**/*.sqlite3"):
    paths += glob.glob(pattern, recursive=True)
paths = [p for p in paths if not any(k in p.lower() for k in SKIP)]
if not paths:
    sys.exit("No database file found. Run this from the project folder.")

found = []
for path in paths:
    con = sqlite3.connect(path)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
            joined = " ".join(cols).lower()
            if "email" in cols and ("password" in joined or "hash" in joined):
                n = con.execute(f'SELECT COUNT(*) FROM "{t}" WHERE lower(email) = ?', (email,)).fetchone()[0]
                if n:
                    found.append((path, t, n))
    finally:
        con.close()

if not found:
    sys.exit(f"No account with email {email} found in: {', '.join(paths)}")
for path, table, n in found:
    print(f"Found {n} account(s) for {email} in {path} (table '{table}')")
if input("Delete it so you can register again? Type yes: ").strip().lower() != "yes":
    sys.exit("Nothing changed.")
for path, table, _ in found:
    con = sqlite3.connect(path)
    with con:
        con.execute(f'DELETE FROM "{table}" WHERE lower(email) = ?', (email,))
    con.close()
print("Done. Open the Register tab and create the account again.")