# instntmny_api/rate_limits.py

from flask import request, g, has_request_context
from flask_limiter.util import get_remote_address

from ..utils.extensions import limiter
from ..utils.logger import Log


# ---------- KEY FUNCTIONS ----------

def _get_request_data():
    """Safely get JSON or form data as a dict."""
    data = request.get_json(silent=True)
    if not data:
        data = request.form or request.values
    return data or {}


def _get_client_ip():
    """Safely get client IP, returns 'unknown' if outside request context."""
    if has_request_context():
        return get_remote_address() or "unknown"
    return "unknown"


def login_key_func():
    """
    Rate-limit per username/phone where possible, else fall back to IP.
    Good for unauthenticated login/initiate endpoints.
    """
    data = _get_request_data()
    username = data.get("username") or data.get("phone")
    if username:
        return f"login:{str(username).lower()[:100]}"
    return get_remote_address()


def default_ip_key_func():
    """Standard per-IP rate limiting."""
    return get_remote_address()


def user_key_func():
    """
    Rate-limit per authenticated user.

    NOTE: Adjust this to match your auth implementation.
    Common patterns:
      - g.current_user.id
      - g.user.id
      - g.jwt_payload["sub"]
    """
    user_id = getattr(g, "current_user_id", None) or getattr(getattr(g, "current_user", None), "id", None)
    if user_id is not None:
        return f"user:{user_id}"
    return get_remote_address()


# ---------- RATE LIMIT BREACH HANDLER ----------

def log_rate_limit_breach(request_limit):
    """
    Callback when a rate limit is breached.
    
    Register this with your limiter in extensions.py:
        limiter = Limiter(
            key_func=get_remote_address,
            on_breach=log_rate_limit_breach,
        )
    """
    client_ip = _get_client_ip()
    user_id = getattr(g, "current_user_id", None) or "anonymous"
    endpoint = request.endpoint or "unknown"
    method = request.method
    path = request.path
    
    Log.warning(
        f"[rate_limits.py][RATE_LIMIT_BREACH][{client_ip}] "
        f"user={user_id}, limit={request_limit}, method={method}, path={path}, endpoint={endpoint}"
    )


# ---------- LOGIN HELPERS ----------

def login_ip_limiter(
    entity_name: str = "login",
    limit_str: str = "5 per minute; 30 per hour; 100 per day",
    scope: str | None = None,
):
    """
    Per-IP limit for login/authentication endpoints.
    
    Default: 5 per minute; 30 per hour; 100 per day (per IP)
    
    Rationale:
    - 5/min prevents rapid brute-force while allowing legitimate retries
    - 30/hour stops sustained attacks
    - 100/day catches distributed slow attacks
    
    Example:
        decorators = [login_ip_limiter("admin-login")]
        decorators = [login_ip_limiter("api-auth", limit_str="3 per minute; 20 per hour")]
    """
    scope = scope or f"{entity_name}-ip"
    error_message = f"Too many {entity_name} attempts from this IP. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message=error_message,
    )


def login_user_limiter(
    entity_name: str = "login",
    limit_str: str = "3 per 5 minutes; 10 per hour; 20 per day",
    scope: str | None = None,
):
    """
    Per-username/phone limit for login endpoints.
    
    Default: 3 per 5 minutes; 10 per hour; 20 per day (per account)
    
    Rationale:
    - 3/5min allows password typos but blocks credential stuffing
    - 10/hour protects against slow attacks on specific accounts
    - 20/day provides strong account protection
    
    CRITICAL: This is your primary defense against credential stuffing!
    
    Example:
        decorators = [login_user_limiter("user-login")]
        decorators = [login_user_limiter("admin-login", limit_str="2 per 5 minutes; 5 per hour")]
    """
    scope = scope or f"{entity_name}-user"
    error_message = f"Too many {entity_name} attempts for this account. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=login_key_func,
        methods=["POST"],
        error_message=error_message,
    )


