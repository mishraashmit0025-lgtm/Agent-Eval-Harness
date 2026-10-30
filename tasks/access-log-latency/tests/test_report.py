import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

import pytest

WS = Path(os.environ["WORKSPACE"])
LOG_SHA256 = "f6c31cd87b5779c948204b4ebf65a17270b20b9945f7a7a8c21a6add070a6c14"


def parse(line):
    """Independent parser: splits on the quoted request instead of using one regex."""
    try:
        head, request, tail = line.split('"')
    except ValueError:
        return None
    hf = head.split()
    if len(hf) != 5 or hf[1:3] != ["-", "-"] or not (hf[3].startswith("[") and hf[4].endswith("]")):
        return None
    rf = request.split(" ")
    if len(rf) != 3 or not rf[0].isalpha() or not rf[0].isupper() or not rf[2].startswith("HTTP/"):
        return None
    tf = tail.split()
    if len(tf) != 3 or len(tf[0]) != 3 or not tf[0].isdigit() or not (tf[1].isdigit() or tf[1] == "-"):
        return None
    try:
        latency = float(tf[2])
    except ValueError:
        return None
    if not tail.startswith(" ") or not tf[2][0].isdigit():
        return None
    path = rf[1].partition("?")[0]
    path = path.rstrip("/") or "/"
    path = "/".join(":id" if s.isdigit() else s for s in path.split("/"))
    return f"{rf[0]} {path}", int(tf[0]), latency * 1000


def nearest_rank(vals, p):
    vals = sorted(vals)
    k = -(-p * len(vals) // 100)  # ceil without floats
    return vals[max(k, 1) - 1]


@pytest.fixture(scope="module")
def expected():
    skipped, lat, err = 0, defaultdict(list), defaultdict(int)
    for line in (WS / "access.log").read_text(encoding="utf-8").splitlines():
        r = parse(line)
        if r is None:
            skipped += 1
            continue
        lat[r[0]].append(r[2])
        err[r[0]] += r[1] >= 500
    eps = {k: {"count": len(v), "errors": err[k], "error_rate": round(err[k] / len(v), 4),
               "p50_ms": round(nearest_rank(v, 50), 1), "p95_ms": round(nearest_rank(v, 95), 1)} for k, v in lat.items()}
    return {"skipped_lines": skipped, "endpoints": eps}


@pytest.fixture(scope="module")
def report():
    p = WS / "report.json"
    assert p.exists(), "report.json was not written"
    return json.loads(p.read_text(encoding="utf-8"))


def test_log_untouched():
    assert hashlib.sha256((WS / "access.log").read_bytes()).hexdigest() == LOG_SHA256


def test_endpoint_keys(report, expected):
    assert set(report["endpoints"]) == set(expected["endpoints"])


def test_skipped_lines(report, expected):
    assert report["skipped_lines"] == expected["skipped_lines"]


def test_counts_and_errors(report, expected):
    for k, e in expected["endpoints"].items():
        got = report["endpoints"][k]
        assert (got["count"], got["errors"]) == (e["count"], e["errors"]), k
        assert got["error_rate"] == pytest.approx(e["error_rate"], abs=1e-4), k


def test_percentiles(report, expected):
    for k, e in expected["endpoints"].items():
        got = report["endpoints"][k]
        assert got["p50_ms"] == pytest.approx(e["p50_ms"], abs=0.051), k
        assert got["p95_ms"] == pytest.approx(e["p95_ms"], abs=0.051), k
