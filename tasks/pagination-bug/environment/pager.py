"""Pagination helper used by the list endpoints."""


def paginate(items, page, per_page=20):
    total_pages = len(items) // per_page
    start = page * per_page
    end = start + per_page
    return {
        "items": items[start:end],
        "page": page,
        "per_page": per_page,
        "total": len(items),
        "total_pages": total_pages,
        "has_next": page < total_pages - 1,
        "has_prev": page > 0,
    }
