# utils/url_utils.py

import os

from urllib.parse import urlencode, urlparse, parse_qs, urlunparse


def generate_forgot_password_token(return_url, token):
    """
    Generate forgot password reset URL with token.
    
    Args:
        return_url: Base URL for password reset page
        token: Reset token
        
    Returns:
        Full URL with token parameter
    """
    # Build callback URL
    callback_base = os.getenv("BACK_END_BASE_URL", "http://localhost:9090")
    callback_url = f"{callback_base}/social/api/v1/auth/reset-password/callback"
    
    # Add token and return_url as query parameters
    params = {
        "token": token,
        "return_url": return_url
    }
    
    full_url = f"{callback_url}?{urlencode(params)}"
    return full_url


def generate_return_url_with_payload(base_url, query_params):
    """
    Generate return URL with query parameters.
    
    Args:
        base_url: Base URL
        query_params: Dict of query parameters
        
    Returns:
        Full URL with query parameters
    """
    if not base_url:
        return None
    
    # Parse the base URL
    parsed = urlparse(base_url)
    
    # Get existing query parameters
    existing_params = parse_qs(parsed.query)
    
    # Merge with new parameters
    for key, value in query_params.items():
        existing_params[key] = [str(value)]
    
    # Build new query string
    new_query = urlencode(existing_params, doseq=True)
    
    # Reconstruct URL
    new_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))
    
    return new_url