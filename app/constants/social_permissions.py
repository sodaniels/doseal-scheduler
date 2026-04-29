# app/constants/church_permissions.py

"""
Church CRM – Fine-Grained Role & Permission Definitions
========================================================

Architecture:
  • Each MODULE has a list of allowed ACTIONS (read, create, update, delete, approve, export, etc.)
  • Each ROLE has a dict mapping MODULE → [ACTIONS]
  • Permissions can be scoped per branch via the Role model
  • SYSTEM_OWNER bypasses all checks (cross-business platform operator)
  • Restricted modules can be reserved for SYSTEM_OWNER only
  • Custom roles copy from a base role and can be tweaked per module

Usage in resource:
  from ...constants.church_permissions import has_permission
  if not has_permission(user_info, "donations", "export", branch_id):
      return prepared_response(False, "FORBIDDEN", "You don't have permission.")
"""

# ═══════════════════════════════════════════════════════════════
# MODULE DEFINITIONS — every module and its possible actions
# ═══════════════════════════════════════════════════════════════

PERMISSION_MODULES = [
    # Platform-level (SYSTEM_OWNER only)
    "businesses",
    "configuration",
    "discount",
    "promo-code",
    "packages",

    # Core
    "dashboard",
    "members",
    "branches",
    "households",

    # Groups & Ministry
    "groups",
    "ministries",

    # Engagement
    "attendance",
    "followup",
    "care",
    "messaging",
    "events",

    # Finance
    "accounting",
    "donations",
    "pledges",
    "budgets",

    # Volunteering & Worship
    "volunteers",
    "worship",

    # Workflows
    "workflows",

    # Reporting
    "dashboards",
    "reports",
    "auditlogs",

    # Forms & Portal
    "forms",
    "portal",
    "pagebuilder",

    # Storage
    "storage",

    # Admin / Security
    "team",
    "roles",
    "settings",
    "billing",
    "subscription",
    "integrations",

    # Sacraments & Sermons
    "sacraments",
    "sermons",

    # Safeguarding
    "safeguarding",

    # Request demo & complaints
    "request_demos",
    "complaints",
    
    # Data Import/Export
    "data_import_export",
]

# All possible actions across all modules
ALL_ACTIONS = [
    "read", "create", "update", "delete",
    "approve", "reject",
    "export", "import",
    "publish", "unpublish",
    "assign", "upload",
    "send", "schedule",
    "manage",
    "archive",
    "refund",
]

# Per-module action sets — defines what actions are valid for each module
MODULE_ACTIONS = {
    # SYSTEM_OWNER ONLY
    "businesses":    ["read", "create", "update", "delete", "manage", "export"],
    "configuration": ["read", "create", "update", "delete", "manage"],
    "discount":      ["read", "create", "update", "delete", "manage"],
    "promo-code":    ["read", "create", "update", "delete", "manage"],
    "packages":      ["read", "create", "update", "delete", "manage"],

    # Business modules
    "dashboard":     ["read"],
    "members":       ["read", "create", "update", "delete", "import", "export", "manage"],
    "branches":      ["read", "create", "update", "delete", "archive", "export"],
    "households":    ["read", "create", "update", "delete"],
    "groups":        ["read", "create", "update", "delete", "manage", "assign"],
    "ministries":    ["read", "create", "update", "delete", "manage", "assign"],
    "attendance":    ["read", "create", "update", "delete", "export"],
    "followup":      ["read", "create", "update", "delete", "assign", "export"],
    "care":          ["read", "create", "update", "delete", "assign", "export"],
    "messaging":     ["read", "create", "update", "delete", "send", "schedule", "export"],
    "events":        ["read", "create", "update", "delete", "publish", "unpublish", "export", "manage"],
    "accounting":    ["read", "create", "update", "delete", "approve", "export", "import"],
    "donations":     ["read", "create", "update", "delete", "export", "import", "refund"],
    "pledges":       ["read", "create", "update", "delete", "export"],
    "budgets":       ["read", "create", "update", "delete", "approve", "export"],
    "volunteers":    ["read", "create", "update", "delete", "approve", "reject", "assign", "export"],
    "worship":       ["read", "create", "update", "delete", "publish", "assign"],
    "workflows":     ["read", "create", "update", "delete", "approve", "reject", "assign"],
    "dashboards":    ["read", "create", "update", "delete"],
    "reports":       ["read", "create", "export", "schedule"],
    "auditlogs":     ["read", "export"],
    "safeguarding":  ["read", "create", "update", "delete", "approve", "export", "assign"],
    "forms":         ["read", "create", "update", "delete", "publish", "unpublish", "export"],
    "portal":        ["read", "update"],
    "pagebuilder":   ["read", "create", "update", "delete", "publish", "unpublish", "upload"],
    "storage":       ["read", "update", "upload", "delete"],
    "team":          ["read", "create", "update", "delete"],
    "roles":         ["read", "create", "update", "delete"],
    "settings":      ["read", "update"],
    "billing":       ["read", "update"],
    "subscription":  ["read", "update"],
    "integrations":  ["read", "create", "update", "delete"],
    "sacraments":    ["read", "create", "update", "delete", "export"],
    "sermons":       ["read", "create", "update", "delete", "publish", "export"],
    "request_demos": ["read", "update", "delete", "export"],
    "complaints":    ["read", "update", "delete", "export"],
    "data_import_export": ["read", "create", "delete", "export", "import"],
}

