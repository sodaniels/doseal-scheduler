# instntmny_api/rate_limits.py

from flask import request, g
from flask_limiter.util import get_remote_address

from ..utils.extensions import limiter


# ---------- KEY FUNCTIONS ----------

def _get_request_data():
    """Safely get JSON or form data as a dict."""
    data = request.get_json(silent=True)
    if not data:
        data = request.form or request.values
    return data or {}


def login_key_func():
    """
    Rate-limit per username/phone where possible, else fall back to IP.
    Good for unauthenticated login/initiate endpoints.
    """
    data = _get_request_data()
    username = data.get("username") or data.get("phone")
    if username:
        # Normalize and truncate to prevent abuse with long strings
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
    # Fallback to IP if user not resolved (should rarely happen on protected endpoints)
    return get_remote_address()


# ---------- LOGIN HELPERS ----------

def login_ip_limiter(limit_str="5 per minute; 30 per hour; 100 per day"):
    """
    Per-IP limit for login endpoints.
    
    Improved default: 5 per minute; 30 per hour; 100 per day (per IP)
    
    Rationale:
    - 5/min prevents rapid brute-force while allowing legitimate retries
    - 30/hour stops sustained attacks
    - 100/day catches distributed slow attacks
    """
    return limiter.shared_limit(
        limit_str,
        scope="login-ip",
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message="Too many login attempts from this IP. Please try again later.",
    )


def login_user_limiter(limit_str="3 per 5 minutes; 10 per hour; 20 per day"):
    """
    Per-username/phone limit for login endpoints.
    
    Improved default: 3 per 5 minutes; 10 per hour; 20 per day (per account)
    
    Rationale:
    - 3/5min allows password typos but blocks credential stuffing
    - 10/hour protects against slow attacks on specific accounts
    - 20/day provides strong account protection
    
    CRITICAL: This is your primary defense against credential stuffing!
    """
    return limiter.shared_limit(
        limit_str,
        scope="login-user",
        key_func=login_key_func,
        methods=["POST"],
        error_message="Too many login attempts for this account. Please try again later.",
    )


def login_rate_limiter(limit_str="3 per 5 minutes; 10 per hour; 20 per day"):
    """
    Backwards-compatible helper for login endpoints.

    Returns a per-user shared limit by default.
    
    IMPORTANT: For production, use BOTH decorators:
        decorators = [login_ip_limiter(), login_user_limiter()]
    
    This provides defense-in-depth against both distributed attacks (IP)
    and targeted credential stuffing (username).
    """
    return login_user_limiter(limit_str)


# ---------- REGISTER HELPERS ----------

def register_rate_limiter(limit_str="2 per minute; 5 per hour; 20 per day"):
    """
    Reusable decorator for registration endpoints (per IP).
    
    Improved default: 2 per minute; 5 per hour; 20 per day (per IP)
    
    Rationale:
    - Registration should be infrequent
    - Tighter limits prevent spam account creation
    - 20/day allows legitimate edge cases (offices, schools)
    """
    return limiter.limit(
        limit_str,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message="Too many registration attempts. Please try again later.",
    )


# ---------- OTP HELPERS ----------

def otp_initiate_limiter(limit_str="3 per minute; 10 per hour"):
    """
    For OTP request/send endpoints (per IP).
    
    Default: 3 per minute; 10 per hour (per IP)
    
    Rationale:
    - Prevents SMS/email flooding attacks
    - Protects against OTP enumeration
    - Allows legitimate retry scenarios
    """
    return limiter.shared_limit(
        limit_str,
        scope="otp-initiate",
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message="Too many OTP requests. Please try again later.",
    )


def otp_verify_limiter(limit_str="5 per 5 minutes; 15 per hour"):
    """
    For OTP verification endpoints (per IP).
    
    Default: 5 per 5 minutes; 15 per hour (per IP)
    
    Rationale:
    - Allows slightly more attempts for code entry mistakes
    - Still prevents brute-force of OTP codes
    - Most OTPs expire in 5-10 minutes anyway
    """
    return limiter.shared_limit(
        limit_str,
        scope="otp-verify",
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message="Too many OTP verification attempts. Please try again later.",
    )


