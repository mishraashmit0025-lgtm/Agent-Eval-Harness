import os
import sys

import pytest

sys.path.insert(0, os.environ["WORKSPACE"])
from pager import paginate  # noqa: E402

ITEMS = list(range(1, 46))  # 45 items


def test_first_page_starts_at_first_item():
    r = paginate(ITEMS, 1, 10)
    assert r["items"] == list(range(1, 11))
    assert r["has_prev"] is False and r["has_next"] is True


def test_last_partial_page_is_reachable():
    r = paginate(ITEMS, 5, 10)
    assert r["total_pages"] == 5
    assert r["items"] == [41, 42, 43, 44, 45]
    assert r["has_next"] is False and r["has_prev"] is True


def test_every_item_appears_exactly_once():
    for per_page in (1, 7, 10, 45, 50):
        pages = paginate(ITEMS, 1, per_page)["total_pages"]
        seen = [x for p in range(1, pages + 1) for x in paginate(ITEMS, p, per_page)["items"]]
        assert seen == ITEMS, per_page


def test_exact_multiple():
    r = paginate(list(range(40)), 4, 10)
    assert r["total_pages"] == 4 and r["has_next"] is False and len(r["items"]) == 10


def test_empty_and_past_the_end():
    assert paginate([], 1, 10)["total_pages"] == 0
    assert paginate([], 1, 10)["items"] == []
    r = paginate(ITEMS, 9, 10)
    assert r["items"] == [] and r["has_next"] is False


@pytest.mark.parametrize("page,per_page", [(0, 10), (-1, 10), (1, 0), (1, -5)])
def test_invalid_arguments(page, per_page):
    with pytest.raises(ValueError):
        paginate(ITEMS, page, per_page)


def test_shape_unchanged():
    assert set(paginate(ITEMS, 2, 10)) == {"items", "page", "per_page", "total", "total_pages", "has_next", "has_prev"}
    assert paginate(ITEMS, 2, 10)["total"] == 45