# SYSTEM_OWNER-only modules
SYSTEM_OWNER_ONLY_MODULES = {
    "businesses",
    "configuration",
    "discount",
    "promo-code",
    "packages",
}

# ═══════════════════════════════════════════════════════════════
# ROLE DEFINITIONS — default permission sets per role
# ═══════════════════════════════════════════════════════════════

ROLE_SYSTEM_OWNER = "SYSTEM_OWNER"
ROLE_BUSINESS_OWNER = "BUSINESS_OWNER"
ROLE_SUPER_ADMIN = "SUPER_ADMIN"
ROLE_PASTOR = "PASTOR"
ROLE_FINANCE_OFFICER = "FINANCE_OFFICER"
ROLE_CHURCH_ADMIN = "CHURCH_ADMIN"
ROLE_DEPARTMENT_HEAD = "DEPARTMENT_HEAD"
ROLE_GROUP_LEADER = "GROUP_LEADER"
ROLE_VOLUNTEER = "VOLUNTEER"
ROLE_MEMBER = "MEMBER"
ROLE_GUEST = "GUEST"
ROLE_CUSTOM = "CUSTOM"

SYSTEM_ROLES = [
    ROLE_SYSTEM_OWNER, ROLE_BUSINESS_OWNER, ROLE_SUPER_ADMIN,
    ROLE_PASTOR, ROLE_FINANCE_OFFICER, ROLE_CHURCH_ADMIN,
    ROLE_DEPARTMENT_HEAD, ROLE_GROUP_LEADER, ROLE_VOLUNTEER,
    ROLE_MEMBER, ROLE_GUEST, ROLE_CUSTOM,
]

# ── System Owner — god-level, cross-business, platform-wide ──
PERMISSIONS_SYSTEM_OWNER = {
    module: list(actions) for module, actions in MODULE_ACTIONS.items()
}

# ── Super Admin — full access within own business except SYSTEM_OWNER-only modules ──
PERMISSIONS_SUPER_ADMIN = {
    module: list(actions) for module, actions in MODULE_ACTIONS.items()
}
PERMISSIONS_SUPER_ADMIN["request_demos"] = []
PERMISSIONS_SUPER_ADMIN["complaints"] = []
for _module in SYSTEM_OWNER_ONLY_MODULES:
    PERMISSIONS_SUPER_ADMIN[_module] = []

