import os
import time
import smtplib
import requests
import jinja2
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional, Dict, Any, List, Union

from app.utils.logger import Log


# ---------- Config ----------

@dataclass
class EmailConfig:
    provider: str  # "mailgun" | "smtp"

    # common
    from_email: str
    from_name: str = "Schedulefy"
    templates_dir: str = "templates"

    # mailgun
    mailgun_api_key: Optional[str] = None
    mailgun_domain: Optional[str] = None
    mailgun_api_host: str = "api.mailgun.net"  # api.eu.mailgun.net for EU region

    # smtp
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True


def load_email_config() -> EmailConfig:
    provider = os.getenv("EMAIL_PROVIDER", "mailgun").lower()

    from_email = os.getenv("SENDER_EMAIL") or ""
    from_name = os.getenv("MAIL_NAME", "Instntmny Transfer")
    templates_dir = os.getenv("EMAIL_TEMPLATES_DIR", "templates")

    cfg = EmailConfig(
        provider=provider,
        from_email=from_email,
        from_name=from_name,
        templates_dir=templates_dir,
        # mailgun
        mailgun_api_key=os.getenv("MAILGUN_API_KEY"),
        mailgun_domain=os.getenv("INSTNTMNY_MAILGUN_DOMAIN"),
        mailgun_api_host=os.getenv("MAILGUN_API_HOST", "api.mailgun.net"),
        # smtp
        smtp_host=os.getenv("SMTP_HOST"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME"),
        smtp_password=os.getenv("SMTP_PASSWORD"),
        smtp_use_tls=os.getenv("SMTP_USE_TLS", "true").lower() == "true",
    )

    return cfg


# ---------- Templates ----------

class TemplateRenderer:
    def __init__(self, templates_dir: str):
        # makes template paths consistent no matter where you run the app from
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


# ---------- Providers ----------

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
    ) -> Dict[str, Any]:
        raise NotImplementedError


class MailgunProvider(BaseEmailProvider):
    def __init__(self, cfg: EmailConfig):
        self.cfg = cfg
        if not cfg.mailgun_api_key or not cfg.mailgun_domain:
            raise EmailSendError("Mailgun config missing: MAILGUN_API_KEY / INSTNTMNY_MAILGUN_DOMAIN")

    def _post(self, data: Dict[str, Any], max_retries: int = 3) -> requests.Response:
        url = f"https://{self.cfg.mailgun_api_host}/v3/{self.cfg.mailgun_domain}/messages"

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(
                    url,
                    auth=("api", self.cfg.mailgun_api_key),
                    data=data,
                    timeout=20,
                )
                Log.info(f"Mailgun send status={resp.status_code} attempt={attempt}")

                if resp.status_code < 400:
                    return resp

                # retry on rate limit / transient errors
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue

                # permanent failure
                raise EmailSendError(f"Mailgun error {resp.status_code}: {resp.text[:800]}")
            except requests.RequestException as exc:
                Log.error(f"Mailgun request exception attempt={attempt} err={exc}")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise EmailSendError(f"Mailgun request failed after retries: {exc}") from exc

        raise EmailSendError("Mailgun failed unexpectedly")

    def send(self, to, subject, text, html=None, reply_to=None, tags=None, meta=None):
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
        if tags:
            # Mailgun tags
            for t in tags:
                data.setdefault("o:tag", []).append(t)
        if meta:
            for k, v in meta.items():
                data[f"v:{k}"] = str(v)

        resp = self._post(data)
        return {"ok": True, "provider": "mailgun", "status_code": resp.status_code, "response": resp.json() if resp.text else {}}


class SmtpProvider(BaseEmailProvider):
    def __init__(self, cfg: EmailConfig):
        self.cfg = cfg
        required = [cfg.smtp_host, cfg.smtp_username, cfg.smtp_password]
        if any(not x for x in required):
            raise EmailSendError("SMTP config missing: SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD")

    def send(self, to, subject, text, html=None, reply_to=None, tags=None, meta=None):
        to_list = [to] if isinstance(to, str) else to

        msg = EmailMessage()
        msg["From"] = f"{self.cfg.from_name} <{self.cfg.from_email}>"
        msg["To"] = ", ".join(to_list)
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to

        # Always include text fallback
        msg.set_content(text or "")

        if html:
            msg.add_alternative(html, subtype="html")

        try:
            with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=20) as server:
                server.ehlo()
                if self.cfg.smtp_use_tls:
                    server.starttls()
                    server.ehlo()
                server.login(self.cfg.smtp_username, self.cfg.smtp_password)
                server.send_message(msg)

            return {"ok": True, "provider": "smtp", "status_code": 250, "response": {}}
        except Exception as exc:
            raise EmailSendError(f"SMTP send failed: {exc}") from exc


# ---------- Service layer (your app uses this) ----------

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
        to: str,
        subject: str,
        template: str,
        context: Dict[str, Any],
        text_fallback: Optional[str] = None,
        reply_to: Optional[str] = None,
        tags: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        html = self.renderer.render(template, **context)

        # decent default fallback (you can improve later)
        text = text_fallback or f"{subject}\n\nPlease open this email in an HTML-capable client."

        return self.provider.send(
            to=to,
            subject=subject,
            text=text,
            html=html,
            reply_to=reply_to,
            tags=tags,
            meta=meta,
        )


# ---------- Your specific emails ----------

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