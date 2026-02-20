# Dataset 01: ecom_traps
Expected joins (equality):
- orders.customer_id -> customers.customer_id (dirty keys)
- order_items.order_id -> orders.order_id
- order_items.product_id -> products.product_id (dirty keys)
- payments.order_id -> orders.order_id (dirty keys)
- refunds.payment_id -> payments.payment_id
- order_promotions.order_id -> orders.order_id
- order_promotions.promo_code -> promotions.promo_code
Composite key:
- order_items(order_id, line_no) near-unique
Traps:
- created_date/updated_date, country, currency, region_code, active, status