# ── Business Owner — full access within own business except SYSTEM_OWNER-only modules ──
PERMISSIONS_BUSINESS_OWNER = {
    module: list(actions) for module, actions in MODULE_ACTIONS.items()
}
PERMISSIONS_BUSINESS_OWNER["request_demos"] = []
PERMISSIONS_BUSINESS_OWNER["complaints"] = []
for _module in SYSTEM_OWNER_ONLY_MODULES:
    PERMISSIONS_BUSINESS_OWNER[_module] = []

# ── Pastor — leadership view, pastoral modules, read-only finance, full workflows ──
PERMISSIONS_PASTOR = {
    "dashboard":     ["read"],
    "safeguarding":  ["read", "create", "update", "delete", "approve", "export", "assign"],
    "members":       ["read", "create", "update", "export", "manage"],
    "branches":      ["read"],
    "households":    ["read", "create", "update"],
    "groups":        ["read", "create", "update", "delete", "manage", "assign"],
    "ministries":    ["read", "create", "update", "delete", "manage", "assign"],
    "attendance":    ["read", "create", "update", "export"],
    "followup":      ["read", "create", "update", "assign", "export"],
    "care":          ["read", "create", "update", "delete", "assign", "export"],
    "messaging":     ["read", "create", "send", "schedule"],
    "events":        ["read", "create", "update", "delete", "publish", "unpublish", "manage"],
    "accounting":    ["read", "approve"],
    "donations":     ["read", "export"],
    "pledges":       ["read", "create", "update", "export"],
    "budgets":       ["read", "approve"],
    "volunteers":    ["read", "create", "update", "approve", "reject", "assign"],
    "worship":       ["read", "create", "update", "delete", "publish", "assign"],
    "workflows":     ["read", "create", "update", "approve", "reject", "assign"],
    "dashboards":    ["read", "create", "update"],
    "reports":       ["read", "create", "export"],
    "auditlogs":     ["read"],
    "forms":         ["read", "create", "update", "delete", "publish"],
    "portal":        ["read"],
    "pagebuilder":   ["read", "create", "update", "publish", "unpublish"],
    "storage":       ["read"],
    "team":          ["read", "create", "update"],
    "roles":         ["read"],
    "settings":      ["read", "update"],
    "billing":       [],
    "subscription":  ["read"],
    "integrations":  ["read"],
    "sacraments":    ["read", "create", "update", "delete", "export"],
    "sermons":       ["read", "create", "update", "delete", "publish", "export"],
    "request_demos": [],
    "complaints":    [],
     "data_import_export": ["read", "create", "import", "export"],
}

# ── Finance Officer — full finance, read-only pastoral ──
PERMISSIONS_FINANCE_OFFICER = {
    "dashboard":     ["read"],
    "members":       ["read"],
    "branches":      ["read"],
    "households":    ["read"],
    "groups":        ["read"],
    "ministries":    ["read"],
    "attendance":    ["read"],
    "followup":      [],
    "safeguarding":  [],
    "care":          [],
    "messaging":     ["read"],
    "events":        ["read"],
    "accounting":    ["read", "create", "update", "delete", "approve", "export", "import"],
    "donations":     ["read", "create", "update", "delete", "export", "import", "refund"],
    "pledges":       ["read", "create", "update", "delete", "export"],
    "budgets":       ["read", "create", "update", "delete", "approve", "export"],
    "volunteers":    ["read"],
    "worship":       [],
    "workflows":     ["read", "approve", "reject"],
    "dashboards":    ["read"],
    "reports":       ["read", "create", "export"],
    "auditlogs":     ["read", "export"],
    "forms":         ["read"],
    "portal":        ["read"],
    "pagebuilder":   ["read"],
    "storage":       ["read"],
    "team":          ["read"],
    "roles":         [],
    "settings":      ["read"],
    "billing":       ["read", "update"],
    "subscription":  ["read", "update"],
    "integrations":  ["read"],
    "sacraments":    [],
    "sermons":       ["read"],
    "request_demos": [],
    "complaints":    [],
    "data_import_export": ["read", "import", "export"],
}

