"""Generates tasks/access-log-latency/environment/access.log (seeded, so the file is reproducible)."""

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

rng = random.Random(20261031)
ROUTES = [
    ("GET", "/api/users/{id}", 0.040, 0.01),
    ("GET", "/api/users", 0.120, 0.02),
    ("POST", "/api/orders", 0.300, 0.06),
    ("GET", "/api/orders/{id}/items", 0.080, 0.01),
    ("GET", "/health", 0.002, 0.0),
    ("DELETE", "/api/users/{id}", 0.150, 0.03),
]
WEIGHTS = [30, 15, 12, 18, 20, 5]
t = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)
lines = []
for i in range(3000):
    t += timedelta(milliseconds=rng.randint(5, 900))
    method, route, base, err = rng.choices(ROUTES, WEIGHTS)[0]
    path = route.replace("{id}", str(rng.randint(1, 99999)))
    if rng.random() < 0.15:
        path += f"?page={rng.randint(1, 9)}"
    elif rng.random() < 0.08 and path != "/health":
        path += "/"
    status = rng.choice([500, 502, 503]) if rng.random() < err else rng.choice([200, 200, 200, 201, 204, 304, 404])
    latency = rng.lognormvariate(0, 0.6) * base * (4 if status >= 500 else 1)
    stamp = t.strftime("%d/%b/%Y:%H:%M:%S +0000")
    ip = f"10.0.{rng.randint(0, 9)}.{rng.randint(1, 254)}"
    line = f'{ip} - - [{stamp}] "{method} {path} HTTP/1.1" {status} {rng.randint(80, 9000)} {latency:.4f}'
    r = rng.random()
    if r < 0.01:
        line = line.rsplit(" ", 1)[0] + " -"  # no latency recorded
    elif r < 0.02:
        line = line[: rng.randint(10, len(line) - 10)]  # truncated write
    elif r < 0.025:
        line = "health-checker: probe ok"
    lines.append(line)
out = Path(__file__).resolve().parent.parent / "tasks/access-log-latency/environment/access.log"
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote {len(lines)} lines to {out}")
