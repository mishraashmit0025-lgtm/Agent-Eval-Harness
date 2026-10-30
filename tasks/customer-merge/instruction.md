We are moving to a single customer table. `crm_export.csv` and `billing_export.csv` both hold customer records, with different column names and timestamp formats, and the same customer often appears in both (sometimes more than once).

Write `customers.csv` in the workspace with the header `email,name,plan,updated_at` and exactly one row per customer:

- A customer is identified by their normalized email: trim surrounding whitespace, lowercase it, and drop any `+tag` from the part before the `@` (`Ana+news@X.com` and `ana@x.com` are the same person). Rows whose normalized email is empty or has no `@` are dropped.
- When a customer has several records across both files, keep the one with the latest `updated_at` moment in time. Timestamps carry UTC offsets, and those offsets matter. If two records are at exactly the same moment, the billing record wins.
- `name` and `plan` come from the kept record, with surrounding whitespace trimmed. `email` is the normalized email. `updated_at` is the kept record's moment converted to UTC and written as `YYYY-MM-DDTHH:MM:SSZ`.
- Sort rows by email.

Do not modify the two input files.