def login_rate_limiter(
    entity_name: str = "login",
    limit_str: str = "3 per 5 minutes; 10 per hour; 20 per day",
):
    """
    Backwards-compatible helper for login endpoints.

    Returns a per-user shared limit by default.
    
    IMPORTANT: For production, use BOTH decorators:
        decorators = [login_ip_limiter(), login_user_limiter()]
    
    This provides defense-in-depth against both distributed attacks (IP)
    and targeted credential stuffing (username).
    """
    return login_user_limiter(entity_name, limit_str)


# ---------- REGISTER HELPERS ----------

def register_rate_limiter(
    entity_name: str = "registration",
    limit_str: str = "2 per minute; 5 per hour; 20 per day",
    scope: str | None = None,
):
    """
    Reusable decorator for registration/signup endpoints (per IP).
    
    Default: 2 per minute; 5 per hour; 20 per day (per IP)
    
    Rationale:
    - Registration should be infrequent
    - Tighter limits prevent spam account creation
    - 20/day allows legitimate edge cases (offices, schools)
    
    Example:
        decorators = [register_rate_limiter("user-signup")]
        decorators = [register_rate_limiter("merchant-registration", limit_str="1 per minute; 3 per hour")]
    """
    scope = scope or f"{entity_name}-ip"
    error_message = f"Too many {entity_name} attempts. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message=error_message,
    )


# ---------- OTP HELPERS ----------

def otp_initiate_limiter(
    entity_name: str = "OTP",
    limit_str: str = "3 per minute; 10 per hour",
    scope: str | None = None,
):
    """
    For OTP request/send endpoints (per IP).
    
    Default: 3 per minute; 10 per hour (per IP)
    
    Rationale:
    - Prevents SMS/email flooding attacks
    - Protects against OTP enumeration
    - Allows legitimate retry scenarios
    
    Example:
        decorators = [otp_initiate_limiter("sms-otp")]
        decorators = [otp_initiate_limiter("email-otp", limit_str="2 per minute; 8 per hour")]
    """
    scope = scope or f"{entity_name}-initiate"
    error_message = f"Too many {entity_name} requests. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message=error_message,
    )


def otp_verify_limiter(
    entity_name: str = "OTP verification",
    limit_str: str = "5 per 5 minutes; 15 per hour",
    scope: str | None = None,
):
    """
    For OTP verification endpoints (per IP).
    
    Default: 5 per 5 minutes; 15 per hour (per IP)
    
    Rationale:
    - Allows slightly more attempts for code entry mistakes
    - Still prevents brute-force of OTP codes
    - Most OTPs expire in 5-10 minutes anyway
    
    Example:
        decorators = [otp_verify_limiter("sms-otp-verify")]
        decorators = [otp_verify_limiter("email-otp-verify", limit_str="3 per 5 minutes; 10 per hour")]
    """
    scope = scope or f"{entity_name}-verify"
    error_message = f"Too many {entity_name} attempts. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message=error_message,
    )


def otp_shared_limiter(
    entity_name: str = "OTP",
    limit_str: str = "10 per 10 minutes",
    scope: str | None = None,
):
    """
    Legacy shared bucket for OTP endpoints (verify, resend, etc.).
    
    DEPRECATED: Use otp_initiate_limiter() and otp_verify_limiter() instead
    for more granular control.
    
    Default: 10 per 10 minutes (per IP)
    """
    scope = scope or f"{entity_name}-shared"
    error_message = f"Too many {entity_name} requests. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message=error_message,
    )


# ---------- PASSWORD RESET HELPERS ----------

def password_reset_request_limiter(
    entity_name: str = "password reset",
    limit_str: str = "2 per minute; 5 per hour; 10 per day",
    scope: str | None = None,
):
    """
    For password reset request endpoints (per IP).
    
    Default: 2 per minute; 5 per hour; 10 per day (per IP)
    
    Rationale:
    - Prevents email/SMS flooding
    - Stops account enumeration attempts
    - Legitimate users rarely need more
    
    Example:
        decorators = [password_reset_request_limiter("password-reset")]
        decorators = [password_reset_request_limiter("pin-reset", limit_str="1 per minute; 3 per hour")]
    """
    scope = scope or f"{entity_name}-request"
    error_message = f"Too many {entity_name} requests. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message=error_message,
    )


