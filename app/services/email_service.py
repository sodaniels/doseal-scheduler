# app/services/email_service.py
import os
import time
import smtplib
import requests
import jinja2
from dataclasses import dataclass
from email.message import EmailMessage
from datetime import datetime
from typing import Optional, Dict, Any, List, Union, TypedDict

from app.utils.logger import Log

EmailAddr = Union[str, List[str]]


class EmailAttachment(TypedDict, total=False):
    filename: str
    content_type: str
    data: bytes
    disposition: str
    content_id: str


@dataclass
class EmailConfig:
    provider: str  # "mailgun" | "smtp"

    from_email: str
    from_name: str = "Schedulefy"
    templates_dir: str = "templates"

    mailgun_api_key: Optional[str] = None
    mailgun_domain: Optional[str] = None
    mailgun_api_host: str = "api.mailgun.net"

    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True


def load_email_config() -> EmailConfig:
    provider = os.getenv("EMAIL_PROVIDER", "mailgun").lower()

    from_email = os.getenv("SENDER_EMAIL") or ""
    from_name = os.getenv("MAIL_NAME", "Schedulefy")
    templates_dir = os.getenv("EMAIL_TEMPLATES_DIR", "templates")

    return EmailConfig(
        provider=provider,
        from_email=from_email,
        from_name=from_name,
        templates_dir=templates_dir,
        mailgun_api_key=os.getenv("MAILGUN_API_KEY"),
        mailgun_domain=os.getenv("INSTNTMNY_MAILGUN_DOMAIN"),
        mailgun_api_host=os.getenv("MAILGUN_API_HOST", "api.mailgun.net"),
        smtp_host=os.getenv("SMTP_HOST"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME"),
        smtp_password=os.getenv("SMTP_PASSWORD"),
        smtp_use_tls=os.getenv("SMTP_USE_TLS", "true").lower() == "true",
    )


class TemplateRenderer:
    def __init__(self, templates_dir: str):
        abs_dir = os.path.abspath(templates_dir)
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(abs_dir),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
        )

    def render(self, template_filename: str, **context) -> str:
        try:
            return self.env.get_template(template_filename).render(**context)
        except Exception as exc:
            Log.error(f"Template render failed: {template_filename} err={exc}")
            raise


class EmailSendError(Exception):
    pass


