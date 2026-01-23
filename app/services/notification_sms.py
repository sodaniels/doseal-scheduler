# app/services/notify_sms.py
from __future__ import annotations

import os
import re
import time
from typing import List, Dict, Optional, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.utils.logger import Log
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from ..models.instntmny.messages_model import Message

"""
Twilio SMS helper (single & bulk) with mixed-country normalisation.

Environment (single-number mode):
- TWILIO_ACCOUNT_SID=ACxxxxxxxx...
- TWILIO_AUTH_TOKEN=xxxxxxxx
- TWILIO_FROM=+4475XXXXXXXX            # required if no Messaging Service

Optional (Messaging Service mode — recommended for bulk):
- TWILIO_MESSAGING_SERVICE_SID=MGxxxxxxxx...  # preferred; if set and valid, overrides TWILIO_FROM
- TWILIO_STATUS_CALLBACK=https://example.com/webhooks/twilio/status

Fan-out controls:
- TWILIO_CONCURRENCY=64   # how many messages to create concurrently (default 5)
- TWILIO_TARGET_MPS=10    # used only by paced variants (not used in fast fan-out)

Normalisation:
- Uses libphonenumber (phonenumbers) if available with REGION_PRIORITY (default "GB,GH")
- Accepts and preserves +E.164 inputs (e.g., +44…, +233…)
- Handles 00-prefix (00… → +…)
- Heuristic fallback if phonenumbers not installed

Config:
- REGION_PRIORITY="GB,GH"   # try these regions in order for national-format numbers
- DEFAULT_COUNTRY_CODE=44   # only used in heuristic fallback
- NATIONAL_TRUNK_PREFIX=0   # e.g., 0xxxxxxx → +44xxxxxxx (fallback path)
- ALLOWED_COUNTRY_CODES=44,233  # detect bare international numbers without '+'
"""

# =========================
# Config
# =========================
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

# Sanitize Messaging Service SID quietly (ignore AC… etc.)
_raw_mssid = (os.getenv("TWILIO_MESSAGING_SERVICE_SID") or "").strip()
TWILIO_MESSAGING_SERVICE_SID = _raw_mssid if _raw_mssid.startswith("MG") else ""

TWILIO_FROM = os.getenv("TWILIO_FROM")
TWILIO_STATUS_CALLBACK = os.getenv("TWILIO_STATUS_CALLBACK")

# Concurrency (set high to "dispatch all at once")
TWILIO_CONCURRENCY = int(os.getenv("TWILIO_CONCURRENCY", "5"))
TWILIO_TARGET_MPS = float(os.getenv("TWILIO_TARGET_MPS", "10"))  # not used by fast fan-out

# Normalisation settings
REGION_PRIORITY = [r.strip().upper() for r in (os.getenv("REGION_PRIORITY", "GB,GH").split(","))]
DEFAULT_COUNTRY_CODE = os.getenv("DEFAULT_COUNTRY_CODE", "44")
NATIONAL_TRUNK_PREFIX = os.getenv("NATIONAL_TRUNK_PREFIX", "0")
ALLOWED_COUNTRY_CODES = [c.strip() for c in (os.getenv("ALLOWED_COUNTRY_CODES", "44,233").split(",")) if c.strip()]

_GSM_7_MAX = 1600
_E164_RE = re.compile(r"^\+\d{7,15}$")

# Try to use libphonenumber if available
USE_PHONENUMBERS = False
try:
    import phonenumbers
    from phonenumbers import PhoneNumberFormat
    from phonenumbers.phonenumberutil import NumberParseException
    USE_PHONENUMBERS = True
except Exception:
    USE_PHONENUMBERS = False


def _twilio_client() -> Client:
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN):
        raise RuntimeError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set")
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


# =========================
# Phone helpers
# =========================
def _format_e164_with_lib(s: str) -> Optional[str]:
    """Parse and format to E.164 using libphonenumber with region priority."""
    assert USE_PHONENUMBERS
    # Already '+'? Parse without region hint.
    if s.startswith("+"):
        try:
            num = phonenumbers.parse(s, None)
            if phonenumbers.is_valid_number(num):
                return phonenumbers.format_number(num, PhoneNumberFormat.E164)
            return None
        except NumberParseException:
            return None

    # Try each region in priority for national-format inputs
    for region in REGION_PRIORITY:
        try:
            num = phonenumbers.parse(s, region)
            if phonenumbers.is_valid_number(num):
                return phonenumbers.format_number(num, PhoneNumberFormat.E164)
        except NumberParseException:
            continue
    return None


