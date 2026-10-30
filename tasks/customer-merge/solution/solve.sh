#!/usr/bin/env bash
set -euo pipefail
cat > /tmp/merge_$$.py <<'PY'
import csv
from datetime import datetime, timezone

def norm(email):
    e = email.strip().lower()
    if "@" not in e:
        return None
    local, _, domain = e.partition("@")
    return f"{local.split('+', 1)[0]}@{domain}"

best = {}
def offer(email, name, plan, when, source_rank):
    key = norm(email)
    if not key:
        return
    cand = (when, source_rank, name.strip(), plan.strip())
    if key not in best or cand[:2] > best[key][:2]:
        best[key] = cand

with open("crm_export.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        offer(r["email"], r["name"], r["plan"], datetime.fromisoformat(r["updated_at"]), 0)
with open("billing_export.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        when = datetime.strptime(r["Last Modified"], "%Y-%m-%d %H:%M:%S %z")
        offer(r["Email Address"], r["Full Name"], r["Plan"], when, 1)

with open("customers.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["email", "name", "plan", "updated_at"])
    for email in sorted(best):
        when, _, name, plan = best[email]
        w.writerow([email, name, plan, when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")])
PY
"${PYTHON:-python3}" /tmp/merge_$$.py
rm -f /tmp/merge_$$.py