class BaseEmailProvider:
    def send(
        self,
        to: Union[str, List[str]],
        subject: str,
        text: str,
        html: Optional[str] = None,
        reply_to: Optional[str] = None,
        tags: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
        attachments: Optional[List[EmailAttachment]] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError


class MailgunProvider(BaseEmailProvider):
    def __init__(self, cfg: EmailConfig):
        self.cfg = cfg
        if not cfg.mailgun_api_key or not cfg.mailgun_domain:
            raise EmailSendError("Mailgun config missing: MAILGUN_API_KEY / INSTNTMNY_MAILGUN_DOMAIN")

    def _post(
        self,
        data: Dict[str, Any],
        files: Optional[List[tuple]] = None,
        max_retries: int = 3,
    ) -> requests.Response:
        url = f"https://{self.cfg.mailgun_api_host}/v3/{self.cfg.mailgun_domain}/messages"

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(
                    url,
                    auth=("api", self.cfg.mailgun_api_key),
                    data=data,
                    files=files,
                    timeout=20,
                )
                Log.info(f"Mailgun send status={resp.status_code} attempt={attempt}")

                if resp.status_code < 400:
                    return resp

                if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue

                raise EmailSendError(f"Mailgun error {resp.status_code}: {resp.text[:800]}")
            except requests.RequestException as exc:
                Log.error(f"Mailgun request exception attempt={attempt} err={exc}")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise EmailSendError(f"Mailgun request failed after retries: {exc}") from exc

        raise EmailSendError("Mailgun failed unexpectedly")

    def send(
        self,
        to,
        subject,
        text,
        html=None,
        reply_to=None,
        tags=None,
        meta=None,
        attachments=None,
        cc=None,
        bcc=None,
    ):
        to_list = [to] if isinstance(to, str) else to

        data: Dict[str, Any] = {
            "from": f"{self.cfg.from_name} <{self.cfg.from_email}>",
            "to": to_list,
            "subject": subject,
            "text": text or "",
        }

        if html:
            data["html"] = html
        if reply_to:
            data["h:Reply-To"] = reply_to
        if cc:
            data["cc"] = cc
        if bcc:
            data["bcc"] = bcc

        if tags:
            for t in tags:
                data.setdefault("o:tag", []).append(t)

        if meta:
            for k, v in meta.items():
                data[f"v:{k}"] = str(v)

        files: Optional[List[tuple]] = None
        if attachments:
            files = []
            for a in attachments:
                filename = a.get("filename")
                blob = a.get("data")
                content_type = a.get("content_type") or "application/octet-stream"
                if not filename or not blob:
                    continue
                files.append(("attachment", (filename, blob, content_type)))

        resp = self._post(data, files=files)

        try:
            payload = resp.json() if resp.text else {}
        except Exception:
            payload = {"raw": resp.text[:800]}

        return {"ok": resp.status_code < 400, "provider": "mailgun", "status_code": resp.status_code, "response": payload}


class SmtpProvider(BaseEmailProvider):
    def __init__(self, cfg: EmailConfig):
        self.cfg = cfg
        required = [cfg.smtp_host, cfg.smtp_username, cfg.smtp_password]
        if any(not x for x in required):
            raise EmailSendError("SMTP config missing: SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD")

    def send(
        self,
        to,
        subject,
        text,
        html=None,
        reply_to=None,
        tags=None,
        meta=None,
        attachments=None,
        cc=None,
        bcc=None,
    ):
        to_list = [to] if isinstance(to, str) else to

        msg = EmailMessage()
        msg["From"] = f"{self.cfg.from_name} <{self.cfg.from_email}>"
        msg["To"] = ", ".join(to_list)
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to
        if cc:
            msg["Cc"] = ", ".join(cc)

        msg.set_content(text or "")
        if html:
            msg.add_alternative(html, subtype="html")

        if attachments:
            for a in attachments:
                filename = a.get("filename") or "attachment"
                content_type = a.get("content_type") or "application/octet-stream"
                data_bytes = a.get("data")
                if not data_bytes:
                    continue

                maintype, subtype = content_type.split("/", 1) if "/" in content_type else ("application", "octet-stream")
                msg.add_attachment(data_bytes, maintype=maintype, subtype=subtype, filename=filename)

        all_recipients = list(to_list)
        if cc:
            all_recipients += list(cc)
        if bcc:
            all_recipients += list(bcc)

        try:
            with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=20) as server:
                server.ehlo()
                if self.cfg.smtp_use_tls:
                    server.starttls()
                    server.ehlo()
                server.login(self.cfg.smtp_username, self.cfg.smtp_password)
                server.send_message(msg, to_addrs=all_recipients)

            return {"ok": True, "provider": "smtp", "status_code": 250, "response": {}}
        except Exception as exc:
            raise EmailSendError(f"SMTP send failed: {exc}") from exc


