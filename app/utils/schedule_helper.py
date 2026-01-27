
import os
import json
import secrets

import requests
from flask.views import MethodView
from flask import request, jsonify, redirect, g
from flask_smorest import Blueprint
from datetime import datetime, timezone
from .logger import Log
from ..constants.service_code import HTTP_STATUS_CODES
from .redis import get_redis, set_redis_with_expiry, remove_redis



# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _safe_json_load(raw, default=None):
    if default is None:
        default = {}
    try:
        if raw is None:
            return default
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if isinstance(raw, (dict, list)):
            return raw
        return json.loads(raw)
    except Exception:
        return default


def _require_env(key: str, log_tag: str):
    val = os.getenv(key)
    if not val:
        Log.info(f"{log_tag} ENV missing: {key}")
    return val


def _exchange_code_for_token(*, code: str, redirect_uri: str, log_tag: str) -> dict:
    """
    Exchange OAuth code for Meta user access token.
    """
    meta_app_id = _require_env("META_APP_ID", log_tag)
    meta_app_secret = _require_env("META_APP_SECRET", log_tag)
    if not meta_app_id or not meta_app_secret:
        raise Exception("META_APP_ID or META_APP_SECRET not set")

    token_url = os.getenv(
        "FACEBOOK_GRAPH_OAUTH_ACCESS_TOKEN_URL",
        "https://graph.facebook.com/v20.0/oauth/access_token"
    )

    payload = {
        "client_id": meta_app_id,
        "client_secret": meta_app_secret,
        "redirect_uri": redirect_uri,
        "code": code,
    }

    resp = requests.get(token_url, params=payload, timeout=30)
    data = resp.json()
    if resp.status_code != HTTP_STATUS_CODES["OK"]:
        raise Exception(f"Token exchange failed: {data}")
    if not data.get("access_token"):
        raise Exception(f"Token exchange missing access_token: {data}")

    return data


def _store_state(owner: dict, state: str, provider: str, ttl_seconds: int = 600):
    """
    Store state in redis:
      key: <provider>_oauth_state:<state>
      val: {"owner": {"business_id": "...", "user__id": "..."}}
    """
    key = f"{provider}_oauth_state:{state}"
    set_redis_with_expiry(key, ttl_seconds, json.dumps({"owner": owner}))


def _consume_state(state: str, provider: str) -> dict:
    """
    Validate and one-time consume state.
    Returns: {"owner": {...}}
    """
    key = f"{provider}_oauth_state:{state}"
    raw = get_redis(key)
    if not raw:
        return {}
    remove_redis(key)
    return _safe_json_load(raw, default={})


def _store_selection(*, provider: str, selection_key: str, payload: dict, ttl_seconds: int = 300):
    """
    Stores selection payload in redis:
      key: <provider>_select:<selection_key>
      val: payload JSON
    """
    key = f"{provider}_select:{selection_key}"
    set_redis_with_expiry(key, ttl_seconds, json.dumps(payload))


def _load_selection(provider: str, selection_key: str) -> dict:
    key = f"{provider}_select:{selection_key}"
    raw = get_redis(key)
    return _safe_json_load(raw, default={}) if raw else {}


def _delete_selection(provider: str, selection_key: str):
    key = f"{provider}_select:{selection_key}"
    try:
        remove_redis(key)
    except Exception:
        pass


def _redirect_to_frontend(path: str, selection_key: str):
    """
    Redirects to your frontend page with selection_key
    Example:
      /connect/facebook?selection_key=...
      /connect/instagram?selection_key=...
    """
    frontend_url = os.getenv("FRONT_END_BASE_URL")
    if not frontend_url:
        return jsonify({
            "success": True,
            "message": "FRONT_END_BASE_URL not set; returning selection_key for testing",
            "selection_key": selection_key,
        }), HTTP_STATUS_CODES["OK"]

    return redirect(f"{frontend_url}{path}?selection_key={selection_key}")


def _require_x_env(log_tag: str):
    ck = _require_env("X_CONSUMER_KEY", log_tag)
    cs = _require_env("X_CONSUMER_SECRET", log_tag)
    cb = _require_env("X_OAUTH_CALLBACK_URL", log_tag)
    return ck, cs, cb
