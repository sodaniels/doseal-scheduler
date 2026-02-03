from datetime import datetime

SERVICE_CODE = {
    "INTERNAL_ERROR": "INTERNAL_ERROR",
    "SUCCESS": "SUCCESS",
    "FAILED": "FAILED",
    "NOT_FOUND": "NOT_FOUND",
    "ALLOWD_IPS": ["127.0.0.1", "::1"],
}

HTTP_STATUS_CODES = {
    "OK": 200,
	"CREATED": 201,
	"NO_CONTENT": 204,
	"BAD_REQUEST": 400,
	"UNAUTHORIZED": 401,
	"PENDING": 411,
	"FORBIDDEN": 403,
	"NOT_FOUND": 404,
	"CONFLICT": 409,
	"VALIDATION_ERROR": 422,
	"INTERNAL_SERVER_ERROR": 500,
	"SERVICE_UNAVAILABLE": 503,
    #CUSTOM CODE
	"DEVICE_IS_NEW_PIN_REQUIRED": 1001,
	"ACCOUNT_PIN_MUST_BE_SET_BY_PRIMARY_DEVICE": 1002,
}

ERROR_MESSAGES = {
	'VALIDATION_FAILED': "Validation failed. Please check your inputs.",
	"UNAUTHORIZED_ACCESS": "You are not authorized to access this resource.",
	"RESOURCE_NOT_FOUND": "The requested resource could not be found.",
	"DUPLICATE_RESOURCE": "The resource already exists.",
	"SERVER_ERROR": "An unexpected error occurred. Please try again later.",
 	"NO_DATA_WAS_FOUND": "No data was found",
    "SUBSCRIPTION_KEY_ERROR": "Access denied due to invalid subscription key. Make sure to provide a valid key for an active subscription."
}

AUTHENTICATION_MESSAGES = {
	'AUTHENTICATION_REQUIRED': "Authentication Required",
	"TOKEN_EXPIRED": "Token expired",
	"INVALID_TOKEN": "Invalid token",
	"DUPLICATE_RESOURCE": "The resource already exists.",
	"SERVER_ERROR": "An unexpected error occurred. Please try again later.",
}

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'docx'}

ACCOUNT_TYPES = { "WALLET": 13, "BANK": 7, "BILLPAY": 10  }

TRANSACTION_STATUS_CODE = {
    "PENDING": 411,
    "SUCCESSFUL": 200,
    "FAILED": 400,
    "REFUNDED": 477,
    "DEBIT_TRANSACTION": "Dr",
    "CREDIT_TRANSACTION": "Cr",
    "STATUS_MESSAGE": "Transaction sent for processing",
    "TRANSACTION_INITIALTED": "Transaction has been initiated successfully",
}

REQUEST_STATUS_CODE = {
    "PENDING": 411,
    "SUCCESSFUL": 200,
    "FAILED": 400,
    "REFUNDED": 477,
    "STATUS_MESSAGE": "Request sent for processing",
    "TRANSACTION_INITIALTED": "Request has been initiated successfully",
}

TRANSACTION_GENERAL_REQUIRED_FIELDS = [
    "sender_full_name", 
    "sender_phone_number", 
    "sender_country", 
    "sender_country_iso_2",
    "beneficiary_id",
    "payment_type",
    "recipient_full_name",
    "recipient_phone_number",
    "recipient_country",
    "recipient_country_iso_2",
    "recipient_currency",
    "recipient_phone_number",
]

TRANSACTION_BANK_REQUIRED_FIELDS = [
    "recipient_full_name", 
    "account_name", 
    "recipient_account_number", 
    "routing_number", 
]

ALLOWED_IPS = [
    '::1',  # localhost IPv6
    '127.0.0.1', # localhost IPv4
    '172.20.0.1', # Docker bridge network IP (host's view)
    '198.199.83.148', #Shop IP
    '146.190.209.15', #Instntmny IP
    '154.160.15.53', #Zeepay network
    '82.28.252.83', #Samuel's house IP,
    '81.134.210.199', #Zeepay UK Network
    '20.121.105.0/24', #Intermex Sandbox IP
    '20.237.11.39', #Intermex Sandbox IP
    '20.185.189.41', #Intermex Production IP
]

AUTOMATED_TEST_USERNAMES = [
    "447450232444",
    "447568983861",
]




PERMISSION_FIELDS_FOR_AGENTS = [
    "send_money",
    "senders",
    "beneficiaries",
    "notice_boards",
    "transactions",
    "billpay_services",
    "dail_transactions",
    "held_transactions",
    "check_rate",
    "system_users",
    "balance",
]


PERMISSION_FIELDS_FOR_ADMINS = [
    "dashboard",

    # Social core
    "socialaccounts",
    "scheduledposts",
    "drafts",
    "calendar",

    # Content
    "medialibrary",
    "contenttemplates",
    "hashtagsets",

    # Engagement
    "inbox",
    "comments",

    # Insights
    "analytics",
    "reports",

    # Workflow
    "approvals",

    # Team / security
    "team",
    "roles",
    "systemuser",

    # Integrations / infra
    "integrations",
    "webhooks",

    # Billing
    "billing",
    "subscription",

    # Audit / config
    "auditlogs",
    "settings",
    "admin",
]