def password_reset_verify_limiter(
    entity_name: str = "password reset",
    limit_str: str = "5 per 10 minutes; 15 per hour",
    scope: str | None = None,
):
    """
    For password reset verification/completion endpoints (per IP).
    
    Default: 5 per 10 minutes; 15 per hour (per IP)
    
    Example:
        decorators = [password_reset_verify_limiter("password-reset-verify")]
        decorators = [password_reset_verify_limiter("pin-reset-verify", limit_str="3 per 10 minutes")]
    """
    scope = scope or f"{entity_name}-verify"
    error_message = f"Too many {entity_name} attempts. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message=error_message,
    )


def logout_rate_limiter(
    entity_name: str = "logout",
    limit_str: str = "20 per minute; 200 per hour",
    scope: str | None = None,
):
    """
    Limits for logout endpoints (per authenticated user).

    Default: 20 per minute; 200 per hour (per user)

    This is mainly a safety net to catch buggy clients spamming logout,
    not a security control like login rate limiting.
    
    Example:
        decorators = [logout_rate_limiter("user-logout")]
        decorators = [logout_rate_limiter("api-logout", limit_str="10 per minute")]
    """
    scope = scope or f"{entity_name}-user"
    error_message = f"Too many {entity_name} requests. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST"],
        error_message=error_message,
    )


# ---------- TRANSACTION / PROTECTED ENDPOINT HELPERS ----------

def transaction_user_limiter(
    entity_name: str = "transaction",
    limit_str: str = "3 per minute; 20 per hour; 100 per day",
    scope: str | None = None,
):
    """
    Limits for transaction-initiating endpoints (send money, withdrawals, etc.)
    per authenticated user.
    
    Default: 3 per minute; 20 per hour; 100 per day (per user)
    
    Rationale:
    - Financial transactions should be deliberate, not rapid
    - Tighter limits reduce fraud impact
    - Still allows legitimate high-volume users
    - Consider even stricter limits for high-value transactions
    
    Example:
        decorators = [transaction_user_limiter("send-money")]
        decorators = [transaction_user_limiter("withdrawal", limit_str="2 per minute; 10 per hour")]
    """
    scope = scope or f"{entity_name}-user"
    error_message = f"Too many {entity_name} attempts. Please slow down and try again."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST"],
        error_message=error_message,
    )


def transaction_ip_limiter(
    entity_name: str = "transaction",
    limit_str: str = "10 per minute; 50 per hour",
    scope: str | None = None,
):
    """
    Safety net per-IP limiter for transaction endpoints.
    
    Default: 10 per minute; 50 per hour (per IP)
    
    Rationale:
    - Catches compromised accounts from same IP
    - Meant to prevent coordinated attacks
    
    Example:
        decorators = [transaction_ip_limiter("send-money")]
        decorators = [transaction_ip_limiter("withdrawal", limit_str="5 per minute; 30 per hour")]
    """
    scope = scope or f"{entity_name}-ip"
    error_message = f"Too many {entity_name} requests from this IP. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message=error_message,
    )


def high_value_transaction_limiter(
    entity_name: str = "high-value transaction",
    limit_str: str = "1 per minute; 5 per hour; 20 per day",
    scope: str | None = None,
):
    """
    Extra-strict limits for high-value transactions (per user).
    
    Default: 1 per minute; 5 per hour; 20 per day (per user)
    
    Use this for withdrawals, large transfers, or irreversible operations.
    Apply threshold based on your risk tolerance (e.g., >$1000, >$10000).
    
    Example:
        decorators = [high_value_transaction_limiter("large-withdrawal")]
        decorators = [high_value_transaction_limiter("wire-transfer", limit_str="1 per 5 minutes; 3 per hour")]
    """
    scope = scope or f"{entity_name}-high-value"
    error_message = f"Rate limit exceeded for {entity_name}. Please wait before retrying."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST"],
        error_message=error_message,
    )