def otp_shared_limiter(limit_str="10 per 10 minutes", scope="otp"):
    """
    Legacy shared bucket for OTP endpoints (verify, resend, etc.).
    
    DEPRECATED: Use otp_initiate_limiter() and otp_verify_limiter() instead
    for more granular control.
    
    Suggested default: 10 per 10 minutes (per IP)
    """
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message="Too many OTP requests. Please try again later.",
    )


# ---------- PASSWORD RESET HELPERS ----------

def password_reset_request_limiter(limit_str="2 per minute; 5 per hour; 10 per day"):
    """
    For password reset request endpoints (per IP).
    
    Default: 2 per minute; 5 per hour; 10 per day (per IP)
    
    Rationale:
    - Prevents email/SMS flooding
    - Stops account enumeration attempts
    - Legitimate users rarely need more
    """
    return limiter.shared_limit(
        limit_str,
        scope="pwd-reset-request",
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message="Too many password reset requests. Please try again later.",
    )


def password_reset_verify_limiter(limit_str="5 per 10 minutes; 15 per hour"):
    """
    For password reset verification/completion endpoints (per IP).
    
    Default: 5 per 10 minutes; 15 per hour (per IP)
    """
    return limiter.shared_limit(
        limit_str,
        scope="pwd-reset-verify",
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message="Too many password reset attempts. Please try again later.",
    )

def logout_rate_limiter(
    limit_str="20 per minute; 200 per hour",
    scope="logout-user",
):
    """
    Limits for logout endpoints (per authenticated user).

    Suggested default:
        20 per minute; 200 per hour (per user)

    This is mainly a safety net to catch buggy clients spamming logout,
    not a security control like login rate limiting.
    """
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST"],
        error_message="Too many logout requests. Please try again later.",
    )

# ---------- TRANSACTION / PROTECTED ENDPOINT HELPERS ----------

def transaction_user_limiter(
    limit_str="3 per minute; 20 per hour; 100 per day",
    scope="txn-user",
):
    """
    Limits for transaction-initiating endpoints (send money, withdrawals, etc.)
    per authenticated user.
    
    Improved default: 3 per minute; 20 per hour; 100 per day (per user)
    
    Rationale:
    - Financial transactions should be deliberate, not rapid
    - Tighter limits reduce fraud impact
    - Still allows legitimate high-volume users
    - Consider even stricter limits for high-value transactions
    """
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST"],
        error_message="Too many transaction attempts. Please slow down and try again.",
    )


def transaction_ip_limiter(
    limit_str="10 per minute; 50 per hour",
    scope="txn-ip",
):
    """
    Safety net per-IP limiter for transaction endpoints.
    
    Improved default: 10 per minute; 50 per hour (per IP)
    
    Rationale:
    - Catches compromised accounts from same IP
    - Meant to prevent coordinated attacks
    """
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=default_ip_key_func,
        methods=["POST"],
        error_message="Too many transaction requests from this IP. Please try again later.",
    )


def high_value_transaction_limiter(
    limit_str="1 per minute; 5 per hour; 20 per day",
    scope="txn-high-value",
):
    """
    Extra-strict limits for high-value transactions (per user).
    
    Default: 1 per minute; 5 per hour; 20 per day (per user)
    
    Use this for withdrawals, large transfers, or irreversible operations.
    Apply threshold based on your risk tolerance (e.g., >$1000, >$10000).
    """
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST"],
        error_message="Rate limit exceeded for high-value transactions. Please wait before retrying.",
    )


def read_protected_user_limiter(
    limit_str="30 per minute; 300 per hour",
    scope="read-protected",
):
    """
    Limits for read-only protected endpoints (balances, transaction lists, etc.)
    per authenticated user.
    
    Improved default: 30 per minute; 300 per hour (per user)
    
    Rationale:
    - Tighter than before to prevent data scraping
    - Still generous for legitimate dashboard/app usage
    - Reduces database load from malicious polling
    """
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["GET"],
        error_message="Too many requests. Please slow down and try again.",
    )

def crud_protected_user_limiter(
    limit_str="30 per minute; 300 per hour",
    scope="read-protected",
):
    """
    Limits for read-only protected endpoints (balances, transaction lists, etc.)
    per authenticated user.
    
    Improved default: 30 per minute; 300 per hour (per user)
    
    Rationale:
    - Tighter than before to prevent data scraping
    - Still generous for legitimate dashboard/app usage
    - Reduces database load from malicious polling
    """
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["GET", "POST", "PUT", "PATCH", "DELEE"],
        error_message="Too many requests. Please slow down and try again.",
    )


