from ..models.social.integration_model import Integration

PAYMENT_PROVIDER_KEYS = [
    k for k, v in Integration.PROVIDERS.items()
    if v["category"] == Integration.CAT_PAYMENT
]

SMS_PROVIDER_KEYS = [
    k for k, v in Integration.PROVIDERS.items()
    if v["category"] == Integration.CAT_SMS
]

EMAIL_PROVIDER_KEYS = [
    k for k, v in Integration.PROVIDERS.items()
    if v["category"] == Integration.CAT_EMAIL
]

WHATSAPP_PROVIDER_KEYS = [
    k for k, v in Integration.PROVIDERS.items()
    if v["category"] == Integration.CAT_WHATSAPP
]