def read_protected_user_limiter(
    entity_name: str = "data",
    limit_str: str = "30 per minute; 300 per hour",
    scope: str | None = None,
):
    """
    Limits for read-only protected endpoints (balances, transaction lists, etc.)
    per authenticated user.
    
    Default: 30 per minute; 300 per hour (per user)
    
    Rationale:
    - Tighter than before to prevent data scraping
    - Still generous for legitimate dashboard/app usage
    - Reduces database load from malicious polling
    
    Example:
        decorators = [read_protected_user_limiter("balance")]
        decorators = [read_protected_user_limiter("transaction-history", limit_str="20 per minute")]
    """
    scope = scope or f"{entity_name}-read-protected"
    error_message = f"Too many {entity_name} requests. Please slow down and try again."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["GET"],
        error_message=error_message,
    )


def crud_protected_user_limiter(
    entity_name: str = "resource",
    limit_str: str = "30 per minute; 300 per hour",
    scope: str | None = None,
):
    """
    Limits for CRUD operations on protected endpoints per authenticated user.
    
    Default: 30 per minute; 300 per hour (per user)
    
    Rationale:
    - Covers all HTTP methods for general protected resources
    - Still generous for legitimate dashboard/app usage
    - Reduces database load from malicious requests
    
    Example:
        decorators = [crud_protected_user_limiter("settings")]
        decorators = [crud_protected_user_limiter("preferences", limit_str="20 per minute")]
    """
    scope = scope or f"{entity_name}-crud-protected"
    error_message = f"Too many {entity_name} requests. Please slow down and try again."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        error_message=error_message,
    )


# ---------- ADMIN/SENSITIVE ENDPOINTS ----------

def admin_action_limiter(
    entity_name: str = "admin action",
    limit_str: str = "10 per minute; 50 per hour",
    scope: str | None = None,
):
    """
    For administrative actions (user management, config changes, etc.)
    per authenticated admin user.
    
    Default: 10 per minute; 50 per hour (per admin user)
    
    Example:
        decorators = [admin_action_limiter("user-management")]
        decorators = [admin_action_limiter("config-change", limit_str="5 per minute; 20 per hour")]
    """
    scope = scope or f"{entity_name}-admin"
    error_message = f"Too many {entity_name} requests. Please slow down."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST", "PUT", "DELETE"],
        error_message=error_message,
    )


# ---------- PUBLIC ENDPOINTS ----------

def public_read_limiter(
    entity_name: str = "public resource",
    limit_str: str = "60 per minute; 500 per hour",
    scope: str | None = None,
):
    """
    For public/unauthenticated read endpoints (per IP).
    
    Default: 60 per minute; 500 per hour (per IP)
    
    Adjust based on your public API needs.
    
    Example:
        decorators = [public_read_limiter("exchange-rates")]
        decorators = [public_read_limiter("public-api", limit_str="30 per minute; 300 per hour")]
    """
    scope = scope or f"{entity_name}-public"
    error_message = f"Too many {entity_name} requests. Please slow down and try again."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["GET"],
        error_message=error_message,
    )


# ---------- GENERIC HELPER ----------

def generic_limiter(
    entity_name: str = "request",
    limit_str: str = "30 per minute",
    methods: list | None = None,
    scope: str | None = None,
    key_func=None,
):
    """
    Generic helper if you want to define custom limits quickly.

    Example:
        decorators = [
            generic_limiter("reports", "100 per minute", methods=["GET"]),
        ]
    """
    methods = methods or ["GET", "POST", "PUT", "DELETE"]
    key_func = key_func or default_ip_key_func
    scope = scope or f"{entity_name}-generic"
    error_message = f"Too many {entity_name} requests. Please try again later."

    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=key_func,
        methods=methods,
        error_message=error_message,
    )


# ---------- BENEFICIARY/SENDER HELPERS ----------