# ── Church Administrator — operational management, no finance approve ──
PERMISSIONS_CHURCH_ADMIN = {
    "dashboard":     ["read"],
    "members":       ["read", "create", "update", "delete", "import", "export", "manage"],
    "safeguarding":  ["read", "create", "update", "export"],
    "branches":      ["read", "create", "update"],
    "households":    ["read", "create", "update", "delete"],
    "groups":        ["read", "create", "update", "delete", "manage", "assign"],
    "ministries":    ["read", "create", "update", "delete", "manage", "assign"],
    "attendance":    ["read", "create", "update", "delete", "export"],
    "followup":      ["read", "create", "update", "delete", "assign", "export"],
    "care":          ["read", "create", "update", "assign"],
    "messaging":     ["read", "create", "update", "delete", "send", "schedule", "export"],
    "events":        ["read", "create", "update", "delete", "publish", "unpublish", "export", "manage"],
    "accounting":    ["read", "create", "update"],
    "donations":     ["read", "create", "update", "export"],
    "pledges":       ["read", "create", "update", "export"],
    "budgets":       ["read"],
    "volunteers":    ["read", "create", "update", "delete", "approve", "reject", "assign", "export"],
    "worship":       ["read", "create", "update", "delete", "publish", "assign"],
    "workflows":     ["read", "create", "update", "delete", "approve", "reject", "assign"],
    "dashboards":    ["read", "create", "update", "delete"],
    "reports":       ["read", "create", "export", "schedule"],
    "auditlogs":     ["read", "export"],
    "forms":         ["read", "create", "update", "delete", "publish", "unpublish", "export"],
    "portal":        ["read", "update"],
    "pagebuilder":   ["read", "create", "update", "delete", "publish", "unpublish", "upload"],
    "storage":       ["read", "update", "upload"],
    "team":          ["read", "create", "update", "delete"],
    "roles":         ["read", "create", "update"],
    "settings":      ["read", "update"],
    "billing":       ["read"],
    "subscription":  ["read"],
    "integrations":  ["read", "create", "update", "delete"],
    "sacraments":    ["read", "create", "update", "delete", "export"],
    "sermons":       ["read", "create", "update", "delete", "publish", "export"],
    "request_demos": [],
    "complaints":    [],
    "data_import_export": ["read", "create", "delete", "import", "export"],
}

# ── Department Head — scoped to their department/ministry ──
PERMISSIONS_DEPARTMENT_HEAD = {
    "dashboard":     ["read"],
    "members":       ["read"],
    "branches":      ["read"],
    "households":    ["read"],
    "safeguarding":  ["read", "create"],
    "groups":        ["read", "create", "update", "manage", "assign"],
    "ministries":    ["read", "update", "manage", "assign"],
    "attendance":    ["read", "create", "update"],
    "followup":      ["read", "create", "update", "assign"],
    "care":          ["read", "create"],
    "messaging":     ["read", "create", "send"],
    "events":        ["read", "create", "update"],
    "accounting":    [],
    "donations":     [],
    "pledges":       [],
    "budgets":       ["read"],
    "volunteers":    ["read", "create", "update", "approve", "reject", "assign"],
    "worship":       ["read", "create", "update", "assign"],
    "workflows":     ["read", "create", "approve"],
    "dashboards":    ["read"],
    "reports":       ["read"],
    "auditlogs":     [],
    "forms":         ["read", "create", "update"],
    "portal":        ["read"],
    "pagebuilder":   [],
    "storage":       ["read", "upload"],
    "team":          ["read"],
    "roles":         [],
    "settings":      ["read"],
    "billing":       [],
    "subscription":  [],
    "integrations":  [],
    "sacraments":    ["read", "create", "update"],
    "sermons":       ["read"],
    "request_demos": [],
    "complaints":    [],
    "data_import_export": ["read", "import"],
}

