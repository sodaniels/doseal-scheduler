# app/services/seeders/social_role_seeder.py

from typing import Dict, Any, List
from app.utils.logger import Log

from ...models.admin.super_superadmin_model import Role
from ...constants.social_role_permissions import (
    PERMISSION_FIELDS_FOR_ADMINS,
    PERMISSION_FIELDS_FOR_ADMIN_ROLE,
)

def _perm_all_ones(field: str) -> List[dict]:
    """Return a permission list with all actions set to '1' for this module."""
    actions = PERMISSION_FIELDS_FOR_ADMIN_ROLE.get(field, [])
    return [{a: "1" for a in actions}] if actions else [{"read": "1"}]

def _perm_some(field: str, allowed_actions: List[str]) -> List[dict]:
    """Return a permission list with only some actions as '1', others as '0'."""
    actions = PERMISSION_FIELDS_FOR_ADMIN_ROLE.get(field, [])
    return [{a: ("1" if a in allowed_actions else "0") for a in actions}] if actions else [{"read": "0"}]

def _build_role_payload(
    *,
    business_id: str,
    user__id: str,
    user_id: str,
    name: str,
    email: str,
    admin_id: str,
    created_by: str,
    permissions: Dict[str, List[dict]],
) -> Dict[str, Any]:
    """
    Build payload for your Role(**payload) constructor.
    IMPORTANT:
      - Only include permission keys that you want stored (your model does that).
    """
    payload = {
        "business_id": business_id,
        "user__id": user__id,
        "user_id": user_id,
        "name": name,
        "email": email,
        "admin_id": admin_id,
        "created_by": created_by,
        "status": "Active",
    }

    # add only permission fields present in permissions dict
    for k, v in (permissions or {}).items():
        if k in PERMISSION_FIELDS_FOR_ADMINS:
            payload[k] = v

    return payload