def beneficiary_limiter(
    entity_name: str = "beneficiary",
    limit_str: str = "10 per minute; 50 per hour; 200 per day",
    scope: str | None = None,
):
    """
    Combined limiter for beneficiary/sender CRUD operations (per user).
    
    Default: 10 per minute; 50 per hour; 200 per day (per user)
    
    Rationale:
    - Covers all HTTP methods (GET, POST, PATCH, DELETE)
    - READ operations (GET): 10/min is reasonable for viewing beneficiaries
    - WRITE operations (POST/PATCH/DELETE): Stricter than pure reads, 
      but more permissive than financial transactions since these are 
      setup/management operations
    - Shares same bucket across all methods to prevent abuse
    
    Example:
        decorators = [beneficiary_limiter("beneficiary")]
        decorators = [beneficiary_limiter("recipient", limit_str="5 per minute; 30 per hour")]
    """
    scope = scope or f"{entity_name}-ops"
    error_message = f"Too many {entity_name} operations. Please slow down and try again."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["GET", "POST", "PATCH", "DELETE"],
        error_message=error_message,
    )


def sender_limiter(
    entity_name: str = "sender",
    limit_str: str = "10 per minute; 50 per hour; 200 per day",
    scope: str | None = None,
):
    """
    Combined limiter for sender CRUD operations (per user).
    
    Default: 10 per minute; 50 per hour; 200 per day (per user)
    
    Same rationale as beneficiary_limiter - these are management operations
    that should be tracked together but don't need transaction-level strictness.
    
    Example:
        decorators = [sender_limiter("sender")]
        decorators = [sender_limiter("remitter", limit_str="5 per minute; 30 per hour")]
    """
    scope = scope or f"{entity_name}-ops"
    error_message = f"Too many {entity_name} operations. Please slow down and try again."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["GET", "POST", "PATCH", "DELETE"],
        error_message=error_message,
    )


def people_limiter(
    entity_name: str = "people",
    limit_str: str = "10 per minute; 50 per hour; 200 per day",
    scope: str | None = None,
):
    """
    Combined limiter for people CRUD operations (per user).
    
    Default: 10 per minute; 50 per hour; 200 per day (per user)
    
    Same rationale as beneficiary_limiter - these are management operations
    that should be tracked together but don't need transaction-level strictness.
    
    Example:
        decorators = [people_limiter("contacts")]
        decorators = [people_limiter("customers", limit_str="20 per minute; 100 per hour")]
    """
    scope = scope or f"{entity_name}-ops"
    error_message = f"Too many {entity_name} operations. Please slow down and try again."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["GET", "POST", "PATCH", "DELETE"],
        error_message=error_message,
    )


def collection_limiter(
    entity_name: str = "collection",
    limit_str: str = "10 per minute; 50 per hour; 200 per day",
    scope: str | None = None,
):
    """
    Combined limiter for CRUD operations (per user).
    
    Default: 10 per minute; 50 per hour; 200 per day (per user)
    
    Rationale:
    - Covers all HTTP methods (GET, POST, PATCH, PUT, DELETE)
    - READ operations (GET): 10/min is reasonable for viewing collections
    - WRITE operations (POST/PATCH/PUT/DELETE): Stricter than pure reads, 
      but more permissive than financial transactions since these are 
      setup/management operations
    - Shares same bucket across all methods to prevent abuse
    
    Example:
        decorators = [collection_limiter("inventory")]
        decorators = [collection_limiter("catalog", limit_str="20 per minute; 100 per hour")]
    """
    scope = scope or f"{entity_name}-ops"
    error_message = f"Too many {entity_name} operations. Please slow down and try again."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        error_message=error_message,
    )


def customers_read_limiter(
    entity_name: str = "customer",
    limit_str: str = "60 per minute",
    scope: str | None = None,
):
    """
    Limits for reading customer data (list, search, fetch) in the POS system.
    Typical user behaviour: frequent but safe.
    
    Default: 60 per minute (per user)
    
    Example:
        decorators = [customers_read_limiter("customer")]
        decorators = [customers_read_limiter("client", limit_str="30 per minute")]
    """
    scope = scope or f"{entity_name}-read"
    error_message = f"Too many {entity_name} lookup requests. Please slow down."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["GET"],
        error_message=error_message,
    )


