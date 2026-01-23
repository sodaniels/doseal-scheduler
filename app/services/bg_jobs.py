# app/services/bg_jobs.py
from ..utils.logger import Log
from ..services.gateways.sms_gateway_service import SmsGatewayService

def send_sms_batch_async(*, message_id: str, business_id: str, text: str, contacts: list[str]):
    log_tag = "[bg_jobs.send_sms_batch_async]"
    Log.info(f"{log_tag} starting | message_id={message_id} business_id={business_id} contacts={len(contacts)}")

    try:
        svc = SmsGatewayService(text=text, provider="twilio", to_numbers=contacts)
        svc.send_bulk_sms(message_id=message_id, business_id=business_id)
        Log.info(f"{log_tag} finished OK | message_id={message_id}")
    except Exception as e:
        Log.info(f"{log_tag} FAILED | message_id={message_id} error={e}")
