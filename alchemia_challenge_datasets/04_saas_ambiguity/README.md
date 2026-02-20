# Dataset 04: saas_ambiguity
Expected joins:
- contacts.acct_id -> accounts.account_id (acct_id sometimes 'ACC' prefix)
- subscriptions.account_id -> accounts.account_id (dirty keys)
- events.account_id -> accounts.account_id (dirty keys)
- events.contact_id -> contacts.contact_id (many nulls, dirty keys)
Traps:
- country, created_date, status, currency
