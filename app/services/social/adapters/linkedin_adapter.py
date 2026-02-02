# app/services/social/adapters/linkedin_adapter.py

import requests
from typing import Any, Dict, Optional, List
from urllib.parse import urlencode

from ....utils.logger import Log


class LinkedInAdapter:
    """
    LinkedIn publisher (UGC Posts for now)

    Supports:
      - Text-only UGC post for:
          destination_type="author" (person)
          destination_type="organization" (page)  [requires special permissions]
    """

    API_BASE = "https://api.linkedin.com/v2"

    @staticmethod
    def _headers(access_token: str) -> Dict[str, str]:
        if not access_token:
            raise Exception("Missing LinkedIn access_token")
        return {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _safe_json(resp: requests.Response) -> Dict[str, Any]:
        try:
            return resp.json()
        except Exception:
            # LinkedIn can return empty body on success
            txt = getattr(resp, "text", None)
            return {"text": txt} if txt else {}

    @staticmethod
    def _author_urn(destination_type: str, destination_id: str) -> str:
        dt = (destination_type or "").lower().strip()
        if dt == "author":
            return f"urn:li:person:{destination_id}"
        if dt == "organization":
            return f"urn:li:organization:{destination_id}"
        raise Exception("linkedin destination_type must be 'author' or 'organization'")

    @classmethod
    def publish_post(
        cls,
        *,
        access_token: str,
        destination_type: str,
        destination_id: str,
        text: Optional[str],
        link: Optional[str],
        media: Optional[List[dict]],
        log_tag: str,
        visibility: str = "PUBLIC",  # PUBLIC or CONNECTIONS (depending on account)
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Returns:
          {
            "success": bool,
            "provider_post_id": str|None,
            "raw": dict|None,
            "error": str|None
          }
        """

        destination_type = (destination_type or "").lower().strip()
        destination_id = str(destination_id or "").strip()

        if destination_type not in ("author", "organization"):
            return {
                "success": False,
                "provider_post_id": None,
                "raw": None,
                "error": "linkedin destination_type must be 'author' or 'organization'",
            }

        if not destination_id:
            return {
                "success": False,
                "provider_post_id": None,
                "raw": None,
                "error": "Missing destination_id",
            }

        # Build final text (append link into body for simplicity)
        final_text = (text or "").strip()
        if link:
            final_text = (final_text + "\n\n" + link).strip()

        # Must have some content
        if not final_text and not media:
            return {
                "success": False,
                "provider_post_id": None,
                "raw": None,
                "error": "LinkedIn requires text or media",
            }

        # Media support not implemented yet (requires registerUpload + upload step)
        if media:
            return {
                "success": False,
                "provider_post_id": None,
                "raw": None,
                "error": "linkedin media upload not implemented (registerUpload flow required)",
            }

        # Convert destination -> author URN
        try:
            author_urn = cls._author_urn(destination_type, destination_id)
        except Exception as e:
            return {
                "success": False,
                "provider_post_id": None,
                "raw": None,
                "error": str(e),
            }

        # Visibility enum used by ugcPosts
        visibility_enum = "PUBLIC" if visibility.upper() == "PUBLIC" else "CONNECTIONS"

        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": final_text or ""},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility_enum},
        }

        url = f"{cls.API_BASE}/ugcPosts"

        try:
            resp = requests.post(
                url,
                headers=cls._headers(access_token),
                json=payload,
                timeout=timeout,
            )

            raw = cls._safe_json(resp)
            # Include headers for debugging
            raw_meta = {
                "status_code": resp.status_code,
                "headers": {
                    "x-restli-id": resp.headers.get("x-restli-id"),
                    "location": resp.headers.get("location"),
                },
                "body": raw,
            }

            if resp.status_code >= 400:
                # Better message for org permission
                if resp.status_code == 403 and destination_type == "organization":
                    msg = (
                        "LinkedIn 403: insufficient permissions to post as organization. "
                        "Your app/token likely lacks organization posting access."
                    )
                else:
                    msg = f"LinkedIn publish error {resp.status_code}"

                Log.info(f"{log_tag} linkedin publish failed: {resp.status_code} {resp.text}")
                return {
                    "success": False,
                    "provider_post_id": None,
                    "raw": raw_meta,
                    "error": msg,
                }

            provider_post_id = resp.headers.get("x-restli-id") or resp.headers.get("location")

            return {
                "success": True,
                "provider_post_id": provider_post_id,
                "raw": raw_meta,
                "error": None,
            }

        except Exception as e:
            Log.info(f"{log_tag} linkedin publish exception: {e}")
            return {
                "success": False,
                "provider_post_id": None,
                "raw": None,
                "error": str(e),
            }