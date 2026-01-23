import os
import time
import requests
from dotenv import load_dotenv
import jinja2
from app.utils.logger import Log

load_dotenv()

MAILGUN_API_KEY   = os.getenv("MAILGUN_API_KEY")
MAILGUN_DOMAIN    = os.getenv("INSTNTMNY_MAILGUN_DOMAIN")   # e.g. mg.example.com
SENDER_EMAIL      = os.getenv("SENDER_EMAIL")                   # e.g. info@mg.example.com
MAIL_NAME         = os.getenv("MAIL_NAME", "Instntmny Transfer")
MAILGUN_API_HOST  = os.getenv("MAILGUN_API_HOST", "api.mailgun.net")  # use "api.eu.mailgun.net" if EU region

# Jinja2
template_env = jinja2.Environment(loader=jinja2.FileSystemLoader("templates"))

def render_template(template_filename, **context):
    return template_env.get_template(template_filename).render(**context)

def _mailgun_post(data, max_retries=3):
    """POST to Mailgun with simple backoff on 429/5xx."""
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        Log.error("Mailgun API key or domain missing.")
        return None

    url = f"https://{MAILGUN_API_HOST}/v3/{MAILGUN_DOMAIN}/messages"
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                url,
                auth=("api", MAILGUN_API_KEY),  # Basic Auth (username='api', password=API_KEY)
                data=data,
                timeout=15,
            )
            Log.info(f"Mailgun status={resp.status_code} attempt={attempt}")
            if resp.status_code < 400:
                return resp
            # Retry on 429/5xx
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            # Hard failure
            Log.error(f"Mailgun error {resp.status_code}: {resp.text[:500]}")
            return resp
        except Exception as exc:
            Log.error(f"Mailgun exception attempt {attempt}: {exc}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            return None

def send_simple_message(to, subject, body, html):
    return _mailgun_post({
        "from":    f"{MAIL_NAME} <{SENDER_EMAIL}>",
        "to":      [to] if isinstance(to, str) else to,
        "subject": subject,
        "text":    body,
        "html":    html,
    })

def send_user_registration_email(email, name, link):
    subject = f"Welcome to {MAIL_NAME}"
    body    = f"Hi {name}! Complete your registration by confirming your email."
    html    = render_template("email/agent_initial_account.html", email=email, link=link, app_name=MAIL_NAME)
    return send_simple_message(email, subject, body, html)

def send_subscriber_registration_email(email, name, link):
    subject = f"Welcome to {MAIL_NAME}"
    body    = f"Hi {name}! Complete your registration by confirming your email."
    html    = render_template("email/subscriber_initial_account.html", email=email, link=link, app_name=MAIL_NAME)
    return send_simple_message(email, subject, body, html)

def send_user_contact_sale_email(email, name):
    subject = "We received your message"
    body    = f"Hi {name}! You have successfully signed up to the Stores REST API."
    html    = render_template("email/registration.html", email=email)
    return send_simple_message(email, subject, body, html)

def send_new_contact_sale_email(email, name, business_email, fullname, phone_number, company_name, store_url):
    subject = "New Contact Sale Request"
    body    = f"Hi {name}! There is a new contact sale request."
    html    = render_template(
        "email/new-contact-sale.html",
        email=email,
        business_email=business_email,
        fullname=fullname,
        phone_number=phone_number,
        company_name=company_name,
        store_url=store_url
    )
    return send_simple_message(email, subject, body, html)

def send_contact_sale_registration_email(email, name):
    subject = "Successfully signed up"
    body    = f"Hi {name}! You have successfully signed up to the Stores REST API."
    html    = render_template("email/contact-sales.html", email=email)
    return send_simple_message(email, subject, body, html)

def send_payment_receipt(email, payload):
    subject = f"{MAIL_NAME} Payment Receipt"
    body    = f"Your {MAIL_NAME} Payment Receipt"
    html    = render_template("email/receipt.html", payload=payload)
    return send_simple_message(email, subject, body, html)
