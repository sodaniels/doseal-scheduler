def is_downgrade(current_pkg: dict, new_pkg: dict) -> bool:
    # limits
    cur_limits = current_pkg.get("limits") or current_pkg
    new_limits = new_pkg.get("limits") or new_pkg

    limit_keys = ["max_outlets", "max_products", "max_users", "max_transactions_per_month", "storage_limit_gb"]
    for k in limit_keys:
        cur = cur_limits.get(k)
        new = new_limits.get(k)

        # None means unlimited. Unlimited -> number is downgrade.
        if cur is None and new is not None:
            return True

        # number -> lower number is downgrade
        if isinstance(cur, (int, float)) and isinstance(new, (int, float)) and new < cur:
            return True

    # features: True -> False is downgrade
    cur_feat = current_pkg.get("features") or {}
    new_feat = new_pkg.get("features") or {}
    for f, cur_v in cur_feat.items():
        if cur_v is True and new_feat.get(f) is False:
            return True

    return False