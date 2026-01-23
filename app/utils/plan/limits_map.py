# app/utils/plan/limits_map.py

LIMIT_RULES = {
    # -------- Core catalog --------
    "products": {
        "feature": "inventory",
        "limit_key": "max_products",
        "counter": "products",
        "period": "billing",
    },
    "brands": {
        "feature": "inventory",
        "limit_key": "max_brands",
        "counter": "brands",
        "period": "billing",
    },
    "variants": {
        "feature": "inventory",
        "limit_key": "max_variants",
        "counter": "variants",
        "period": "billing",
    },
    "composite_variants": {
        "feature": "inventory",
        "limit_key": "max_composite_variants",
        "counter": "composite_variants",
        "period": "billing",
    },

    # -------- Business scale / multi-branch --------
    "outlets": {
        "feature": "multi_outlet",
        "limit_key": "max_outlets",
        "counter": "outlets",
        "period": "billing",
    },
    "business_locations": {
        "feature": "multi_outlet",
        "limit_key": "max_business_locations",
        "counter": "business_locations",
        "period": "billing",
    },

    # -------- People / CRM --------
    "users": {
        # Optional feature gate (remove if you want users limited on all plans)
        "feature": "user_permissions",
        "limit_key": "max_users",
        "counter": "users",
        "period": "billing",
    },
    "customers": {
        "feature": "reports",  # optional; change/remove if you want always-on
        "limit_key": "max_customers",
        "counter": "customers",
        "period": "billing",
    },
    "suppliers": {
        "feature": "inventory",  # optional
        "limit_key": "max_suppliers",
        "counter": "suppliers",
        "period": "billing",
    },

    # -------- Selling / marketing --------
    "discounts": {
        "feature": "discount_coupons",
        "limit_key": "max_discounts",
        "counter": "discounts",
        "period": "billing",
    },
    "coupons": {
        "feature": "discount_coupons",
        "limit_key": "max_coupons",
        "counter": "coupons",
        "period": "billing",
    },
    "gift_cards": {
        "feature": "loyalty_program",
        "limit_key": "max_gift_cards",
        "counter": "gift_cards",
        "period": "billing",
    },

    # -------- Transactions (always monthly) --------
    "sales": {
        "feature": "pos",
        "limit_key": "max_transactions_per_month",
        "counter": "transactions",
        "period": "month",   # IMPORTANT: per month regardless of yearly billing
    },
    # If you track purchase orders and want to limit them:
    "purchase_orders": {
        "feature": "inventory",
        "limit_key": "max_purchase_orders",
        "counter": "purchase_orders",
        "period": "billing",
    },

    # -------- Ops / accounting (optional limits) --------
    "expenses": {
        "feature": "reports",  # optional
        "limit_key": "max_expenses",
        "counter": "expenses",
        "period": "billing",
    },
    "cash_sessions": {
        "feature": "pos",
        "limit_key": "max_cash_sessions",
        "counter": "cash_sessions",
        "period": "billing",
    },

    # -------- Stock (optional; can become huge) --------
    "stock": {
        "feature": "inventory",
        "limit_key": "max_stock_movements",
        "counter": "stock_movements",
        "period": "billing",
    },

    # -------- Usually NOT limited (leave out unless you add max_* fields) --------
    # store, unit, category, sub_category, tax, warranty, tag,
    # selling_price_group
}
