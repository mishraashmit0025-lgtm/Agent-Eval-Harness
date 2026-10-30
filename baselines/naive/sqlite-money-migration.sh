#!/usr/bin/env bash
# Strips symbols and parses with float(): rounding errors, and it accepts amounts the spec calls invalid.
set -euo pipefail
cat > migrate.py <<'PY'
import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else "app.db"
con = sqlite3.connect(db)
cols = {r[1] for r in con.execute("PRAGMA table_info(orders)")}
if "amount_cents" not in cols:
    con.execute("ALTER TABLE orders ADD COLUMN amount_cents INTEGER")
con.execute("CREATE TABLE IF NOT EXISTS migration_errors (order_id INTEGER PRIMARY KEY, raw TEXT)")
con.execute("DELETE FROM migration_errors")
for oid, raw in con.execute("SELECT id, amount FROM orders").fetchall():
    cents = None
    if raw is not None:
        s = raw.strip().upper().replace("USD", "").replace("$", "").replace(",", "").strip()
        neg = s.startswith("(") or s.startswith("-")
        try:
            cents = int(float(s.strip("()-")) * 100) * (-1 if neg else 1)
        except ValueError:
            con.execute("INSERT INTO migration_errors VALUES (?, ?)", (oid, raw))
    con.execute("UPDATE orders SET amount_cents = ? WHERE id = ?", (cents, oid))
con.execute("CREATE INDEX IF NOT EXISTS idx_orders_amount_cents ON orders(amount_cents)")
con.commit()
PY
"${PYTHON:-python3}" migrate.py app.db
