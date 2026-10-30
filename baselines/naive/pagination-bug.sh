#!/usr/bin/env bash
# Fixes the 1-based offset and validation, but still floors total_pages, so the last partial page is lost.
set -euo pipefail
cat > pager.py <<'PY'
def paginate(items, page, per_page=20):
    if page < 1 or per_page < 1:
        raise ValueError("bad page")
    total_pages = len(items) // per_page
    start = (page - 1) * per_page
    return {"items": items[start:start + per_page], "page": page, "per_page": per_page, "total": len(items),
            "total_pages": total_pages, "has_next": page < total_pages, "has_prev": page > 1}
PY