# ── Group Leader — scoped to their group(s) ──
PERMISSIONS_GROUP_LEADER = {
    "dashboard":     ["read"],
    "members":       ["read"],
    "branches":      ["read"],
    "households":    ["read"],
    "safeguarding":  ["read", "create"],
    "groups":        ["read", "update", "manage"],
    "ministries":    ["read"],
    "attendance":    ["read", "create", "update"],
    "followup":      ["read", "create", "update"],
    "care":          ["read", "create"],
    "messaging":     ["read", "create", "send"],
    "events":        ["read"],
    "accounting":    [],
    "donations":     [],
    "pledges":       [],
    "budgets":       [],
    "volunteers":    ["read"],
    "worship":       ["read"],
    "workflows":     ["read", "create"],
    "dashboards":    ["read"],
    "reports":       ["read"],
    "auditlogs":     [],
    "forms":         ["read"],
    "portal":        ["read"],
    "pagebuilder":   [],
    "storage":       ["read", "upload"],
    "team":          [],
    "roles":         [],
    "settings":      [],
    "billing":       [],
    "subscription":  [],
    "integrations":  [],
    "sacraments":    ["read"],
    "sermons":       ["read"],
    "request_demos": [],
    "complaints":    [],
    "data_import_export": [],
}

# ── Volunteer — self-service + volunteer module ──
PERMISSIONS_VOLUNTEER = {
    "safeguarding":  [],
    "dashboard":     ["read"],
    "members":       [],
    "branches":      ["read"],
    "households":    [],
    "groups":        ["read"],
    "ministries":    ["read"],
    "attendance":    ["read"],
    "followup":      [],
    "care":          [],
    "messaging":     ["read"],
    "events":        ["read"],
    "accounting":    [],
    "donations":     [],
    "pledges":       [],
    "budgets":       [],
    "volunteers":    ["read", "update"],
    "worship":       ["read"],
    "workflows":     ["read", "create"],
    "dashboards":    [],
    "reports":       [],
    "auditlogs":     [],
    "forms":         ["read"],
    "portal":        ["read", "update"],
    "pagebuilder":   [],
    "storage":       ["read", "upload"],
    "team":          [],
    "roles":         [],
    "settings":      [],
    "billing":       [],
    "subscription":  [],
    "integrations":  [],
    "sacraments":    ["read"],
    "sermons":       ["read"],
    "request_demos": [],
    "complaints":    [],
    "data_import_export": [],
}

# ── Member — portal self-service only ──
PERMISSIONS_MEMBER = {
    "safeguarding":  [],
    "dashboard":     ["read"],
    "members":       [],
    "branches":      ["read"],
    "households":    ["read"],
    "groups":        ["read"],
    "ministries":    ["read"],
    "attendance":    ["read"],
    "followup":      [],
    "care":          [],
    "messaging":     ["read"],
    "events":        ["read"],
    "accounting":    [],
    "donations":     ["read"],
    "pledges":       ["read"],
    "budgets":       [],
    "volunteers":    ["read"],
    "worship":       [],
    "workflows":     ["read", "create"],
    "dashboards":    [],
    "reports":       [],
    "auditlogs":     [],
    "forms":         ["read"],
    "portal":        ["read", "update"],
    "pagebuilder":   [],
    "storage":       ["read", "upload"],
    "team":          [],
    "roles":         [],
    "settings":      [],
    "billing":       [],
    "subscription":  [],
    "integrations":  [],
    "sacraments":    ["read"],
    "sermons":       ["read"],
    "request_demos": [],
    "complaints":    [],
    "data_import_export": [],
}

# ── Guest / Visitor — public-facing only ──
PERMISSIONS_GUEST = {
    "dashboard":     [],
    "safeguarding":  [],
    "members":       [],
    "branches":      ["read"],
    "households":    [],
    "groups":        [],
    "ministries":    ["read"],
    "attendance":    [],
    "followup":      [],
    "care":          [],
    "messaging":     [],
    "events":        ["read"],
    "accounting":    [],
    "donations":     [],
    "pledges":       [],
    "budgets":       [],
    "volunteers":    [],
    "worship":       [],
    "workflows":     [],
    "dashboards":    [],
    "reports":       [],
    "auditlogs":     [],
    "forms":         ["read"],
    "portal":        [],
    "pagebuilder":   [],
    "storage":       [],
    "team":          [],
    "roles":         [],
    "settings":      [],
    "billing":       [],
    "subscription":  [],
    "integrations":  [],
    "sacraments":    [],
    "sermons":       ["read"],
    "request_demos": [],
    "complaints":    [],
    "data_import_export": [],
}

