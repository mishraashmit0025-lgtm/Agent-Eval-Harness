#!/usr/bin/env bash
set -euo pipefail
cat > /tmp/report_$$.py <<'PY'
import json, math, re
from collections import defaultdict

LINE = re.compile(r'^\S+ - - \[[^\]]+\] "([A-Z]+) (\S+) HTTP/[\d.]+" (\d{3}) (\d+|-) (\d+(?:\.\d+)?)$')

def endpoint(method, path):
    path = path.split("?", 1)[0]
    if len(path) > 1:
        path = path.rstrip("/")
    segs = [":id" if s.isdigit() else s for s in path.split("/")]
    return f"{method} {'/'.join(segs) or '/'}"

def rank(sorted_vals, p):
    return sorted_vals[math.ceil(p / 100 * len(sorted_vals)) - 1]

skipped, lat, err = 0, defaultdict(list), defaultdict(int)
with open("access.log", encoding="utf-8") as f:
    for line in f:
        m = LINE.match(line.rstrip("\n"))
        if not m:
            skipped += 1
            continue
        key = endpoint(m.group(1), m.group(2))
        lat[key].append(float(m.group(5)) * 1000)
        err[key] += int(m.group(3)) >= 500

out = {"skipped_lines": skipped, "endpoints": {}}
for key, vals in sorted(lat.items()):
    vals.sort()
    out["endpoints"][key] = {"count": len(vals), "errors": err[key], "error_rate": round(err[key] / len(vals), 4),
                             "p50_ms": round(rank(vals, 50), 1), "p95_ms": round(rank(vals, 95), 1)}
json.dump(out, open("report.json", "w"), indent=2)
PY
"${PYTHON:-python3}" /tmp/report_$$.py
rm -f /tmp/report_$$.py
