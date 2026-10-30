Users of our API say pagination is broken: page 1 skips the first record, the last partial page never shows up, and asking for page 0 or a negative page returns data instead of an error.

Fix `paginate` in `pager.py`. Pages are numbered from 1. `total_pages` is the number of pages needed to show every item (0 for an empty list). Asking for a page past the end returns an empty `items` list, not an error. `page < 1` or `per_page < 1` must raise `ValueError`. Keep the function's signature and the keys of the dict it returns.
