#!/usr/bin/env bash
# Splits on whitespace and uses interpolated percentiles (statistics.quantiles) instead of nearest-rank.
set -euo pipefail
cat > /tmp/naive_$$.py <<'PY'
import json, re, statistics
from collections import defaultdict
lat, err, skipped = defaultdict(list), defaultdict(int), 0
for line in open("access.log", encoding="utf-8"):
    f = line.split()
    try:
        method, path, status, latency = f[5].strip('"'), f[6], int(f[8]), float(f[10])
    except (IndexError, ValueError):
        skipped += 1
        continue
    path = path.split("?")[0].rstrip("/") or "/"
    path = re.sub(r"/\d+", "/:id", path)
    key = f"{method} {path}"
    lat[key].append(latency * 1000)
    err[key] += status >= 500
out = {"skipped_lines": skipped, "endpoints": {}}
for k, v in lat.items():
    q = statistics.quantiles(v, n=100) if len(v) > 1 else [v[0]] * 99
    out["endpoints"][k] = {"count": len(v), "errors": err[k], "error_rate": round(err[k] / len(v), 4),
                           "p50_ms": round(q[49], 1), "p95_ms": round(q[94], 1)}
json.dump(out, open("report.json", "w"), indent=2)
PY
"${PYTHON:-python3}" /tmp/naive_$$.py
rm -f /tmp/naive_$$.py
