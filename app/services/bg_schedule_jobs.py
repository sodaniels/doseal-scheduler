# app/services/bg_schedule_jobs.py
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from ..utils.logger import Log
from ..services.gateways.sms_gateway_service import SmsGatewayService

def _parse_dt(value: str, tz: ZoneInfo) -> datetime:
    raw = (value or "").strip()
    if not raw:
        return datetime.now(tz)

    # ISO first
    try:
        iso = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
    except Exception:
        dt = None

    if dt is None:
        for fmt in ("%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d %H:%M",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%dT%H:%M",
                    "%Y-%m-%d"):
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except Exception:
                pass

    if dt is None:
        # fallback: now
        return datetime.now(tz)

    # Attach tz if naive
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt

def send_sms_batch_at_async(*, message_id: str, business_id: str, text: str, contacts: list[str], send_at: str, tz_name: str = "Europe/London"):
    """
    Sleep until `send_at` (in tz_name), then fire SmsGatewayService.send_bulk_sms
    """
    log_tag = "[bg_jobs.send_sms_batch_at_async]"
    tz = ZoneInfo(tz_name)
    due = _parse_dt(send_at, tz)
    now = datetime.now(tz)
    delay = (due - now).total_seconds()

    Log.info(f"{log_tag} scheduled | message_id={message_id} due={due.isoformat()} now={now.isoformat()} delay={delay:.2f}s size={len(contacts)}")

    # Clamp: if already in the past, send immediately
    if delay > 0:
        # optional: cap max sleep if you want (e.g., split long sleeps)
        time.sleep(delay)

    try:
        svc = SmsGatewayService(text=text, provider="twilio", to_numbers=contacts)
        svc.send_bulk_sms(message_id=message_id, business_id=business_id)
        Log.info(f"{log_tag} dispatched | message_id={message_id} recipients={len(contacts)}")
    except Exception as e:
        Log.info(f"{log_tag} FAILED | message_id={message_id} error={e}")
