# app/constants/social_role_permissions.py

# These are the modules your Social Scheduler app will control
PERMISSION_FIELDS_FOR_ADMINS = [
    "dashboard",

    "social_accounts",      # connect/disconnect FB/IG/X accounts
    "posts",                # draft posts
    "scheduled_posts",      # schedule/list/cancel
    "publishing",           # publish now, retry failed
    "media_library",        # upload/delete media assets

    "inbox",                # messages/inbox
    "comments",             # comments/replies

    "analytics",            # view analytics
    "reports",              # export reports

    "team",                 # invite/remove users
    "role",                 # role management itself
    "settings",             # workspace settings
    "billing",              # plan/subscription
    "integrations",         # integrations/settings e.g. Meta OAuth
]

# Actions per module (keep "1"/"0" pattern)
PERMISSION_FIELDS_FOR_ADMIN_ROLE = {
    "dashboard": ["read"],

    "social_accounts": ["read", "create", "update", "delete"],
    "posts": ["read", "create", "update", "delete"],
    "scheduled_posts": ["read", "create", "update", "delete", "cancel"],
    "publishing": ["publish", "retry"],

    "media_library": ["read", "upload", "delete"],

    "inbox": ["read", "reply", "assign", "resolve"],
    "comments": ["read", "reply", "delete"],

    "analytics": ["read"],
    "reports": ["read", "export"],

    "team": ["read", "invite", "remove"],
    "role": ["read", "create", "update", "delete"],

    "settings": ["read", "update"],
    "billing": ["read", "update"],
    "integrations": ["read", "connect", "disconnect"],
}