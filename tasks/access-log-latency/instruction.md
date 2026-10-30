`access.log` is a day of traffic from one of our API servers. Each good line looks like this, with the request time in seconds as the last field:

```
10.0.9.224 - - [12/Oct/2026:09:00:00 +0000] "GET /api/users/96185?page=2 HTTP/1.1" 201 614 0.0284
```

Write `report.json` in the workspace with per-endpoint latency and error statistics:

```json
{
  "skipped_lines": 0,
  "endpoints": {
    "GET /api/users/:id": {"count": 0, "errors": 0, "error_rate": 0.0, "p50_ms": 0.0, "p95_ms": 0.0}
  }
}
```

Rules:

- An endpoint is the HTTP method, a space, and the path with the query string removed, any trailing slash removed (except for `/` itself), and every path segment made only of digits replaced by `:id`.
- A line counts only if it has all the fields shown above: client, two dashes, timestamp in brackets, a quoted request with method, path and protocol, a three-digit status, a byte count, and a numeric request time. Anything else is skipped and counted in `skipped_lines`.
- `errors` counts responses with status 500 or above. `error_rate` is `errors / count` rounded to 4 decimal places.
- `p50_ms` and `p95_ms` are latency percentiles in milliseconds using the nearest-rank method: sort the endpoint's latencies ascending; the p-th percentile is the value at 1-based rank `ceil(p / 100 * n)`. Round to 1 decimal place.

Leave `access.log` unchanged.
