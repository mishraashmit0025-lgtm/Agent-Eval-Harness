"""Generates the two input CSVs for tasks/customer-merge (seeded)."""

import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

rng = random.Random(7)
env = Path(__file__).resolve().parent.parent / "tasks/customer-merge/environment"
FIRST = ["Asha", "Ben", "Chen", "Dina", "Eli", "Farah", "Goran", "Hana", "Ivan", "Jia", "Kofi", "Lena", "Mateo", "Nia"]
LAST = ["Rao", "Smith", "Li", "Haddad", "Cohen", "Khan", "Petrov", "Sato", "Ivanova", "Wang", "Mensah", "Berg"]
PLANS = ["free", "pro", "team", "enterprise"]
OFFSETS = [timedelta(hours=h, minutes=m) for h, m in [(0, 0), (5, 30), (-5, 0), (-8, 0), (9, 0), (1, 0), (-3, -30)]]


def fmt_crm(dt_utc, off):
    return dt_utc.astimezone(timezone(off)).isoformat(timespec="seconds")


def fmt_billing(dt_utc, off):
    local = dt_utc.astimezone(timezone(off))
    return local.strftime("%Y-%m-%d %H:%M:%S %z")


def variant(email):
    local, domain = email.split("@")
    r = rng.random()
    if r < 0.3:
        return f"  {email.upper()} "
    if r < 0.55:
        return f"{local}+{rng.choice(['news', 'billing', 'x1'])}@{domain}"
    if r < 0.7:
        return email.title()
    return email


base = datetime(2026, 1, 1, tzinfo=timezone.utc)
people = []
for i in range(220):
    f, l = rng.choice(FIRST), rng.choice(LAST)
    people.append((f"{f}.{l}{i}@example.{rng.choice(['com', 'org', 'io'])}".lower(), f"{f} {l}"))

crm, billing = [], []
for email, name in people:
    t_crm = base + timedelta(minutes=rng.randint(0, 400_000))
    in_crm, in_billing = rng.random() < 0.8, rng.random() < 0.7
    if not (in_crm or in_billing):
        in_crm = True
    if in_crm:
        crm.append([variant(email), name, rng.choice(PLANS), fmt_crm(t_crm, rng.choice(OFFSETS))])
    if in_billing:
        r = rng.random()
        if r < 0.25:
            # the local clock time is later but the instant is earlier: offsets decide
            t_b = t_crm - timedelta(hours=2)
            off_c, off_b = timedelta(0), timedelta(hours=5, minutes=30)
            if in_crm:
                crm[-1][3] = fmt_crm(t_crm, off_c)
        elif r < 0.35:
            t_b, off_b = t_crm, rng.choice(OFFSETS)  # same instant: billing wins the tie
        else:
            t_b, off_b = t_crm + timedelta(minutes=rng.randint(-50_000, 50_000)), rng.choice(OFFSETS)
        billing.append([variant(email), name.upper() if rng.random() < 0.2 else name, rng.choice(PLANS),
                        fmt_billing(t_b, off_b)])

# a few rows with no usable email
crm += [["", "Ghost User", "free", "2026-02-01T00:00:00+00:00"], ["not-an-email", "Typo Tom", "pro",
                                                                    "2026-02-02T00:00:00+00:00"]]
billing += [["   ", "Blank Bill", "team", "2026-02-03 00:00:00 +0000"]]
# duplicates inside one file: the later one must win
dup_email, dup_name = people[3]
crm.append([dup_email.upper(), dup_name, "enterprise", "2026-12-31T23:00:00-01:00"])

rng.shuffle(crm)
rng.shuffle(billing)
with open(env / "crm_export.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["email", "name", "plan", "updated_at"])
    w.writerows(crm)
with open(env / "billing_export.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["Email Address", "Full Name", "Plan", "Last Modified"])
    w.writerows(billing)
print(len(crm), len(billing))