class EmailService:
    def __init__(self, cfg: EmailConfig):
        self.cfg = cfg
        self.renderer = TemplateRenderer(cfg.templates_dir)
        self.provider = self._build_provider(cfg)
        if not cfg.from_email:
            raise EmailSendError("SENDER_EMAIL is missing (used in From:)")

    def _build_provider(self, cfg: EmailConfig) -> BaseEmailProvider:
        if cfg.provider == "mailgun":
            return MailgunProvider(cfg)
        if cfg.provider == "smtp":
            return SmtpProvider(cfg)
        raise EmailSendError(f"Unknown EMAIL_PROVIDER: {cfg.provider}")

    def send_templated(
        self,
        to: Union[str, List[str]],
        subject: str,
        template: str,
        context: Dict[str, Any],
        text_fallback: Optional[str] = None,
        reply_to: Optional[str] = None,
        tags: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
        attachments: Optional[List[EmailAttachment]] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        html = self.renderer.render(template, **context)
        text = text_fallback or f"{subject}\n\nPlease open this email in an HTML-capable client."

        return self.provider.send(
            to=to,
            subject=subject,
            text=text,
            html=html,
            reply_to=reply_to,
            tags=tags,
            meta=meta,
            attachments=attachments,
            cc=cc,
            bcc=bcc,
        )


# =========================================================
# Emails
# =========================================================

# ---------------------------------
# EMAIL TO USER UPON NEW REGISTRATION
#----------------------------------
def send_user_registration_email(email: str, fullname: str, reset_url: str) -> Dict[str, Any]:
    cfg = load_email_config()
    svc = EmailService(cfg)

    subject = f"Welcome to {cfg.from_name}! Please verify your email address"
    text = f"Hi {fullname},\n\nComplete your registration by confirming your email:\n{reset_url}\n"

    return svc.send_templated(
        to=email,
        subject=subject,
        template="email/initial_account.html",
        context={
            "email": email,
            "link": reset_url,
            "app_name": cfg.from_name,
            "fullname": fullname,
            "expiry_minutes": 5,
            "support_email": "support@schedulefy.org",
            "sender_domain": "schedulefy.org",
        },
        text_fallback=text,
        tags=["registration"],
        meta={"email_type": "user_registration"},
    )


# -------------------------------------
# EMAIL TO ADMIN UPON USER REGISTRATION
#--------------------------------------
def send_new_contact_sale_email(
    to_admins: EmailAddr,
    admin_name: str,
    requester_email: str,
    requester_fullname: str,
    requester_phone_number: str,
    company_name: str,
    cc_admins: Optional[EmailAddr] = None,
    bcc_admins: Optional[EmailAddr] = None,
) -> Dict[str, Any]:
    """
    Sends an internal notification email to admins when a new contact sale request comes in.
    """

    def _as_list(val: Optional[EmailAddr]) -> List[str]:
        if not val:
            return []
        return [val] if isinstance(val, str) else list(val)

    cfg = load_email_config()
    svc = EmailService(cfg)

    to_list = _as_list(to_admins)
    cc_list = _as_list(cc_admins)
    bcc_list = _as_list(bcc_admins)

    if not to_list:
        raise ValueError("send_new_contact_sale_email: 'to_admins' cannot be empty")

    subject = f"New Contact Sale Request — {company_name}"

    text = (
        f"Hi {admin_name},\n\n"
        f"A new contact sale request has been submitted.\n\n"
        f"Company: {company_name}\n\n"
        f"Requester Name: {requester_fullname}\n"
        f"Requester Email: {requester_email}\n"
        f"Requester Phone: {requester_phone_number}\n\n"
        f"— {cfg.from_name}\n"
    )

    reply_to = requester_email if requester_email else None

    try:
        return svc.send_templated(
            to=",".join(to_list) if len(to_list) == 1 else to_list[0],  # keep compatibility
            subject=subject,
            template="email/new-contact-sale.html",
            context={
                "app_name": cfg.from_name,
                "admin_name": admin_name,
                "company_name": company_name,
                "requester_fullname": requester_fullname,
                "requester_email": requester_email,
                "requester_phone_number": requester_phone_number,
            },
            text_fallback=text,
            reply_to=reply_to,
            tags=["admin", "contact-sale"],
            meta={"email_type": "new_contact_sale"},
            cc=cc_list or None,
            bcc=bcc_list or None,
        )
    except Exception as exc:
        Log.error(f"send_new_contact_sale_email failed: {exc}")
        raise


#-------------------------------------
# EMAIL TO USER UPON PASSWORD CHANGE
#------------------------------------
def send_password_changed_email(
    email: str,
    fullname: Optional[str] = None,
    changed_at: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = load_email_config()
    svc = EmailService(cfg)

    subject = f"Your {cfg.from_name} password was changed"

    text = (
        f"Hi {fullname or 'there'},\n\n"
        f"This is a confirmation that your password was changed.\n\n"
        f"Time: {changed_at or 'Just now'}\n"
        f"IP: {ip_address or 'Unknown'}\n"
        f"Device: {user_agent or 'Unknown'}\n\n"
        f"If you didn’t do this, reset your password immediately and contact support.\n\n"
        f"— {cfg.from_name}\n"
    )

    return svc.send_templated(
        to=email,
        subject=subject,
        template="email/password_changed.html",
        context={
            "app_name": cfg.from_name,
            "email": email,
            "fullname": fullname,
            "changed_at": changed_at,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "support_email": os.getenv("SUPPORT_EMAIL", None),
        },
        text_fallback=text,
        tags=["security", "password-changed"],
        meta={"email_type": "password_changed"},
    )


# ---------------------------------------------
# EMAIL TO USER WHEN SCHEDULED POST IS PUBLISHED
# ---------------------------------------------
def send_post_published_email(
    email: str,
    fullname: Optional[str] = None,
    post_text: Optional[str] = None,
    platforms: Optional[List[str]] = None,
    account_names: Optional[List[str]] = None,
    scheduled_time: Optional[str] = None,
    published_time: Optional[str] = None,
    media_url: Optional[str] = None,
    media_type: Optional[str] = None,
    media_count: Optional[int] = None,
    post_url: Optional[str] = None,
    post_ids: Optional[List[str]] = None,
    dashboard_url: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = load_email_config()
    svc = EmailService(cfg)

    platform_count = len(platforms) if platforms else 0
    if platform_count == 1:
        subject = f"✓ Your post is now live on {platforms[0].capitalize()}"
    elif platform_count > 1:
        subject = f"✓ Your post is now live on {platform_count} platforms"
    else:
        subject = f"✓ Your scheduled post is now live"

    platforms_str = ", ".join([p.capitalize() for p in (platforms or [])]) or "your connected accounts"
    accounts_str = ", ".join(account_names) if account_names else ""

    text_lines = [
        f"Hi {fullname or 'there'},",
        "",
        f"Great news! Your scheduled post has been successfully published to {platforms_str}.",
        "",
    ]

    if post_text:
        preview = post_text[:200] + "..." if len(post_text) > 200 else post_text
        text_lines.extend(["Post preview:", f'"{preview}"', ""])

    text_lines.extend([
        f"Scheduled for: {scheduled_time or '—'}",
        f"Published at: {published_time or 'Just now'}",
    ])

    if accounts_str:
        text_lines.append(f"Accounts: {accounts_str}")

    text_lines.extend([
        "",
        f"View your post: {post_url or dashboard_url or 'Check your dashboard'}",
        "",
        "Tip: Check back in a few hours to see how your post is performing!",
        "",
        f"— {cfg.from_name}",
    ])

    text = "\n".join(text_lines)

    return svc.send_templated(
        to=email,
        subject=subject,
        template="email/post_published.html",
        context={
            "app_name": cfg.from_name,
            "email": email,
            "fullname": fullname,
            "post_text": post_text,
            "platforms": platforms or [],
            "account_names": account_names,
            "scheduled_time": scheduled_time,
            "published_time": published_time,
            "media_url": media_url,
            "media_type": media_type,
            "media_count": media_count,
            "post_url": post_url,
            "post_ids": post_ids,
            "dashboard_url": dashboard_url or os.getenv("APP_DASHBOARD_URL"),
        },
        text_fallback=text,
        tags=["social", "post-published", "notification"],
        meta={"email_type": "post_published"},
    )


# ---------------------------------------------
# EMAIL TO USER WHEN SCHEDULED POST FAILS
# ---------------------------------------------
def send_post_failed_email(
    email: str,
    fullname: Optional[str] = None,
    post_text: Optional[str] = None,
    platforms: Optional[List[str]] = None,
    account_names: Optional[List[str]] = None,
    scheduled_time: Optional[str] = None,
    failed_time: Optional[str] = None,
    error_message: Optional[str] = None,
    error_code: Optional[str] = None,
    failed_platforms: Optional[List[str]] = None,
    successful_platforms: Optional[List[str]] = None,
    retry_url: Optional[str] = None,
    dashboard_url: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = load_email_config()
    svc = EmailService(cfg)

    is_partial = bool(successful_platforms and len(successful_platforms) > 0)
    subject = "⚠️ Your post partially published - action needed" if is_partial else "❌ Your scheduled post failed to publish"

    failed_str = ", ".join([p.capitalize() for p in (failed_platforms or platforms or [])]) or "some platforms"

    text_lines = [f"Hi {fullname or 'there'},", ""]
    if is_partial:
        success_str = ", ".join([p.capitalize() for p in successful_platforms or []])
        text_lines.extend([f"Your scheduled post was published to {success_str}, but failed on {failed_str}.", ""])
    else:
        text_lines.extend([f"Unfortunately, your scheduled post failed to publish to {failed_str}.", ""])

    if post_text:
        preview = post_text[:150] + "..." if len(post_text) > 150 else post_text
        text_lines.extend(["Post preview:", f'"{preview}"', ""])

    text_lines.extend([f"Scheduled for: {scheduled_time or '—'}", f"Failed at: {failed_time or 'Just now'}"])

    if error_message:
        text_lines.extend(["", f"Error: {error_message}"])
    if error_code:
        text_lines.append(f"Error code: {error_code}")

    text_lines.extend([
        "",
        "What to do:",
        "1. Check that your social accounts are still connected",
        "2. Verify your post meets platform requirements",
        "3. Try posting again or contact support if the issue persists",
        "",
        f"Retry or edit your post: {retry_url or dashboard_url or 'Check your dashboard'}",
        "",
        f"— {cfg.from_name}",
    ])

    text = "\n".join(text_lines)

    return svc.send_templated(
        to=email,
        subject=subject,
        template="email/post_failed.html",
        context={
            "app_name": cfg.from_name,
            "email": email,
            "fullname": fullname,
            "post_text": post_text,
            "platforms": platforms or [],
            "account_names": account_names,
            "scheduled_time": scheduled_time,
            "failed_time": failed_time,
            "error_message": error_message,
            "error_code": error_code,
            "failed_platforms": failed_platforms or platforms or [],
            "successful_platforms": successful_platforms or [],
            "is_partial_failure": is_partial,
            "retry_url": retry_url,
            "dashboard_url": dashboard_url or os.getenv("APP_DASHBOARD_URL"),
            "settings_url": os.getenv("APP_SETTINGS_URL"),
            "support_email": os.getenv("SUPPORT_EMAIL"),
            "sender_domain": os.getenv("SENDER_DOMAIN", "doseal.com"),
        },
        text_fallback=text,
        tags=["social", "post-failed", "notification", "alert"],
        meta={"email_type": "post_failed", "error_code": error_code or ""},
    )


# ---------------------------------------------
# EMAIL TO USER FOR UPCOMING SCHEDULED POST REMINDER
# ---------------------------------------------
def send_post_reminder_email(
    email: str,
    fullname: Optional[str] = None,
    post_text: Optional[str] = None,
    platforms: Optional[List[str]] = None,
    account_names: Optional[List[str]] = None,
    scheduled_time: Optional[str] = None,
    time_until: Optional[str] = None,
    media_url: Optional[str] = None,
    media_type: Optional[str] = None,
    edit_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
    dashboard_url: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = load_email_config()
    svc = EmailService(cfg)

    subject = f"⏰ Reminder: Your post goes live in {time_until or 'soon'}"
    platforms_str = ", ".join([p.capitalize() for p in (platforms or [])]) or "your connected accounts"

    text_lines = [
        f"Hi {fullname or 'there'},",
        "",
        f"Just a heads up! Your scheduled post will be published to {platforms_str} in {time_until or 'soon'}.",
        "",
    ]

    if post_text:
        preview = post_text[:200] + "..." if len(post_text) > 200 else post_text
        text_lines.extend(["Post preview:", f'"{preview}"', ""])

    text_lines.extend([
        f"Scheduled for: {scheduled_time or '—'}",
        "",
        "Need to make changes?",
        f"Edit post: {edit_url or dashboard_url or 'Check your dashboard'}",
        f"Cancel post: {cancel_url or dashboard_url or 'Check your dashboard'}",
        "",
        f"— {cfg.from_name}",
    ])

    text = "\n".join(text_lines)

    return svc.send_templated(
        to=email,
        subject=subject,
        template="email/post_reminder.html",
        context={
            "app_name": cfg.from_name,
            "email": email,
            "fullname": fullname,
            "post_text": post_text,
            "platforms": platforms or [],
            "account_names": account_names,
            "scheduled_time": scheduled_time,
            "time_until": time_until,
            "media_url": media_url,
            "media_type": media_type,
            "edit_url": edit_url,
            "cancel_url": cancel_url,
            "dashboard_url": dashboard_url or os.getenv("APP_DASHBOARD_URL"),
            "settings_url": os.getenv("APP_SETTINGS_URL"),
            "support_email": os.getenv("SUPPORT_EMAIL"),
            "sender_domain": os.getenv("SENDER_DOMAIN", "doseal.com"),
        },
        text_fallback=text,
        tags=["social", "post-reminder", "notification"],
        meta={"email_type": "post_reminder"},
    )


# ---------------------------------------------
# EMAIL OTP FOR LOGIN VERIFICATION
# ---------------------------------------------
def send_otp_email(
    email: str,
    otp: str,
    message: Optional[str] = None,
    fullname: Optional[str] = None,
    expiry_minutes: int = 5,
) -> Dict[str, Any]:
    cfg = load_email_config()
    svc = EmailService(cfg)

    subject = f"{otp} is your {cfg.from_name} verification code"
    default_message = "Use the code below to complete your sign-in. This code is valid for a limited time."

    text = (
        f"Hi {fullname or 'there'},\n\n"
        f"{message or default_message}\n\n"
        f"Your verification code is: {otp}\n\n"
        f"This code expires in {expiry_minutes} minutes.\n\n"
        f"If you didn't request this code, you can safely ignore this email.\n\n"
        f"— {cfg.from_name}\n"
    )

    return svc.send_templated(
        to=email,
        subject=subject,
        template="email/otp_email.html",
        context={
            "app_name": cfg.from_name,
            "email": email,
            "fullname": fullname,
            "otp": otp,
            "message": message,
            "expiry_minutes": expiry_minutes,
        },
        text_fallback=text,
        tags=["security", "otp", "verification"],
        meta={"email_type": "otp"},
    )


# =========================================================
# PAYMENT CONFIRMATION EMAIL
# =========================================================
def send_payment_confirmation_email(
    *,
    email: str,
    fullname: str,
    amount: float,
    currency: str,
    receipt_number: str,
    invoice_number: str,
    payment_method: str,
    paid_date: str,
    plan_name: str,
    total_from_amount: Optional[float] = None,
    package_amount: Optional[float] = None,
    addon_users: Optional[int] = None,
    invoice_pdf_bytes: Optional[bytes] = None,
    invoice_url: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = load_email_config()
    svc = EmailService(cfg)

    app_name = os.getenv("APP_NAME", cfg.from_name or "Schedulefy")
    subject = f"Payment received — {plan_name} | {app_name}"

    text = (
        f"Hi {fullname},\n\n"
        f"We’ve received your payment successfully.\n\n"
        f"Plan: {plan_name}\n"
        f"Amount: {currency} {amount}\n"
        f"Payment method: {payment_method}\n"
        f"Invoice number: {invoice_number}\n"
        f"Receipt number: {receipt_number}\n"
        f"Paid date: {paid_date}\n"
        f"{'Download invoice: ' + invoice_url if invoice_url else ''}\n\n"
        f"Thank you,\n{app_name}\n"
    )

    attachments: Optional[List[EmailAttachment]] = None
    if invoice_pdf_bytes:
        attachments = [{
            "filename": f"Invoice-{invoice_number}.pdf",
            "content_type": "application/pdf",
            "data": invoice_pdf_bytes,
        }]

    return svc.send_templated(
        to=email,
        subject=subject,
        template="email/payment_confirmation.html",
        context={
            "email": email,
            "fullname": fullname,
            "app_name": app_name,
            "amount": amount,
            "currency": currency,
            "total_from_amount": total_from_amount,
            "package_amount": package_amount,
            "addon_users": addon_users,
            "receipt_number": receipt_number,
            "invoice_number": invoice_number,
            "payment_method": payment_method,
            "paid_date": paid_date,
            "plan_name": plan_name,
            "invoice_url": invoice_url,  # ✅ show link as fallback
            "support_email": os.getenv("SUPPORT_EMAIL", "support@schedulefy.org"),
            "sender_domain": os.getenv("SENDER_DOMAIN", "schedulefy.org"),
        },
        text_fallback=text,
        tags=["payment", "receipt"],
        meta={"email_type": "payment_confirmation", "invoice_number": invoice_number},
        attachments=attachments,
    )


# =========================================================
# TRIAL STARTED EMAIL
# =========================================================
def send_trial_started_email(
    *,
    email: str,
    fullname: Optional[str],
    plan_name: str,
    trial_days: int,
    trial_start_date: datetime,
    trial_end_date: datetime,
    dashboard_url: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = load_email_config()
    svc = EmailService(cfg)

    app_name = os.getenv("APP_NAME", cfg.from_name or "Schedulefy")
    subject = f"Your {trial_days}-day free trial has started | {app_name}"

    text = (
        f"Hi {fullname or ''},\n\n"
        f"Your free trial has started!\n\n"
        f"Plan: {plan_name}\n"
        f"Trial duration: {trial_days} days\n"
        f"Ends on: {trial_end_date.strftime('%Y-%m-%d')}\n\n"
        f"Access your dashboard: {dashboard_url or ''}\n\n"
        f"— {app_name}"
    )

    return svc.send_templated(
        to=email,
        subject=subject,
        template="email/trial_started.html",
        context={
            "email": email,
            "fullname": fullname,
            "app_name": app_name,
            "plan_name": plan_name,
            "trial_days": trial_days,
            "trial_start_date": trial_start_date.strftime("%Y-%m-%d"),
            "trial_end_date": trial_end_date.strftime("%Y-%m-%d"),
            "dashboard_url": dashboard_url,
            "support_email": os.getenv("SUPPORT_EMAIL", "support@schedulefy.org"),
        },
        text_fallback=text,
        tags=["trial", "onboarding"],
        meta={
            "email_type": "trial_started",
            "plan_name": plan_name,
        },
    )


# =========================================================
# TRIAL ENDED EMAIL
# =========================================================
def send_trial_ended_email(
    *,
    email: str,
    fullname: Optional[str],
    plan_name: str,
    trial_days: int,
    trial_end_date: datetime,
    upgrade_url: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = load_email_config()
    svc = EmailService(cfg)

    app_name = os.getenv("APP_NAME", cfg.from_name or "Schedulefy")
    subject = f"Your free trial has ended | {app_name}"

    text = (
        f"Hi {fullname or ''},\n\n"
        f"Your {trial_days}-day free trial of {plan_name} has ended on "
        f"{trial_end_date.strftime('%Y-%m-%d')}.\n\n"
        f"To continue using {app_name}, please upgrade your plan.\n"
        f"{'Upgrade here: ' + upgrade_url if upgrade_url else ''}\n\n"
        f"— {app_name}"
    )

    return svc.send_templated(
        to=email,
        subject=subject,
        template="email/trial_ended.html",
        context={
            "email": email,
            "fullname": fullname,
            "app_name": app_name,
            "plan_name": plan_name,
            "trial_days": trial_days,
            "trial_end_date": trial_end_date.strftime("%Y-%m-%d"),
            "upgrade_url": upgrade_url,
            "support_email": os.getenv("SUPPORT_EMAIL", "support@schedulefy.org"),
        },
        text_fallback=text,
        tags=["trial", "expired"],
        meta={
            "email_type": "trial_ended",
            "plan_name": plan_name,
        },
    )


# =========================================================
# TRIAL CANCELLED EMAIL
# =========================================================
def send_trial_cancelled_email(
    *,
    email: str,
    fullname: Optional[str],
    plan_name: str,
    cancelled_at: Optional[datetime] = None,
    reason: Optional[str] = None,
    upgrade_url: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = load_email_config()
    svc = EmailService(cfg)

    app_name = os.getenv("APP_NAME", cfg.from_name or "Schedulefy")
    subject = f"Your free trial was cancelled | {app_name}"

    cancelled_at_str = (
        cancelled_at.strftime("%Y-%m-%d %H:%M")
        if cancelled_at else None
    )

    text = (
        f"Hi {fullname or ''},\n\n"
        f"Your free trial of {plan_name} has been cancelled.\n\n"
        f"{'Reason: ' + reason if reason else ''}\n"
        f"{'Cancelled at: ' + cancelled_at_str if cancelled_at_str else ''}\n\n"
        f"You can subscribe anytime to continue using {app_name}.\n"
        f"{'Choose a plan: ' + upgrade_url if upgrade_url else ''}\n\n"
        f"— {app_name}"
    )

    return svc.send_templated(
        to=email,
        subject=subject,
        template="email/trial_cancelled.html",
        context={
            "email": email,
            "fullname": fullname,
            "app_name": app_name,
            "plan_name": plan_name,
            "cancelled_at": cancelled_at_str,
            "reason": reason,
            "upgrade_url": upgrade_url,
            "support_email": os.getenv("SUPPORT_EMAIL", "support@schedulefy.org"),
        },
        text_fallback=text,
        tags=["trial", "cancelled"],
        meta={
            "email_type": "trial_cancelled",
            "plan_name": plan_name,
        },
    )








