#!/usr/bin/env bash
set -euo pipefail
cat > pager.py <<'PY'
"""Pagination helper used by the list endpoints."""


def paginate(items, page, per_page=20):
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page must be at least 1")
    total_pages = -(-len(items) // per_page)
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "items": items[start:end],
        "page": page,
        "per_page": per_page,
        "total": len(items),
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }
PY
