# Dataset 02: date_dim_legit
Expected join:
- daily_sales.date_key -> dim_date.date_key
Non-equality relationship (optional future):
- promotions.start_date/end_date applies to dim_date.date (temporal range)
Trap:
- daily_sales.created_date should NOT be used as join key
