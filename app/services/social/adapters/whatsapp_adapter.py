# app/services/social/adapters/whatsapp_adapter.py

from __future__ import annotations

from typing import Any, Dict, List, Optional
import requests

from ....utils.logger import Log


class WhatsAppAdapter:
    """
    WhatsApp Cloud API (Graph API) helper.

    Key concepts:
      - Business Manager owns WABA(s)
      - WABA contains phone numbers
      - phone_number_id is used to SEND messages
      - Use a token that has:
          whatsapp_business_management (to list/manage)
          whatsapp_business_messaging (to send)

    This adapter supports:
      - List WABAs available to token (if supported)
      - List phone numbers under a WABA
      - Send:
          - text message
          - template message
          - media message (image/video/document) using uploaded media_id
      - Upload media
    """

    GRAPH_BASE = "https://graph.facebook.com"
    GRAPH_VERSION = "v20.0"

    @classmethod
    def _url(cls, path: str) -> str:
        return f"{cls.GRAPH_BASE}/{cls.GRAPH_VERSION}/{path.lstrip('/')}"

    @staticmethod
    def _safe_json(resp: requests.Response) -> Dict[str, Any]:
        try:
            return resp.json()
        except Exception:
            txt = getattr(resp, "text", None)
            return {"text": txt} if txt else {}

    @classmethod
    def _get(
        cls,
        path: str,
        *,
        access_token: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        if not access_token:
            raise Exception("Missing WhatsApp access_token")

        url = cls._url(path)
        params = params or {}
        headers = {"Authorization": f"Bearer {access_token}"}

        r = requests.get(url, headers=headers, params=params, timeout=timeout)
        data = cls._safe_json(r)

        if r.status_code >= 400:
            raise Exception(f"WhatsApp Graph GET error {r.status_code}: {data}")
        return data

    @classmethod
    def _post_json(
        cls,
        path: str,
        *,
        access_token: str,
        payload: Dict[str, Any],
        timeout: int = 30,
    ) -> Dict[str, Any]:
        if not access_token:
            raise Exception("Missing WhatsApp access_token")

        url = cls._url(path)
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        data = cls._safe_json(r)

        if r.status_code >= 400:
            raise Exception(f"WhatsApp Graph POST error {r.status_code}: {data}")
        return data

    # ---------------------------------------------------------------------
    # Discovery (optional)
    # ---------------------------------------------------------------------
    @classmethod
    def list_whatsapp_business_accounts(cls, *, access_token: str) -> List[Dict[str, Any]]:
        """
        NOTE:
          Depending on your token type / app configuration, /me/whatsapp_business_accounts
          may NOT be accessible (you saw (#100) nonexisting field on User).

          In many setups, you should list WABAs through the Business:
            GET /{business_id}/owned_whatsapp_business_accounts?fields=id,name

          So we provide both methods.
        """
        data = cls._get(
            "/me",
            access_token=access_token,
            params={"fields": "whatsapp_business_accounts{id,name}", "limit": 200},
        )
        wabas = ((data.get("whatsapp_business_accounts") or {}).get("data")) or []
        return wabas

    @classmethod
    def list_owned_wabas_for_business(
        cls,
        *,
        access_token: str,
        business_id: str,
    ) -> List[Dict[str, Any]]:
        """
        GET /{business_id}/owned_whatsapp_business_accounts?fields=id,name
        This is the most reliable for Business tokens / system users.
        """
        if not business_id:
            return []
        data = cls._get(
            f"/{business_id}/owned_whatsapp_business_accounts",
            access_token=access_token,
            params={"fields": "id,name", "limit": 200},
        )
        return data.get("data") or []

    @classmethod
    def list_phone_numbers(cls, *, access_token: str, waba_id: str) -> List[Dict[str, Any]]:
        """
        GET /{waba_id}/phone_numbers?fields=...
        """
        if not waba_id:
            return []
        data = cls._get(
            f"/{waba_id}/phone_numbers",
            access_token=access_token,
            params={
                "fields": "id,display_phone_number,verified_name,quality_rating,code_verification_status",
                "limit": 200,
            },
        )
        return data.get("data") or []

    # ---------------------------------------------------------------------
    # Messaging: send
    # ---------------------------------------------------------------------
    @classmethod
    def send_text_message(
        cls,
        *,
        access_token: str,
        phone_number_id: str,
        to_phone_e164: str,
        body: str,
        preview_url: bool = False,
    ) -> Dict[str, Any]:
        if not phone_number_id:
            raise Exception("Missing phone_number_id")
        if not to_phone_e164:
            raise Exception("Missing recipient phone (E.164)")
        if not body:
            raise Exception("Missing message body")

        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone_e164,
            "type": "text",
            "text": {"body": body, "preview_url": bool(preview_url)},
        }
        return cls._post_json(
            f"/{phone_number_id}/messages",
            access_token=access_token,
            payload=payload,
            timeout=30,
        )

    @classmethod
    def send_template_message(
        cls,
        *,
        access_token: str,
        phone_number_id: str,
        to_phone_e164: str,
        template_name: str,
        language_code: str = "en_US",
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if not phone_number_id:
            raise Exception("Missing phone_number_id")
        if not to_phone_e164:
            raise Exception("Missing recipient phone (E.164)")
        if not template_name:
            raise Exception("Missing template_name")

        tpl: Dict[str, Any] = {"name": template_name, "language": {"code": language_code}}
        if components:
            tpl["components"] = components

        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone_e164,
            "type": "template",
            "template": tpl,
        }
        return cls._post_json(
            f"/{phone_number_id}/messages",
            access_token=access_token,
            payload=payload,
            timeout=30,
        )

    @classmethod
    def send_media_message(
        cls,
        *,
        access_token: str,
        phone_number_id: str,
        to_phone_e164: str,
        media_type: str,               # "image"|"video"|"document"
        media_id: str,
        caption: Optional[str] = None,
        filename: Optional[str] = None,  # only for document
    ) -> Dict[str, Any]:
        """
        Send a media message referencing uploaded media_id.
        """
        if not phone_number_id:
            raise Exception("Missing phone_number_id")
        if not to_phone_e164:
            raise Exception("Missing recipient phone (E.164)")
        if not media_id:
            raise Exception("Missing media_id")
        mt = (media_type or "").lower().strip()
        if mt not in ("image", "video", "document"):
            raise Exception("media_type must be one of: image, video, document")

        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to_phone_e164,
            "type": mt,
            mt: {"id": media_id},
        }

        # Caption supported for image/video; for document WhatsApp uses filename (and can include caption in some cases)
        if caption and mt in ("image", "video"):
            payload[mt]["caption"] = caption

        if mt == "document":
            if filename:
                payload["document"]["filename"] = filename
            # Some accounts support caption for documents too; harmless if ignored
            if caption:
                payload["document"]["caption"] = caption

        return cls._post_json(
            f"/{phone_number_id}/messages",
            access_token=access_token,
            payload=payload,
            timeout=30,
        )

    # ---------------------------------------------------------------------
    # Media upload
    # ---------------------------------------------------------------------
    @classmethod
    def upload_media(
        cls,
        *,
        access_token: str,
        phone_number_id: str,
        file_bytes: bytes,
        mime_type: str,
        filename: str = "upload.bin",
    ) -> Dict[str, Any]:
        if not phone_number_id:
            raise Exception("Missing phone_number_id")
        if not file_bytes:
            raise Exception("file_bytes is empty")
        if not mime_type:
            raise Exception("mime_type required")

        url = cls._url(f"/{phone_number_id}/media")
        headers = {"Authorization": f"Bearer {access_token}"}

        files = {"file": (filename, file_bytes, mime_type)}
        data = {"messaging_product": "whatsapp"}

        r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        payload = cls._safe_json(r)
        if r.status_code >= 400:
            raise Exception(f"WhatsApp upload_media error {r.status_code}: {payload}")
        return payload