def _normalize_phone(raw: str) -> Optional[str]:
    """
    Normalise input to E.164.
      - Keep +E.164 (+44…, +233…) as-is (validated if phonenumbers installed)
      - Convert 00… → +…
      - For bare international digits (e.g., 233xxxxxxxxx, 44xxxxxxxxxx) add '+'
      - For national formats, try REGION_PRIORITY with libphonenumbers, else heuristic fallback
    """
    if not raw:
        return None

    s = re.sub(r"[^\d+]", "", str(raw).strip())
    if not s:
        return None

    # 00… → +…
    if s.startswith("00"):
        s = "+" + s[2:]

    # If we have libphonenumber, use it first for robust parsing/validation
    if USE_PHONENUMBERS:
        cand = _format_e164_with_lib(s)
        if cand and _E164_RE.match(cand):
            return cand

    # Fallback heuristics below (when phonenumbers not installed or parsing failed)

    # Already +E.164-looking?
    if s.startswith("+"):
        return s if _E164_RE.match(s) else None

    # Bare international with known country code (e.g., '233…' or '44…')
    for cc in ALLOWED_COUNTRY_CODES:
        if s.startswith(cc):
            cand = f"+{s}"
            return cand if _E164_RE.match(cand) else None

    # National trunk prefix (e.g., 0……) → +CC……
    if s.startswith(NATIONAL_TRUNK_PREFIX):
        cand = f"+{DEFAULT_COUNTRY_CODE}{s[1:]}"
        return cand if _E164_RE.match(cand) else None

    # Bare local digits → assume default country
    cand = f"+{DEFAULT_COUNTRY_CODE}{s}"
    return cand if _E164_RE.match(cand) else None


