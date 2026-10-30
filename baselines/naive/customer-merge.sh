#!/usr/bin/env bash
# Normalizes emails correctly but compares local wall-clock times, ignoring the UTC offsets.
set -euo pipefail
cat > /tmp/naive_$$.py <<'PY'
import csv
from datetime import datetime, timezone
best = {}
def offer(email, name, plan, stamp, rank):
    e = email.strip().lower()
    if "@" not in e:
        return
    local, domain = e.split("@", 1)
    key = local.split("+")[0] + "@" + domain
    when = datetime.fromisoformat(stamp.replace(" +", "+").replace(" -", "-").replace(" ", "T"))
    naive = when.replace(tzinfo=None)
    if key not in best or (naive, rank) > best[key][:2]:
        best[key] = (naive, rank, name.strip(), plan.strip(), when)
for r in csv.DictReader(open("crm_export.csv", newline="", encoding="utf-8")):
    offer(r["email"], r["name"], r["plan"], r["updated_at"], 0)
for r in csv.DictReader(open("billing_export.csv", newline="", encoding="utf-8")):
    offer(r["Email Address"], r["Full Name"], r["Plan"], r["Last Modified"], 1)
with open("customers.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["email", "name", "plan", "updated_at"])
    for k in sorted(best):
        _, _, name, plan, when = best[k]
        w.writerow([k, name, plan, when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")])
PY
"${PYTHON:-python3}" /tmp/naive_$$.py
rm -f /tmp/naive_$$.py