def customers_write_limiter(
    entity_name: str = "customer",
    limit_str: str = "10 per minute; 100 per hour",
    scope: str | None = None,
):
    """
    Limits for creating/updating customer records in POS.
    Prevents automated abuse or accidental flooding.

    Default: 10 per minute; 100 per hour (per user)
    
    Example:
        decorators = [customers_write_limiter("customer")]
        decorators = [customers_write_limiter("client", limit_str="5 per minute; 50 per hour")]
    """
    scope = scope or f"{entity_name}-write"
    error_message = f"Too many {entity_name} update requests. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST", "PUT"],
        error_message=error_message,
    )


# ---------- GENERIC CRUD HELPERS FOR POS ENTITIES ----------

def crud_read_limiter(
    entity_name: str,
    limit_str: str = "60 per minute",
    scope: str | None = None,
):
    """
    Generic limiter for READ (GET) operations on POS entities.

    Example:
        decorators = [crud_read_limiter("brand")]
    """
    scope = scope or f"{entity_name}-read"
    error_message = f"Too many {entity_name} read requests. Please slow down."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["GET"],
        error_message=error_message,
    )


def crud_write_limiter(
    entity_name: str,
    limit_str: str = "20 per minute; 200 per hour",
    scope: str | None = None,
):
    """
    Generic limiter for WRITE (POST/PUT/PATCH) operations on POS entities.

    Example:
        decorators = [crud_write_limiter("brand")]
    """
    scope = scope or f"{entity_name}-write"
    error_message = f"Too many {entity_name} write requests. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST", "PUT", "PATCH"],
        error_message=error_message,
    )


def crud_delete_limiter(
    entity_name: str,
    limit_str: str = "10 per minute; 50 per hour",
    scope: str | None = None,
):
    """
    Generic limiter for DELETE operations on POS entities.

    Example:
        decorators = [crud_delete_limiter("brand")]
    """
    scope = scope or f"{entity_name}-delete"
    error_message = f"Too many {entity_name} delete requests. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["DELETE"],
        error_message=error_message,
    )


def sale_refund_limiter(
    entity_name: str = "refund",
    limit_str: str = "5 per minute; 20 per hour",
    scope: str | None = None,
):
    """
    Rate limiting for SALE VOID / REFUND actions.
    
    Refunds are high-risk operations, so limits are stricter.
    
    Default: 5 per minute; 20 per hour (per authenticated user)
    
    Example:
        decorators = [sale_refund_limiter("sale-refund")]
        decorators = [sale_refund_limiter("void", limit_str="3 per minute; 15 per hour")]
    """
    scope = scope or f"{entity_name}-ops"
    error_message = f"Too many {entity_name} attempts. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST"],
        error_message=error_message,
    )


def products_read_limiter(
    entity_name: str = "product",
    limit_str: str = "80 per minute; 800 per hour",
    scope: str | None = None,
):
    """
    Limits for reading/searching products in POS (GET).

    Typical usage:
        - Fast product lookup at the till
        - Search by name, barcode, SKU

    Default: 80 per minute; 800 per hour (per user)
    
    Example:
        decorators = [products_read_limiter("product")]
        decorators = [products_read_limiter("inventory-item", limit_str="60 per minute")]
    """
    scope = scope or f"{entity_name}-read"
    error_message = f"Too many {entity_name} lookup requests. Please slow down."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["GET"],
        error_message=error_message,
    )


def products_write_limiter(
    entity_name: str = "product",
    limit_str: str = "20 per minute; 200 per hour",
    scope: str | None = None,
):
    """
    Limits for creating/updating products (POST/PUT/PATCH).

    Typical usage:
        - Backoffice users adding/updating products

    Default: 20 per minute; 200 per hour (per user)
    
    Example:
        decorators = [products_write_limiter("product")]
        decorators = [products_write_limiter("inventory-item", limit_str="10 per minute")]
    """
    scope = scope or f"{entity_name}-write"
    error_message = f"Too many {entity_name} changes. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST", "PUT", "PATCH"],
        error_message=error_message,
    )