# ---------- ADMIN/SENSITIVE ENDPOINTS ----------

def admin_action_limiter(limit_str="10 per minute; 50 per hour"):
    """
    For administrative actions (user management, config changes, etc.)
    per authenticated admin user.
    
    Default: 10 per minute; 50 per hour (per admin user)
    """
    return limiter.shared_limit(
        limit_str,
        scope="admin-action",
        key_func=user_key_func,
        methods=["POST", "PUT", "DELETE"],
        error_message="Too many administrative actions. Please slow down.",
    )


# ---------- PUBLIC ENDPOINTS ----------

def public_read_limiter(limit_str="60 per minute; 500 per hour"):
    """
    For public/unauthenticated read endpoints (per IP).
    
    Default: 60 per minute; 500 per hour (per IP)
    
    Adjust based on your public API needs.
    """
    return limiter.limit(
        limit_str,
        key_func=default_ip_key_func,
        methods=["GET"],
        error_message="Too many requests. Please slow down and try again.",
    )


# ---------- GENERIC HELPER ----------

def generic_limiter(limit_str, methods=None, scope=None, key_func=None, error_message=None):
    """
    Generic helper if you want to define custom limits quickly.

    Example:
        decorators = [
            generic_limiter("100 per minute", methods=["GET"], scope="reports"),
        ]
    """
    methods = methods or ["GET", "POST", "PUT", "DELETE"]
    key_func = key_func or default_ip_key_func

    if scope:
        return limiter.shared_limit(
            limit_str,
            scope=scope,
            key_func=key_func,
            methods=methods,
            error_message=error_message,
        )
    else:
        return limiter.limit(
            limit_str,
            key_func=key_func,
            methods=methods,
            error_message=error_message,
        )


# ---------- BENEFICIARY/SENDER HELPERS ----------

