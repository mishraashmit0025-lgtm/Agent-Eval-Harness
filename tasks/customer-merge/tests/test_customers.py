import csv
import hashlib
import os
import re
from calendar import timegm
from pathlib import Path

import pytest

WS = Path(os.environ["WORKSPACE"])
INPUT_SHA = {"crm_export.csv": "795208e6d07ec48b335bcb1b94b6cc24eee0e61a673edf472fa3e48093827344", "billing_export.csv": "e94a1bfdf6f13461b334d85000c0b9eaf5b53c669f1e5aa0eac92dfe66ba1ed8"}


def to_epoch(stamp):
    """Parses both input formats by hand into UTC seconds, without datetime, to stay independent of the solver."""
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d) ?(?:Z|([+-])(\d\d):?(\d\d))", stamp.strip())
    assert m, stamp
    y, mo, d, h, mi, s = (int(x) for x in m.groups()[:6])
    local = timegm((y, mo, d, h, mi, s, 0, 0, 0))
    if m.group(7) is None:
        return local
    off = (int(m.group(8)) * 60 + int(m.group(9))) * 60
    return local - off if m.group(7) == "+" else local + off


def normalize(email):
    e = email.strip().lower()
    if "@" not in e:
        return None
    local, domain = e.split("@", 1)
    return local.split("+")[0] + "@" + domain


@pytest.fixture(scope="module")
def expected():
    recs = {}
    for fname, cols, rank in [("crm_export.csv", ("email", "name", "plan", "updated_at"), 0),
                              ("billing_export.csv", ("Email Address", "Full Name", "Plan", "Last Modified"), 1)]:
        with open(WS / fname, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = normalize(row[cols[0]])
                if not key:
                    continue
                cand = (to_epoch(row[cols[3]]), rank, row[cols[1]].strip(), row[cols[2]].strip())
                recs.setdefault(key, []).append(cand)
    out = {}
    for key, cands in recs.items():
        t, _, name, plan = max(cands, key=lambda c: (c[0], c[1]))
        out[key] = (name, plan, t)
    return out


@pytest.fixture(scope="module")
def rows():
    p = WS / "customers.csv"
    assert p.exists(), "customers.csv was not written"
    with open(p, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == ["email", "name", "plan", "updated_at"]
        return [r for r in reader if r]


def test_inputs_untouched():
    for name, sha in INPUT_SHA.items():
        assert hashlib.sha256((WS / name).read_bytes()).hexdigest() == sha, name


def test_one_row_per_customer(rows, expected):
    emails = [r[0] for r in rows]
    assert len(emails) == len(set(emails)), "duplicate customers"
    assert set(emails) == set(expected)


def test_sorted(rows):
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)


def test_timestamps_are_utc_z(rows):
    for r in rows:
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", r[3]), r


def test_latest_record_wins(rows, expected):
    wrong = []
    for email, name, plan, updated in rows:
        e_name, e_plan, e_t = expected[email]
        if (name, plan, to_epoch(updated)) != (e_name, e_plan, e_t):
            wrong.append(email)
    assert not wrong, f"{len(wrong)} customers kept the wrong record, e.g. {wrong[:3]}"