def products_delete_limiter(
    entity_name: str = "product",
    limit_str: str = "10 per minute; 50 per hour",
    scope: str | None = None,
):
    """
    Limits for deleting/archiving products (DELETE).

    Default: 10 per minute; 50 per hour (per user)
    
    Example:
        decorators = [products_delete_limiter("product")]
        decorators = [products_delete_limiter("inventory-item", limit_str="5 per minute")]
    """
    scope = scope or f"{entity_name}-delete"
    error_message = f"Too many {entity_name} deletions. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["DELETE"],
        error_message=error_message,
    )


def profile_retrieval_limiter(
    entity_name: str = "profile",
    limit_str: str = "60 per minute; 600 per hour",
    scope: str | None = None,
):
    """
    Limits for user profile/data retrieval endpoints (/me, /profile, /account).
    
    Default: 60 per minute; 600 per hour (per user)
    
    Rationale:
    - Read-only endpoint, so more permissive than write operations
    - Allows frequent polling for profile updates (e.g., dashboard refreshes)
    - Still prevents abuse from buggy clients or scraping attempts
    - Authenticated users only, keyed by user ID
    
    Example:
        decorators = [profile_retrieval_limiter("user-profile")]
        decorators = [profile_retrieval_limiter("account-settings", limit_str="30 per minute")]
    """
    scope = scope or f"{entity_name}-retrieval"
    error_message = f"Too many {entity_name} requests. Please try again shortly."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["GET"],
        error_message=error_message,
    )


def subscription_payment_limiter(
    entity_name: str = "subscription payment",
    limit_str: str = "3 per hour; 10 per day",
    scope: str | None = None,
):
    """
    Limits for subscription payment initiation endpoints (per authenticated user).
    
    Default: 3 per hour; 10 per day (per user)
    
    Rationale:
    - Subscription payments are infrequent (monthly/yearly)
    - 3/hour allows for payment failures and retries
    - 10/day is generous for edge cases (multiple failed attempts, plan changes)
    - Prevents abuse while not blocking legitimate retry scenarios
    
    Example:
        decorators = [subscription_payment_limiter("subscription")]
        decorators = [subscription_payment_limiter("plan-upgrade", limit_str="2 per hour; 5 per day")]
    """
    scope = scope or f"{entity_name}-initiate"
    error_message = f"Too many {entity_name} attempts. Please try again later or contact support."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST"],
        error_message=error_message,
    )

def subscription_payment_ip_limiter(
    entity_name: str = "subscription payment",
    limit_str: str = "10 per hour; 30 per day",
    scope: str | None = None,
):
    """
    Per-IP safety net for subscription payment endpoints.
    
    Default: 10 per hour; 30 per day (per IP)
    
    Rationale:
    - Catches card testing or fraud from single IP
    - Allows multiple users from same network (office, household)
    - Secondary defense layer
    
    Example:
        decorators = [subscription_payment_ip_limiter("subscription"), subscription_payment_limiter("subscription")]
    """
    scope = scope or f"{entity_name}-initiate-ip"
    error_message = f"Too many {entity_name} requests from this location. Please try again later."
    
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message=error_message,
    )

# ---------- SOCIAL AUTH HELPERS ----------

def social_login_initiator_limiter(
    provider: str = "social",
    limit_str: str = "10 per minute; 30 per hour; 100 per day",
    scope: str | None = None,
):
    """
    Reusable decorator for social login INITIATION endpoints (per IP).
    Covers: /auth/{provider}/login, /auth/{provider}/business/login, etc.

    Default: 10 per minute; 30 per hour; 100 per day (per IP)

    Rationale:
    - Initiation just builds a redirect URL (cheap), but abuse can
      flood Redis with state keys and trigger unnecessary OAuth flows.
    - Higher ceiling than registration since users may click "Login
      with X" several times in one session.
    - 100/day handles shared IPs (offices, schools).

    Example:
        decorators = [social_login_initiator_limiter("linkedin")]
        decorators = [social_login_initiator_limiter("google", limit_str="5 per minute; 20 per hour")]
    """
    scope = scope or f"{provider}-social-login-initiate-ip"
    error_message = f"Too many {provider} login attempts. Please try again later."

    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["GET"],
        error_message=error_message,
    )


