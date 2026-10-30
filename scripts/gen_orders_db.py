"""Builds the orders database for tasks/sqlite-money-migration (seeded).

The same file goes to environment/app.db (what the agent migrates) and
tests/pristine.db (what the verifier migrates again with the agent's script)."""

import random
import shutil
import sqlite3
from pathlib import Path

rng = random.Random(42)
task = Path(__file__).resolve().parent.parent / "tasks/sqlite-money-migration"
db_path = task / "environment/app.db"
db_path.unlink(missing_ok=True)


def money(cents):
    neg, cents = cents < 0, abs(cents)
    whole, frac = divmod(cents, 100)
    style = rng.random()
    if style < 0.25:
        s = f"${whole:,}.{frac:02d}"
    elif style < 0.45:
        s = f"{whole}.{frac:02d}"
    elif style < 0.55:
        s = f"USD {whole}.{frac:02d}" if frac else f"USD {whole}"
    elif style < 0.65:
        s = f"{whole}.{frac // 10}" if frac % 10 == 0 else f"{whole}.{frac:02d}"
    elif style < 0.75:
        s = f"  {whole:,}.{frac:02d} "
    elif style < 0.82:
        s = f"usd{whole}" if frac == 0 else f"usd {whole}.{frac:02d}"
    else:
        s = str(whole) if frac == 0 else f"{whole}.{frac:02d}"
    if neg:
        s = f"({s.strip()})" if rng.random() < 0.5 else "-" + s.strip()
    return s


BAD = ["€12.00", "12.345", "1.2.3", "", "N/A", "12,34.00", "$-5", "1,0000", "--4", "$ 1e3", "USD", "(5", "5)",
       "0x1F", "12.", ".50"]
rows = []
for i in range(1, 1201):
    r = rng.random()
    if r < 0.04:
        amount = rng.choice(BAD)
    elif r < 0.06:
        amount = None
    else:
        cents = rng.choice([rng.randint(0, 999), rng.randint(100, 99_999), rng.randint(100_000, 250_000_000)])
        if rng.random() < 0.05:
            cents = -cents
        if rng.random() < 0.2:
            cents -= cents % 100
        amount = money(cents)
    rows.append((i, f"cust{rng.randint(1, 300):04d}", amount, f"2026-{rng.randint(1, 9):02d}-{rng.randint(1, 28):02d}"))

con = sqlite3.connect(db_path)
con.executescript("""
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer TEXT NOT NULL, amount TEXT, created_at TEXT NOT NULL);
CREATE INDEX idx_orders_customer ON orders(customer);
""")
con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", rows)
con.commit()
con.execute("VACUUM")
con.close()
shutil.copy(db_path, task / "tests/pristine.db")
print(f"{len(rows)} orders, sample: {[r[2] for r in rows[:12]]}")