# ═══════════════════════════════════════════════════════════════
# ROLE → PERMISSIONS MAPPING
# ═══════════════════════════════════════════════════════════════

ROLE_PERMISSIONS = {
    ROLE_SYSTEM_OWNER:    PERMISSIONS_SYSTEM_OWNER,
    ROLE_SUPER_ADMIN:     PERMISSIONS_SUPER_ADMIN,
    ROLE_BUSINESS_OWNER:  PERMISSIONS_BUSINESS_OWNER,
    ROLE_PASTOR:          PERMISSIONS_PASTOR,
    ROLE_FINANCE_OFFICER: PERMISSIONS_FINANCE_OFFICER,
    ROLE_CHURCH_ADMIN:    PERMISSIONS_CHURCH_ADMIN,
    ROLE_DEPARTMENT_HEAD: PERMISSIONS_DEPARTMENT_HEAD,
    ROLE_GROUP_LEADER:    PERMISSIONS_GROUP_LEADER,
    ROLE_VOLUNTEER:       PERMISSIONS_VOLUNTEER,
    ROLE_MEMBER:          PERMISSIONS_MEMBER,
    ROLE_GUEST:           PERMISSIONS_GUEST,
}

# Role metadata for UI display
ROLE_METADATA = {
    ROLE_SYSTEM_OWNER:    {"label": "System Owner", "description": "Platform-level access across all businesses, branches, and modules", "level": 0, "is_system": True, "cross_business": True},
    ROLE_SUPER_ADMIN:     {"label": "Super Admin", "description": "Full access across all branches and modules within own business", "level": 1, "is_system": True},
    ROLE_BUSINESS_OWNER:  {"label": "Business Owner", "description": "Full access including billing and subscription management. Cannot be demoted by Super Admin", "level": 1, "is_system": True},
    ROLE_PASTOR:          {"label": "Pastor", "description": "Pastoral and leadership views with approval rights", "level": 2, "is_system": True},
    ROLE_FINANCE_OFFICER: {"label": "Finance Officer", "description": "Full accounting, giving, and budget management access", "level": 3, "is_system": True},
    ROLE_CHURCH_ADMIN:    {"label": "Church Administrator", "description": "Operational management of members, events, volunteers, and communications", "level": 3, "is_system": True},
    ROLE_DEPARTMENT_HEAD: {"label": "Department Head", "description": "Ministry-level management scoped to assigned departments", "level": 4, "is_system": True},
    ROLE_GROUP_LEADER:    {"label": "Group Leader", "description": "Group-scoped management including attendance and follow-up", "level": 5, "is_system": True},
    ROLE_VOLUNTEER:       {"label": "Volunteer", "description": "Self-service access with volunteer schedule and RSVP", "level": 6, "is_system": True},
    ROLE_MEMBER:          {"label": "Member", "description": "Portal and self-service access including giving history and forms", "level": 7, "is_system": True},
    ROLE_GUEST:           {"label": "Guest / Visitor", "description": "Public-facing access to events, ministries, and public forms only", "level": 8, "is_system": True},
    ROLE_CUSTOM:          {"label": "Custom Role", "description": "Custom role with manually configured permissions", "level": 9, "is_system": False},
}

# Only SYSTEM_OWNER bypasses all permission checks
BYPASS_ROLES = [ROLE_SYSTEM_OWNER]

# ═══════════════════════════════════════════════════════════════
# PERMISSION CHECK HELPERS
# ═══════════════════════════════════════════════════════════════

def get_default_permissions(role_key):
    """Get the default permission set for a system role."""
    return ROLE_PERMISSIONS.get(role_key, PERMISSIONS_MEMBER)