def beneficiary_limiter(limit_str="10 per minute; 50 per hour; 200 per day"):
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
    """
    return limiter.shared_limit(
        limit_str,
        scope="beneficiary-ops",
        key_func=user_key_func,
        methods=["GET", "POST", "PATCH", "DELETE"],
        error_message="Too many beneficiary operations. Please slow down and try again.",
    )


def sender_limiter(limit_str="10 per minute; 50 per hour; 200 per day"):
    """
    Combined limiter for sender CRUD operations (per user).
    
    Default: 10 per minute; 50 per hour; 200 per day (per user)
    
    Same rationale as beneficiary_limiter - these are management operations
    that should be tracked together but don't need transaction-level strictness.
    """
    return limiter.shared_limit(
        limit_str,
        scope="sender-ops",
        key_func=user_key_func,
        methods=["GET", "POST", "PATCH", "DELETE"],
        error_message="Too many sender operations. Please slow down and try again.",
    )
    
def people_limiter(limit_str="10 per minute; 50 per hour; 200 per day"):
    """
    Combined limiter for sender CRUD operations (per user).
    
    Default: 10 per minute; 50 per hour; 200 per day (per user)
    
    Same rationale as beneficiary_limiter - these are management operations
    that should be tracked together but don't need transaction-level strictness.
    """
    return limiter.shared_limit(
        limit_str,
        scope=" people-ops",
        key_func=user_key_func,
        methods=["GET", "POST", "PATCH", "DELETE"],
        error_message="Too many sender operations. Please slow down and try again.",
    )

def collection_limiter(limit_str="10 per minute; 50 per hour; 200 per day"):
    """
    Combined limiter for CRUD operations (per user).
    
    Default: 10 per minute; 50 per hour; 200 per day (per user)
    
    Rationale:
    - Covers all HTTP methods (GET, POST, PATCH, DELETE)
    - READ operations (GET): 10/min is reasonable for viewing beneficiaries
    - WRITE operations (POST/PATCH/DELETE): Stricter than pure reads, 
      but more permissive than financial transactions since these are 
      setup/management operations
    - Shares same bucket across all methods to prevent abuse
    """
    return limiter.shared_limit(
        limit_str,
        scope="beneficiary-ops",
        key_func=user_key_func,
        methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        error_message="Too many beneficiary operations. Please slow down and try again.",
    )

def customers_read_limiter(
    limit_str="60 per minute",
    scope="customers-read",
):
    """
    Limits for reading customer data (list, search, fetch) in the POS system.
    Typical user behaviour: frequent but safe.
    
    Suggested:
        60 per minute (per user)
    """
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["GET"],
        error_message="Too many customer lookup requests. Please slow down.",
    )

def customers_write_limiter(
    limit_str="10 per minute; 100 per hour",
    scope="customers-write",
):
    """
    Limits for creating/updating customer records in POS.
    Prevents automated abuse or accidental flooding.

    Suggested:
        10 per minute; 100 per hour (per user)
    """
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST", "PUT"],
        error_message="Too many customer update requests. Please try again later.",
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
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,   # per authenticated user
        methods=["GET"],
        error_message=f"Too many {entity_name} read requests. Please slow down.",
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
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,   # per authenticated user
        methods=["POST", "PUT", "PATCH"],
        error_message=f"Too many {entity_name} write requests. Please try again later.",
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
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,   # per authenticated user
        methods=["DELETE"],
        error_message=f"Too many {entity_name} delete requests. Please try again later.",
    )

def sale_refund_limiter(
    limit_str="5 per minute; 20 per hour",
    scope="sale-refund",
):
    """
    Rate limiting for SALE VOID / REFUND actions.
    
    Refunds are high-risk operations, so limits are stricter.
    
    Suggested defaults:
        5 per minute; 20 per hour (per authenticated user)
    """
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,   # per authenticated user
        methods=["POST"],
        error_message="Too many refund/void attempts. Please try again later.",
    )


def products_read_limiter(
    limit_str: str = "80 per minute; 800 per hour",
    scope: str = "products-read",
):
    """
    Limits for reading/searching products in POS (GET).

    Typical usage:
        - Fast product lookup at the till
        - Search by name, barcode, SKU

    Suggested default:
        80 per minute; 800 per hour (per user)
    """
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,   # per authenticated user
        methods=["GET"],
        error_message="Too many product lookup requests. Please slow down.",
    )


def products_write_limiter(
    limit_str: str = "20 per minute; 200 per hour",
    scope: str = "products-write",
):
    """
    Limits for creating/updating products (POST/PUT/PATCH).

    Typical usage:
        - Backoffice users adding/updating products

    Suggested default:
        20 per minute; 200 per hour (per user)
    """
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["POST", "PUT", "PATCH"],
        error_message="Too many product changes. Please try again later.",
    )


def products_delete_limiter(
    limit_str: str = "10 per minute; 50 per hour",
    scope: str = "products-delete",
):
    """
    Limits for deleting/archiving products (DELETE).

    Suggested default:
        10 per minute; 50 per hour (per user)
    """
    return limiter.shared_limit(
        limit_str,
        scope=scope,
        key_func=user_key_func,
        methods=["DELETE"],
        error_message="Too many product deletions. Please try again later.",
    )





# ---------- USAGE EXAMPLES ----------
"""
Example endpoint configurations:

# Login endpoint (MOST IMPORTANT - use both limiters!)
@app.route('/auth/login', methods=['POST'])
@login_ip_limiter()
@login_user_limiter()
def login():
    pass

# Registration endpoint
@app.route('/auth/register', methods=['POST'])
@register_rate_limiter()
def register():
    pass

# OTP endpoints
@app.route('/auth/otp/send', methods=['POST'])
@otp_initiate_limiter()
def send_otp():
    pass

@app.route('/auth/otp/verify', methods=['POST'])
@otp_verify_limiter()
def verify_otp():
    pass

# Password reset
@app.route('/auth/password/reset/request', methods=['POST'])
@password_reset_request_limiter()
def request_password_reset():
    pass

# Transaction endpoints
@app.route('/transactions/send', methods=['POST'])
@transaction_ip_limiter()
@transaction_user_limiter()
def send_money():
    # For high-value transactions, add additional check:
    # if amount > HIGH_VALUE_THRESHOLD:
    #     high_value_transaction_limiter().test()
    pass

# Read endpoints
@app.route('/account/balance', methods=['GET'])
@read_protected_user_limiter()
def get_balance():
    pass
"""