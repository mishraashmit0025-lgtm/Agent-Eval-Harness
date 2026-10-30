#!/usr/bin/env bash
set -euo pipefail
cat > migrate.py <<'PY'
"""Adds orders.amount_cents, parsed from the free-text amount column. Safe to rerun."""

import re
import sqlite3
import sys

AMOUNT = re.compile(r"(?:\$|usd)? *(\d+|\d{1,3}(?:,\d{3})+)(?:\.(\d{1,2}))?", re.IGNORECASE)


def to_cents(raw):
    s = raw.strip()
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    elif s.startswith("-"):
        neg, s = True, s[1:]
    m = AMOUNT.fullmatch(s)
    if not m:
        return None
    whole, frac = m.group(1).replace(",", ""), (m.group(2) or "").ljust(2, "0")
    cents = int(whole) * 100 + int(frac)
    return -cents if neg else cents


def migrate(path):
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        cols = {r[1] for r in con.execute("PRAGMA table_info(orders)")}
        if "amount_cents" not in cols:
            con.execute("ALTER TABLE orders ADD COLUMN amount_cents INTEGER")
        con.execute("CREATE TABLE IF NOT EXISTS migration_errors (order_id INTEGER PRIMARY KEY, raw TEXT)")
        con.execute("DELETE FROM migration_errors")
        updates, errors = [], []
        for oid, raw in con.execute("SELECT id, amount FROM orders").fetchall():
            cents = None if raw is None else to_cents(raw)
            if raw is not None and cents is None:
                errors.append((oid, raw))
            updates.append((cents, oid))
        con.executemany("UPDATE orders SET amount_cents = ? WHERE id = ?", updates)
        con.executemany("INSERT INTO migration_errors VALUES (?, ?)", errors)
        con.execute("CREATE INDEX IF NOT EXISTS idx_orders_amount_cents ON orders(amount_cents)")
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


if __name__ == "__main__":
    migrate(sys.argv[1] if len(sys.argv) > 1 else "app.db")
PY
"${PYTHON:-python3}" migrate.py app.db