def has_permission(user_info, module, action, branch_id=None):
    """
    Check whether a user has a specific permission.

    Args:
        user_info: dict from g.current_user
        module: str — the module key
        action: str — the action
        branch_id: str — optional branch scope check

    Returns:
        bool
    """
    if not user_info:
        return False

    account_type = _safe_account_type(user_info.get("account_type", ""))

    # Only SYSTEM_OWNER bypasses everything
    if account_type in (ROLE_SYSTEM_OWNER, "SYSTEM_OWNER"):
        return True

    # Restricted modules: nobody except SYSTEM_OWNER
    if module in SYSTEM_OWNER_ONLY_MODULES:
        return False

    # Check user-level custom permissions first
    custom_permissions = user_info.get("permissions")
    if custom_permissions and isinstance(custom_permissions, dict):
        module_perms = custom_permissions.get(module, [])
        if action in module_perms:
            if branch_id:
                return _check_branch_scope(user_info, module, action, branch_id)
            return True
        return False

    # Fall back to role-based defaults
    role_key = _resolve_role_key(account_type)
    default_perms = ROLE_PERMISSIONS.get(role_key, PERMISSIONS_MEMBER)
    module_perms = default_perms.get(module, [])

    if action not in module_perms:
        return False

    if branch_id:
        return _check_branch_scope(user_info, module, action, branch_id)

    return True


def _safe_account_type(value):
    """Extract account_type, decrypting if needed, always returns uppercase string."""
    if not value or not isinstance(value, str):
        return ""
    if len(value) <= 30:
        return value.upper()
    try:
        from ..utils.crypt import decrypt_data
        decrypted = decrypt_data(value)
        return decrypted.upper() if decrypted else ""
    except Exception:
        return value.upper()


def _resolve_role_key(account_type):
    """Map account_type string to a role key."""
    mapping = {
        "SYSTEM_OWNER": ROLE_SYSTEM_OWNER,
        "SUPER_ADMIN": ROLE_SUPER_ADMIN,
        "BUSINESS_OWNER": ROLE_BUSINESS_OWNER,
        "PASTOR": ROLE_PASTOR,
        "FINANCE_OFFICER": ROLE_FINANCE_OFFICER,
        "CHURCH_ADMIN": ROLE_CHURCH_ADMIN,
        "ADMIN": ROLE_CHURCH_ADMIN,
        "DEPARTMENT_HEAD": ROLE_DEPARTMENT_HEAD,
        "GROUP_LEADER": ROLE_GROUP_LEADER,
        "VOLUNTEER": ROLE_VOLUNTEER,
        "MEMBER": ROLE_MEMBER,
        "GUEST": ROLE_GUEST,
    }
    return mapping.get(account_type, ROLE_MEMBER)


def _check_branch_scope(user_info, module, action, branch_id):
    """
    Check if the user has permission for a specific branch.
    Users with branch_permissions can have different permissions per branch.
    If no branch_permissions defined, permission is global.
    """
    branch_permissions = user_info.get("branch_permissions")
    if not branch_permissions or not isinstance(branch_permissions, dict):
        return True

    branch_perms = branch_permissions.get(str(branch_id))
    if not branch_perms:
        if branch_permissions.get("all_branches"):
            return True
        return False

    module_perms = branch_perms.get(module, [])
    return action in module_perms


def get_user_permissions(user_info):
    """
    Get the effective permission set for a user.
    Returns custom permissions if set, otherwise role defaults.
    """
    if not user_info:
        return {}

    account_type = _safe_account_type(user_info.get("account_type", ""))

    if account_type in (ROLE_SYSTEM_OWNER, "SYSTEM_OWNER"):
        return PERMISSIONS_SYSTEM_OWNER

    custom_permissions = user_info.get("permissions")
    if custom_permissions and isinstance(custom_permissions, dict):
        return custom_permissions

    role_key = _resolve_role_key(account_type)
    return ROLE_PERMISSIONS.get(role_key, PERMISSIONS_MEMBER)