def social_login_callback_limiter(
    provider: str = "social",
    limit_str: str = "10 per minute; 30 per hour; 100 per day",
    scope: str | None = None,
):
    """
    Reusable decorator for social login CALLBACK endpoints (per IP).
    Covers: /auth/{provider}/callback, /auth/{provider}/business/callback, etc.

    Default: 10 per minute; 30 per hour; 100 per day (per IP)

    Rationale:
    - Callbacks are heavy: token exchange + profile fetch + DB writes.
    - Matching the initiator limit is intentional — each initiation
      should produce at most one callback, so limits stay in sync.
    - Tight per-minute window guards against replayed/forged callbacks.

    Example:
        decorators = [social_login_callback_limiter("linkedin")]
        decorators = [social_login_callback_limiter("facebook", limit_str="5 per minute; 20 per hour")]
    """
    scope = scope or f"{provider}-social-login-callback-ip"
    error_message = f"Too many {provider} login callback attempts. Please try again later."

    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["GET"],
        error_message=error_message,
    )

#--------TRIAL ENDPOINTS--------------
def trial_start_limiter(
    limit_str: str = "1 per day; 2 per hour; 5 per minute",
    scope: str | None = None,
):
    """
    Rate limiter for starting a trial subscription.

    Covers:
    - POST /subscription/trial/start

    Default:
    - 1 per day (hard business rule)
    - 2 per hour (retry protection)
    - 5 per minute (burst protection)

    Rationale:
    - Trial abuse prevention
    - Protects against logic bugs & replay
    - IP-based is acceptable since token_required is enforced
    """
    scope = scope or "trial-start-ip"
    error_message = "Too many trial start attempts. Please try again later."

    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message=error_message,
    )

def trial_status_limiter(
    limit_str: str = "60 per minute; 1000 per day",
    scope: str | None = None,
):
    """
    Rate limiter for checking trial status.

    Covers:
    - GET /subscription/trial/status

    Rationale:
    - Read-only
    - Safe to allow polling from frontend
    """
    scope = scope or "trial-status-ip"
    error_message = "Too many trial status checks. Please slow down."

    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["GET"],
        error_message=error_message,
    )

def trial_convert_limiter(
    limit_str: str = "3 per hour; 10 per day",
    scope: str | None = None,
):
    """
    Rate limiter for converting a trial to a paid subscription.

    Covers:
    - POST /subscription/trial/convert

    Rationale:
    - Payment-adjacent endpoint
    - Prevents double-submit & replay
    - Keeps conversion idempotent
    """
    scope = scope or "trial-convert-ip"
    error_message = "Too many subscription conversion attempts. Please try again later."

    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message=error_message,
    )

def subscription_packages_limiter(
    limit_str: str = "120 per minute; 2000 per day",
    scope: str | None = None,
):
    """
    Rate limiter for listing available subscription packages.

    Covers:
    - GET /subscription/packages

    Rationale:
    - Mostly static data
    - Used by pricing & onboarding screens
    """
    scope = scope or "subscription-packages-ip"
    error_message = "Too many package requests. Please try again later."

    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["GET"],
        error_message=error_message,
    )

def trial_cancel_limiter(
    limit_str: str = "2 per hour; 5 per day",
    scope: str | None = None,
):
    """
    Rate limiter for cancelling a trial subscription.

    Covers:
    - POST /subscription/trial/cancel

    Rationale:
    - State-changing action
    - Prevents rapid toggle / replay
    - Per-business/user scoped to avoid abuse across IPs
    - Trial cancellation should be deliberate and infrequent
    """
    scope = scope or "trial-cancel-business"
    error_message = "Too many trial cancellation attempts. Please try again later."

    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,   # 🔐 per authenticated user/business
        methods=["POST"],
        error_message=error_message,
    )
































