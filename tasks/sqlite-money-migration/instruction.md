`app.db` is a SQLite database whose `orders.amount` column stores money as free text written by several old clients (`$1,234.50`, `USD 12`, `(3.10)` and so on). We want integer cents.

Write `migrate.py` in the workspace. `python migrate.py PATH` migrates the database at `PATH` (default `app.db`), and then run it on `app.db`. The migration must:

1. Add an `amount_cents INTEGER` column to `orders` and fill it for every row.
2. Create a table `migration_errors(order_id INTEGER PRIMARY KEY, raw TEXT)` holding one row for each order whose `amount` is not NULL but could not be parsed. Those orders get `amount_cents = NULL`. Orders whose `amount` is NULL get `amount_cents = NULL` and no error row.
3. Create an index named `idx_orders_amount_cents` on `orders(amount_cents)`.
4. Leave the `amount` column and all existing data as they are.
5. Be safe to run again: a second run on an already migrated database must succeed and leave it in exactly the same state.
6. Apply all of its changes in one transaction, so a failure leaves the database untouched.

An amount is valid when, after trimming surrounding whitespace, it is:

- optionally negative, written either with a leading `-` or by wrapping the whole amount in parentheses (not both);
- then an optional currency marker, `$` or `USD` in any letter case, optionally followed by spaces;
- then a number: either plain digits, or digits grouped by commas with 1 to 3 digits before the first comma and exactly 3 after each comma; optionally followed by `.` and one or two digits.

Anything else is invalid, including other currencies, more than two decimal places, and a dot without digits on both sides. `12.5` means 1250 cents. Use exact decimal arithmetic.