def _validate_and_dedupe(numbers: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for n in numbers or []:
        norm = _normalize_phone(n)
        if not norm:
            Log.info(f"[notify_sms.py] skipping invalid phone: {n!r}")
            continue
        if norm in seen:
            continue
        if str(n).strip() != norm:
            Log.info(f"[notify_sms.py] normalized phone {n!r} -> {norm}")
        seen.add(norm)
        out.append(norm)
    return out


# =========================
# Twilio helpers
# =========================
def _base_twilio_kwargs(text: str) -> Dict[str, str]:
    """
    Build kwargs for client.messages.create().
    For single-send, prefer Messaging Service if set; else fall back to TWILIO_FROM.
    """
    kwargs: Dict[str, str] = {"body": (text or "")[:_GSM_7_MAX]}
    if TWILIO_MESSAGING_SERVICE_SID:
        kwargs["messaging_service_sid"] = TWILIO_MESSAGING_SERVICE_SID
    else:
        if not TWILIO_FROM:
            raise RuntimeError("Set TWILIO_FROM or a valid TWILIO_MESSAGING_SERVICE_SID (starts with 'MG')")
        kwargs["from_"] = TWILIO_FROM

    if TWILIO_STATUS_CALLBACK:
        kwargs["status_callback"] = TWILIO_STATUS_CALLBACK
    return kwargs


def _send_with_retries(
    client: Client,
    to: str,
    base_kwargs: Dict[str, str],
    max_attempts: int = 3,
    backoff: float = 0.8,
) -> Dict[str, Optional[str]]:
    attempt = 0
    while True:
        attempt += 1
        try:
            msg = client.messages.create(to=to, **base_kwargs)
            Log.info(f"[notify_sms.py] twilio sms queued sid={msg.sid} to={to}")
            return {"to": to, "sid": msg.sid, "error": None}
        except TwilioRestException as e:
            is_retryable = (e.status in (429, 500, 502, 503, 504))
            Log.info(
                f"[notify_sms.py] twilio sms error to={to} "
                f"status={getattr(e,'status',None)} code={getattr(e,'code',None)}: {e.msg}"
            )
            if attempt < max_attempts and is_retryable:
                sleep_s = backoff * (2 ** (attempt - 1))
                time.sleep(sleep_s)
                continue
            return {"to": to, "sid": None, "error": f"{getattr(e,'status',None)}:{getattr(e,'code',None)}:{e.msg}"}
        except Exception as e:
            Log.info(f"[notify_sms.py] twilio sms FAILED to={to}: {e}")
            return {"to": to, "sid": None, "error": str(e)}


# =========================
# Public API
# =========================
def send_sms_twilio(to: str, text: str) -> str:
    """
    Send a single SMS (normalises to E.164). Returns Message SID.
    - Uses Messaging Service if TWILIO_MESSAGING_SERVICE_SID is set; otherwise uses TWILIO_FROM.
    - Raises ValueError for bad numbers and RuntimeError for Twilio failures.
    """
    client = _twilio_client()
    norm = _normalize_phone(to)
    if not norm:
        examples = "+447800123456 / +233241234567 / 07800123456 / 0241234567 / 00447800123456"
        raise ValueError(f"Recipient must be a valid phone number. Examples: {examples}")
    kwargs = _base_twilio_kwargs(text)
    res = _send_with_retries(client, norm, kwargs)
    if res["error"]:
        raise RuntimeError(res["error"])
    return str(res["sid"])


def send_bulk_sms_twilio(to_numbers: List[str], text: str, message_id=None, business_id=None) -> List[Dict[str, Optional[str]]]:
    """
    Fast fan-out bulk send via a Twilio Messaging Service (no local pacing).
    - Requires TWILIO_MESSAGING_SERVICE_SID that starts with 'MG' (dispatch to Twilio queues).
    - Twilio will queue and deliver according to your sender pool / throughput config.
    - Returns list of {'to','sid','error'} in the SAME ORDER as input.
    """
    
    log_tag = f"[notification_sms.py][send_bulk_sms_twilio]"
    
    import uuid
    from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

    def _augment_callback(url: str, extra: Dict[str, str]) -> str:
        if not url:
            return url
        u = urlparse(url)
        q = dict(parse_qsl(u.query, keep_blank_values=True))
        q.update(extra)
        return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(q), u.fragment))

    mssid = (TWILIO_MESSAGING_SERVICE_SID or "").strip()
    if not mssid or not mssid.startswith("MG"):
        raise RuntimeError("TWILIO_MESSAGING_SERVICE_SID must be a valid 'MG...' SID to use Messaging Service bulk.")

    clean = _validate_and_dedupe(to_numbers)
    if not clean:
        return []

    client = _twilio_client()

    # ---- Readiness guard: ensure the service actually has senders (prevents 21704) ----
    svc = client.messaging.v1.services(mssid)
    has_sender = bool(svc.phone_numbers.list(limit=1) or
                      svc.short_codes.list(limit=1) or
                      svc.alpha_senders.list(limit=1))
    if not has_sender:
        raise RuntimeError(f"Messaging Service {mssid} has no senders attached. Add a phone number/short code/alpha sender.")

    # Base kwargs (force Messaging Service; no from_)
    base = {
        "body": (text or "")[:_GSM_7_MAX],
        "messaging_service_sid": mssid,
    }

    # Correlate this run in your delivery webhook logs
    batch_id = uuid.uuid4().hex
    cb_base = TWILIO_STATUS_CALLBACK

    results: List[Dict[str, Optional[str]]] = [None] * len(clean)  # preserve order

    # Fan out immediately: let Twilio queue/MPS on their side.
    max_workers = max(1, min(int(TWILIO_CONCURRENCY), len(clean)))

    def _task(i: int, num: str):
        # Per-message kwargs (optionally append i & batch_id to callback URL)
        kwargs = dict(base)
        if cb_base:
            kwargs["status_callback"] = _augment_callback(cb_base, {"batch": batch_id, "i": str(i)})
        res = _send_with_retries(client, num, kwargs)
        Log.info(f"[notify_sms.py][send_bulk_sms_twilio][batch={batch_id} i={i}] result: {res}")
        return i, res

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = [pool.submit(_task, i, n) for i, n in enumerate(clean)]
        for f in as_completed(futs):
            i, res = f.result()
            results[i] = res
            
            response_sid = res.get("sid")
            to = res.get("to")
            Log.info(f"{log_tag}[{message_id}] response_sid: {response_sid}")
            
            
            update_sid = Message.update(
                message_id,
                sid=response_sid,
                business_id=business_id,
                status="dispatched",
                to=to,
                delivery_status=None
            )
            # The call above also upserts payload_detail[ { sid, contact, status, ... } ] for this message_id
            if update_sid:
                Log.info(f"{log_tag}[{message_id}] SID updated successfully: {update_sid}")
                
    return results 


def fetch_message_status(sid: str) -> Dict[str, Optional[str]]:
    """Return current Twilio delivery status + error info for a Message SID."""
    client = _twilio_client()
    msg = client.messages(sid).fetch()
    data = {
        "sid": msg.sid,
        "to": msg.to,
        "from": getattr(msg, "from_", None),
        "status": msg.status,             # queued | sent | delivered | undelivered | failed
        "error_code": msg.error_code,     # e.g. 30007
        "error_message": msg.error_message,
        "num_segments": msg.num_segments,
        "price": msg.price,
        "price_unit": msg.price_unit,
        "date_sent": str(msg.date_sent),
    }
    Log.info(f"[notify_sms.py][fetch_message_status] {data}")
    return data

def send_sms(to: str, text: str):
    """Compatibility shim."""
    return send_sms_twilio(to, text)