class SocialRoleSeeder:
    """
    Seeds default Social Scheduler roles for a business.

    Idempotent strategy:
      - checks if a role with same (admin_id + name + email) already exists using Role.check_role_exists()
      - if exists, skip creating it
    """

    @classmethod
    def seed_defaults(
        cls,
        *,
        business_id: str,
        admin_user__id: str,
        admin_user_id: str,
        admin_email: str,
        admin_name: str,
    ) -> Dict[str, Any]:
        """
        Args:
          business_id: tenant business id
          admin_user__id: ObjectId string (your g.current_user["_id"])
          admin_user_id: optional user_id field you store
          admin_email: email to tag role records (you use this in uniqueness check)
          admin_name: name to tag role records

        Returns:
          {"created": int, "skipped": int}
        """

        log_tag = f"[social_role_seeder.py][seed_defaults][business_id={business_id}]"

        roles_to_seed = cls._default_role_templates(
            admin_email=admin_email,
        )

        created = 0
        skipped = 0

        for tpl in roles_to_seed:
            role_name = tpl["name"]
            role_email = tpl["email"]  # can be derived from admin_email or fixed
            permissions = tpl["permissions"]

            try:
                exists = Role.check_role_exists(
                    admin_id=admin_user__id,
                    name_key="name",
                    name_value=role_name,
                    email_key="email",
                    email_value=role_email,
                )
            except Exception as e:
                Log.info(f"{log_tag} duplicate check failed for {role_name}: {e}")
                # fail-safe: continue but avoid duplicates by skipping
                skipped += 1
                continue

            if exists:
                Log.info(f"{log_tag} role exists => skip: {role_name}")
                skipped += 1
                continue

            payload = _build_role_payload(
                business_id=business_id,
                user__id=admin_user__id,
                user_id=admin_user_id,
                name=role_name,
                email=role_email,
                admin_id=admin_user__id,
                created_by=admin_user__id,
                permissions=permissions,
            )

            try:
                role = Role(**payload)
                role_id = role.save(processing_callback=True)
                if role_id:
                    created += 1
                    Log.info(f"{log_tag} created role={role_name} role_id={role_id}")
                else:
                    skipped += 1
                    Log.info(f"{log_tag} role.save returned None for {role_name}")
            except Exception as e:
                skipped += 1
                Log.info(f"{log_tag} failed creating role={role_name}: {e}")

        return {"created": created, "skipped": skipped}

    @staticmethod
    def _default_role_templates(*, admin_email: str) -> List[Dict[str, Any]]:
        """
        Defines default roles for Social Scheduler app.
        Email:
          - You currently store role email, and use it in uniqueness check.
          - Use a deterministic role email so duplicates are prevented.
        """

        # deterministic role "emails" (they are not used for login; just identifiers)
        # This makes duplicates consistent.
        def role_email(slug: str) -> str:
            domain = "roles.local"
            return f"{slug.lower()}@{domain}"

        # -------------------------
        # ADMIN: all ones
        # -------------------------
        admin_perms = {f: _perm_all_ones(f) for f in PERMISSION_FIELDS_FOR_ADMINS}

        # -------------------------
        # SOCIAL MANAGER
        # -------------------------
        manager_perms = {
            "dashboard": _perm_some("dashboard", ["read"]),
            "social_accounts": _perm_all_ones("social_accounts"),
            "posts": _perm_all_ones("posts"),
            "scheduled_posts": _perm_all_ones("scheduled_posts"),
            "publishing": _perm_all_ones("publishing"),
            "media_library": _perm_all_ones("media_library"),
            "inbox": _perm_all_ones("inbox"),
            "comments": _perm_all_ones("comments"),
            "analytics": _perm_some("analytics", ["read"]),
            "reports": _perm_some("reports", ["read", "export"]),
            "team": _perm_some("team", ["read", "invite"]),
            "role": _perm_some("role", ["read"]),  # manager cannot edit roles
            "settings": _perm_some("settings", ["read"]),
            "integrations": _perm_all_ones("integrations"),
            "billing": _perm_some("billing", ["read"]),
        }

        # -------------------------
        # CONTENT CREATOR
        # -------------------------
        creator_perms = {
            "dashboard": _perm_some("dashboard", ["read"]),
            "social_accounts": _perm_some("social_accounts", ["read"]),
            "posts": _perm_some("posts", ["read", "create", "update"]),
            "scheduled_posts": _perm_some("scheduled_posts", ["read", "create", "update", "cancel"]),
            "media_library": _perm_some("media_library", ["read", "upload", "delete"]),
            "inbox": _perm_some("inbox", ["read", "reply"]),
            "comments": _perm_some("comments", ["read", "reply"]),
            "analytics": _perm_some("analytics", ["read"]),
            "reports": _perm_some("reports", ["read"]),
            "team": _perm_some("team", ["read"]),
            "role": _perm_some("role", ["read"]),
            "settings": _perm_some("settings", ["read"]),
            "integrations": _perm_some("integrations", ["read"]),
        }

        # -------------------------
        # APPROVER / PUBLISHER
        # -------------------------
        approver_perms = {
            "dashboard": _perm_some("dashboard", ["read"]),
            "social_accounts": _perm_some("social_accounts", ["read"]),
            "posts": _perm_some("posts", ["read"]),
            "scheduled_posts": _perm_some("scheduled_posts", ["read", "update", "cancel"]),
            "publishing": _perm_some("publishing", ["publish", "retry"]),
            "media_library": _perm_some("media_library", ["read"]),
            "inbox": _perm_all_ones("inbox"),
            "comments": _perm_all_ones("comments"),
            "analytics": _perm_some("analytics", ["read"]),
            "reports": _perm_some("reports", ["read", "export"]),
        }

        # -------------------------
        # ANALYST
        # -------------------------
        analyst_perms = {
            "dashboard": _perm_some("dashboard", ["read"]),
            "analytics": _perm_some("analytics", ["read"]),
            "reports": _perm_some("reports", ["read", "export"]),
            "posts": _perm_some("posts", ["read"]),
            "scheduled_posts": _perm_some("scheduled_posts", ["read"]),
            "social_accounts": _perm_some("social_accounts", ["read"]),
        }

        # -------------------------
        # VIEWER (read-only)
        # -------------------------
        viewer_perms = {
            "dashboard": _perm_some("dashboard", ["read"]),
            "posts": _perm_some("posts", ["read"]),
            "scheduled_posts": _perm_some("scheduled_posts", ["read"]),
            "social_accounts": _perm_some("social_accounts", ["read"]),
            "analytics": _perm_some("analytics", ["read"]),
            "reports": _perm_some("reports", ["read"]),
        }

        return [
            {"name": "Admin",           "email": role_email("admin"),          "permissions": admin_perms},
            {"name": "Social Manager",  "email": role_email("social_manager"), "permissions": manager_perms},
            {"name": "Content Creator", "email": role_email("content_creator"),"permissions": creator_perms},
            {"name": "Approver",        "email": role_email("approver"),       "permissions": approver_perms},
            {"name": "Analyst",         "email": role_email("analyst"),        "permissions": analyst_perms},
            {"name": "Viewer",          "email": role_email("viewer"),         "permissions": viewer_perms},
        ]