def get_permitted_modules(user_info):
    """Get list of modules the user has at least read access to."""
    perms = get_user_permissions(user_info)
    return [module for module, actions in perms.items() if "read" in actions]


def validate_permissions_dict(permissions):
    """
    Validate a custom permissions dict.
    Returns (is_valid, errors).
    """
    if not isinstance(permissions, dict):
        return False, ["Permissions must be a dictionary."]

    errors = []
    for module, actions in permissions.items():
        if module not in MODULE_ACTIONS:
            errors.append(f"Unknown module: '{module}'")
            continue
        if not isinstance(actions, list):
            errors.append(f"Module '{module}': actions must be a list")
            continue
        valid_actions = MODULE_ACTIONS[module]
        for action in actions:
            if action not in valid_actions:
                errors.append(
                    f"Module '{module}': invalid action '{action}'. Valid: {valid_actions}"
                )

    return len(errors) == 0, errors


def merge_permissions(base_perms, overrides):
    """
    Merge override permissions on top of base permissions.
    Overrides replace the entire action list for a module.
    """
    merged = {k: list(v) for k, v in base_perms.items()}
    for module, actions in overrides.items():
        if module in MODULE_ACTIONS:
            merged[module] = list(actions)
    return merged


def diff_permissions(role_perms, custom_perms):
    """
    Show differences between a role's default permissions and custom overrides.
    Returns {module: {added: [], removed: []}}.
    """
    diff = {}
    all_modules = set(list(role_perms.keys()) + list(custom_perms.keys()))
    for module in all_modules:
        role_actions = set(role_perms.get(module, []))
        custom_actions = set(custom_perms.get(module, []))
        added = custom_actions - role_actions
        removed = role_actions - custom_actions
        if added or removed:
            diff[module] = {}
            if added:
                diff[module]["added"] = sorted(added)
            if removed:
                diff[module]["removed"] = sorted(removed)
    return diff


def is_system_owner(user_info):
    """Check if user is a SYSTEM_OWNER."""
    if not user_info:
        return False
    account_type = _safe_account_type(user_info.get("account_type", ""))
    return account_type in (ROLE_SYSTEM_OWNER, "SYSTEM_OWNER")


def is_business_owner(user_info):
    """Check if user is a BUSINESS_OWNER."""
    if not user_info:
        return False
    account_type = _safe_account_type(user_info.get("account_type", ""))
    return account_type in (ROLE_BUSINESS_OWNER, "BUSINESS_OWNER")


def can_access_business(user_info, target_business_id):
    """
    Check if the user can access a specific business.
    SYSTEM_OWNER can access any business.
    Others can only access their own.
    """
    if is_system_owner(user_info):
        return True
    return str(user_info.get("business_id")) == str(target_business_id)


def can_manage_role(actor_info, target_role):
    """
    Check if the actor can assign/modify a target role.
    Rules:
      - SYSTEM_OWNER can manage any role
      - BUSINESS_OWNER can manage any role except SYSTEM_OWNER
      - SUPER_ADMIN can manage any role except SYSTEM_OWNER and BUSINESS_OWNER
      - Others cannot manage roles at or above their own level
    """
    actor_type = _safe_account_type(actor_info.get("account_type", ""))
    target_type = target_role.upper() if isinstance(target_role, str) else ""

    if actor_type == "SYSTEM_OWNER":
        return True

    if actor_type == "BUSINESS_OWNER":
        return target_type != "SYSTEM_OWNER"

    if actor_type == "SUPER_ADMIN":
        return target_type not in ("SYSTEM_OWNER", "BUSINESS_OWNER", "SUPER_ADMIN")

    actor_meta = ROLE_METADATA.get(_resolve_role_key(actor_type), {})
    target_meta = ROLE_METADATA.get(_resolve_role_key(target_type), {})
    actor_level = actor_meta.get("level", 99)
    target_level = target_meta.get("level", 99)

    return actor_level < target_level