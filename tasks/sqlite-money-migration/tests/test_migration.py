import os
import shutil
import sqlite3
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pytest

WS = Path(os.environ["WORKSPACE"])
HERE = Path(__file__).resolve().parent
PYTHON = os.environ.get("PYTHON", "python3")


def expected_cents(raw):
    """Character-level parser, written independently of any regex solution."""
    if raw is None:
        return None
    s = raw.strip()
    neg = False
    if len(s) >= 2 and s[0] == "(" and s[-1] == ")":
        neg, s = True, s[1:-1]
    elif s[:1] == "-":
        neg, s = True, s[1:]
    if s[:1] == "$":
        s = s[1:]
    elif s[:3].lower() == "usd":
        s = s[3:]
    s = s.lstrip(" ")
    whole, dot, frac = s.partition(".")
    if dot and not (1 <= len(frac) <= 2 and frac.isdigit()):
        return "bad"
    if not whole or not all(c.isdigit() or c == "," for c in whole) or not whole[0].isdigit():
        return "bad"
    if "," in whole:
        groups = whole.split(",")
        if not (1 <= len(groups[0]) <= 3) or any(len(g) != 3 for g in groups[1:]):
            return "bad"
    try:
        value = Decimal(whole.replace(",", "") + (dot + frac if dot else ""))
    except InvalidOperation:
        return "bad"
    cents = int(value * 100)
    return -cents if neg else cents


def state(db):
    con = sqlite3.connect(db)
    try:
        orders = con.execute("SELECT id, customer, amount, created_at, amount_cents FROM orders ORDER BY id").fetchall()
        errors = con.execute("SELECT order_id, raw FROM migration_errors ORDER BY order_id").fetchall()
        idx = con.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_orders_amount_cents'").fetchone()
        cols = [(r[1], r[2].upper()) for r in con.execute("PRAGMA table_info(orders)")]
        return orders, errors, idx, cols
    finally:
        con.close()


def run_migration(db):
    r = subprocess.run([PYTHON, str(WS / "migrate.py"), str(db)], cwd=WS, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.fixture(scope="module")
def pristine_rows():
    con = sqlite3.connect(HERE / "pristine.db")
    rows = con.execute("SELECT id, customer, amount, created_at FROM orders ORDER BY id").fetchall()
    con.close()
    return rows


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "copy.db"
    shutil.copy(HERE / "pristine.db", db)
    run_migration(db)
    return db


def check_state(db, pristine_rows):
    orders, errors, idx, cols = state(db)
    assert ("amount_cents", "INTEGER") in cols
    assert idx is not None and "amount_cents" in idx[0]
    assert [o[:4] for o in orders] == pristine_rows, "existing data was changed"
    want_errors, wrong = [], []
    for oid, _, raw, _, got in orders:
        exp = expected_cents(raw)
        if exp == "bad":
            want_errors.append((oid, raw))
            exp = None
        if got != exp:
            wrong.append((oid, raw, got, exp))
    assert not wrong, f"{len(wrong)} wrong amount_cents, e.g. (id, raw, got, expected) {wrong[:4]}"
    assert errors == want_errors


def test_migrate_script_on_fresh_copy(fresh, pristine_rows):
    check_state(fresh, pristine_rows)


def test_second_run_is_a_no_op(fresh, pristine_rows):
    before = state(fresh)
    run_migration(fresh)
    assert state(fresh) == before


def test_workspace_database_was_migrated(pristine_rows):
    check_state(WS / "app.db", pristine_rows)


def test_failure_leaves_database_untouched(tmp_path, pristine_rows):
    """A database locked by another writer makes the migration fail; nothing may be half applied."""
    db = tmp_path / "locked.db"
    shutil.copy(HERE / "pristine.db", db)
    holder = sqlite3.connect(db, isolation_level=None, timeout=0)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        r = subprocess.run([PYTHON, str(WS / "migrate.py"), str(db)], cwd=WS, capture_output=True, text=True,
                           timeout=60)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    con = sqlite3.connect(db)
    cols = {row[1] for row in con.execute("PRAGMA table_info(orders)")}
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    if r.returncode == 0:
        # the script waited for the lock and then succeeded; that is fine too
        check_state(db, pristine_rows)
    else:
        assert "amount_cents" not in cols and "migration_errors" not in tables
