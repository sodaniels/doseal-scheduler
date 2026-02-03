# app/services/social/adapters/whatsapp_adapter.py

from __future__ import annotations

from typing import Any, Dict, List, Optional
import requests

from ....utils.logger import Log


class WhatsAppAdapter:
    """
    WhatsApp Cloud API (Graph API) helper.

    Key concepts:
      - "WABA" (WhatsApp Business Account) contains phone numbers
      - "phone_number_id" is used to SEND messages
      - Discovery path (reliable):
          /me/businesses  -> for each business_id -> /{business_id}/owned_whatsapp_business_accounts
        (This avoids calling /me/whatsapp_business_accounts which can fail on User nodes.)
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

        params = params or {}
        # Graph supports either access_token param OR Authorization header.
        # We'll use access_token param for GET for simplicity.
        params["access_token"] = access_token

        url = cls._url(path)
        r = requests.get(url, params=params, timeout=timeout)
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
    # Discovery: Businesses -> Owned WABAs -> Phone Numbers
    # ---------------------------------------------------------------------
    @classmethod
    def list_user_businesses(cls, *, access_token: str) -> List[Dict[str, Any]]:
        """
        GET /me/businesses?fields=id,name
        Requires business_management permission in many setups.
        """
        data = cls._get(
            "/me/businesses",
            access_token=access_token,
            params={"fields": "id,name", "limit": 200},
        )
        return data.get("data") or []

    @classmethod
    def list_owned_whatsapp_business_accounts(
        cls,
        *,
        access_token: str,
        business_id: str,
    ) -> List[Dict[str, Any]]:
        """
        GET /{business_id}/owned_whatsapp_business_accounts?fields=id,name
        This is the reliable way to discover WABAs.  [oai_citation:1‡Facebook Developers](https://developers.facebook.com/docs/marketing-api/reference/business/owned_whatsapp_business_accounts?locale=ar_AR&utm_source=chatgpt.com)
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
    def list_whatsapp_business_accounts(cls, *, access_token: str) -> List[Dict[str, Any]]:
        """
        Returns a flattened list of WABAs the user can access by:
          /me/businesses -> /{business_id}/owned_whatsapp_business_accounts

        Output example:
          [{ "id": "...", "name": "...", "business_id": "...", "business_name": "..." }, ...]
        """
        businesses = cls.list_user_businesses(access_token=access_token)
        out: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for b in businesses:
            business_id = str(b.get("id") or "").strip()
            business_name = b.get("name")
            if not business_id:
                continue

            try:
                wabas = cls.list_owned_whatsapp_business_accounts(
                    access_token=access_token,
                    business_id=business_id,
                )
            except Exception as e:
                Log.info(f"[WhatsAppAdapter][list_whatsapp_business_accounts] owned_wabas failed business_id={business_id}: {e}")
                continue

            for w in wabas:
                waba_id = str(w.get("id") or "").strip()
                if not waba_id or waba_id in seen:
                    continue
                seen.add(waba_id)
                out.append({
                    "id": waba_id,
                    "name": w.get("name"),
                    "business_id": business_id,
                    "business_name": business_name,
                })

        return out

    @classmethod
    def list_phone_numbers(cls, *, access_token: str, waba_id: str) -> List[Dict[str, Any]]:
        """
        GET /{waba_id}/phone_numbers?fields=id,display_phone_number,verified_name,quality_rating,code_verification_status
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
        """
        POST /{phone_number_id}/messages
        """
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
        return cls._post_json(f"/{phone_number_id}/messages", access_token=access_token, payload=payload, timeout=30)

    @classmethod
    def send_media_message(
        cls,
        *,
        access_token: str,
        phone_number_id: str,
        to_phone_e164: str,
        media_type: str,            # "image" | "video" | "document"
        media_id: str,
        caption: Optional[str] = None,
        filename: Optional[str] = None,   # for document
    ) -> Dict[str, Any]:
        """
        POST /{phone_number_id}/messages
        payload for image/video/document referencing uploaded media_id
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

        node: Dict[str, Any] = {"id": media_id}
        if caption and mt in ("image", "video", "document"):
            node["caption"] = caption
        if filename and mt == "document":
            node["filename"] = filename

        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone_e164,
            "type": mt,
            mt: node,
        }
        return cls._post_json(f"/{phone_number_id}/messages", access_token=access_token, payload=payload, timeout=30)

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
        """
        POST /{phone_number_id}/media (multipart)
        returns: {"id": "<media_id>"}
        """
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