PERMISSION_FIELDS_FOR_ADMIN_ROLE = {

    # --------------------
    # Dashboard
    # --------------------
    "dashboard": ["read"],

    # --------------------
    # Social Accounts
    # --------------------
    "socialaccounts": ["read", "create", "update", "delete"],

    # --------------------
    # Posts / Scheduling
    # --------------------
    "scheduledposts": [
        "read",
        "create",
        "update",
        "delete",
        "approve",
        "cancel",
        "publish",
        "export",
    ],

    "drafts": ["read", "create", "update", "delete"],

    "calendar": ["read"],

    # --------------------
    # Media / Content
    # --------------------
    "medialibrary": ["read", "create", "update", "delete", "upload"],

    "contenttemplates": ["read", "create", "update", "delete"],

    "hashtagsets": ["read", "create", "update", "delete"],

    # --------------------
    # Engagement
    # --------------------
    "inbox": ["read", "reply", "assign", "tag", "resolve"],

    "comments": ["read", "reply", "hide", "delete"],

    # --------------------
    # Analytics
    # --------------------
    "analytics": ["read", "export"],

    "reports": ["read", "create", "export", "schedule"],

    # --------------------
    # Approval flows
    # --------------------
    "approvals": ["read", "create", "update", "delete", "approve", "reject"],

    # --------------------
    # Team / Roles
    # --------------------
    "team": ["read", "create", "update", "delete"],

    "roles": ["read", "create", "update", "delete"],

    "systemuser": ["read", "create", "update", "delete"],

    # --------------------
    # Integrations
    # --------------------
    "integrations": ["read", "create", "update", "delete"],

    "webhooks": ["read", "create", "update", "delete"],

    # --------------------
    # Billing
    # --------------------
    "billing": ["read", "update"],

    "subscription": ["read", "update", "cancel"],

    # --------------------
    # Audit / Settings
    # --------------------
    "auditlogs": ["read", "export"],

    "settings": ["read", "update"],

    "admin": ["read", "create", "update", "delete"],
}

PERMISSION_FIELDS_FOR_AGENT_ROLE = {
    "send_money": ["execute"],
    "senders": ["read","create", "edit", "delete", "export"],
    "beneficiaries": ["read","create", "edit", "delete", "export"],
    "notice_boards": ["read"],
    "transactions": ["read", "export"],
    "billpay_services": ["read"],
    "dail_transactions": ["read", "export"],
    "held_transactions": ["read", "export"],
    "check_rate": ["read"],
    "system_users": ["read", "create", "edit", "delete", "export"],
    "balance": ["read"]
}

ADMIN_PRE_PROCESS_VALIDATION_CHECKS = [
    {
        'key': 'account_created',
        'message': 'This account do not exist. Please contact support.'
    },
   
    {
        'key': 'business_email_verified',
        'message': 'Business email has not been confirmed. Please confirm your email to proceed.'
    },
    {
        'key': 'subscribed_to_package',
        'message': "No package subscription exists for this account. Please subscribe to a pacakge to get started. "
    }
    
]

SUBSCRIBER_PRE_TRANSACTION_VALIDATION_CHECKS = [
    {
        'key': 'account_verified',
        'message': 'The account is not verified. Please contact support.'
    },
    {
        'key': 'choose_pin',
        'message': 'Account PIN is not set. Please use the [PATCH] registration/choose-pin to set the PIN.'
    },
    {
        'key': 'basic_kyc_updated',
        'message': 'Subscribers KYC has not been updated. Please use the [PATCH] registration/basic-kyc to update the KYC.'
    },
    {
        'key': 'account_email_verified',
        'message': 'Account email has not been confirmed. Please ask the user to confirm their email address.'
    },
    {
        'key': 'uploaded_id_front',
        'message': "A valid ID front image has not been uploaded. Please use the [PATCH] registration/documents to upload a valid ID front image."
    },
    {
        'key': 'uploaded_id_back',
        'message': 'A valid ID back image has not been uploaded. Please use the [PATCH] registration/documents to upload a valid ID back image.'
    },
    {
        'key': 'uploaded_id_utility',
        'message': 'A valid Utility bill image has not been uploaded. Please use the [PATCH] registration/documents to upload a valid Utility bill file.'
    },
    # {
    #     'key': 'onboarding_completed',
    #     'message': 'Onboarding is not completed. Please contact support.'
    # }
]

EMAIL_PROVIDER = { "MAILGUN": 'mailgun', "SES": 'ses' }

SMS_PROVIDER = { "TWILIO": 'twilio', "HUBTEL": 'hubtel' }

BILLPAY_BILLER = [
    {
        "COUNTRY": "GH",
        "BILLER_ID": "f0a3d561-5343-44a5-a295-2f536997a276"
    }
]

SYSTEM_USERS = {
    "SYSTEM_OWNER": "system_owner",
    "SUPER_ADMIN": "super_admin",
    "BUSINESS_OWNER": "business_owner",
    "STAFF": "staff",
}

BUSINESS_FIELDS = [
    "account_type", "business_name", "start_date", "business_contact",
    "country", "city", "state", "postcode", "landmark", "currency",
    "website", "alternate_contact_number", "time_zone", "prefix",
    "first_name", "last_name", "username", "account_status"
]

