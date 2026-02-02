# app/services/social/adapters/linkedin_adapter.py

from __future__ import annotations

import requests
from typing import Any, Dict, Optional, List, Tuple

from ....utils.logger import Log


class LinkedInAdapter:
    """
    LinkedIn publisher (UGC Posts + Media Upload)

    Supports:
      - Text-only UGC post for:
          destination_type="author" (person)
          destination_type="organization" (page)  [often requires special permissions]
      - Media post (single image OR single video) via:
          1) registerUpload (assets?action=registerUpload)
          2) PUT bytes to uploadUrl
          3) ugcPosts referencing asset URN
    """

    API_BASE = "https://api.linkedin.com/v2"

    # LinkedIn upload "recipes" for feed shares
    RECIPE_IMAGE = "urn:li:digitalmediaRecipe:feedshare-image"
    RECIPE_VIDEO = "urn:li:digitalmediaRecipe:feedshare-video"

    # UGC visibility enum
    VIS_PUBLIC = "PUBLIC"
    VIS_CONNECTIONS = "CONNECTIONS"

    # shareMediaCategory enum
    MEDIA_NONE = "NONE"
    MEDIA_IMAGE = "IMAGE"
    MEDIA_VIDEO = "VIDEO"

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
    def _download_bytes(url: str, timeout: int = 60) -> Tuple[bytes, str]:
        r = requests.get(url, stream=True, timeout=timeout)
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        return r.content, ctype
    
    @staticmethod
    def _headers_upload(access_token: str, content_type: str, content_length: int) -> Dict[str, str]:
        # Upload URL is typically a LinkedIn/azure URL; may not require Authorization header,
        # but it does not hurt to include it in most cases.
        # Some upload URLs ignore auth; some require it.
        h = {
            "Content-Type": content_type or "application/octet-stream",
            "Content-Length": str(int(content_length or 0)),
        }
        # Optional: include auth (safe; if rejected, remove)
        if access_token:
            h["Authorization"] = f"Bearer {access_token}"
        return h

    @staticmethod
    def _safe_json(resp: requests.Response) -> Dict[str, Any]:
        try:
            return resp.json()
        except Exception:
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

    @staticmethod
    def _download_media_bytes(url: str, timeout: int = 60) -> Tuple[bytes, str]:
        """
        Download media from a public HTTPS URL (Cloudinary, S3, etc.)
        Returns: (bytes, content_type)
        """
        if not url:
            raise Exception("Missing media.url")
        r = requests.get(url, stream=True, timeout=timeout)
        r.raise_for_status()
        content_type = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        return r.content, content_type

    @classmethod
    def _register_upload(
        cls,
        *,
        access_token: str,
        owner_urn: str,
        recipe: str,
        log_tag: str,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        POST /assets?action=registerUpload

        owner_urn MUST match who is posting:
          - person: urn:li:person:{id}
          - org:    urn:li:organization:{id}
        """
        url = f"{cls.API_BASE}/assets?action=registerUpload"
        payload = {
            "registerUploadRequest": {
                "owner": owner_urn,
                "recipes": [recipe],
                "serviceRelationships": [
                    {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
                ],
            }
        }

        resp = requests.post(url, headers=cls._headers(access_token), json=payload, timeout=timeout)
        data = cls._safe_json(resp)

        if resp.status_code >= 400:
            raise Exception(f"{log_tag} registerUpload failed {resp.status_code}: {data}")

        return data

    @staticmethod
    def _extract_upload_url_and_asset(reg_payload: Dict[str, Any]) -> Tuple[str, str]:
        """
        Returns (upload_url, asset_urn)
        """
        value = reg_payload.get("value") or {}
        asset_urn = value.get("asset")

        mech = value.get("uploadMechanism") or {}
        http_mech = mech.get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest") or {}
        upload_url = http_mech.get("uploadUrl")

        if not asset_urn or not upload_url:
            raise Exception(f"registerUpload missing uploadUrl/asset: {reg_payload}")

        return str(upload_url), str(asset_urn)
    
    @classmethod
    def _create_ugc_post(
        cls,
        *,
        access_token: str,
        author_urn: str,
        text: str,
        media_category: str,       # "NONE" | "IMAGE" | "VIDEO"
        media_asset_urn: Optional[str],
        visibility: str,           # "PUBLIC" | "CONNECTIONS"
        timeout: int = 30,
    ) -> Dict[str, Any]:
        share = {
            "shareCommentary": {"text": text or ""},
            "shareMediaCategory": media_category,
        }

        if media_category in ("IMAGE", "VIDEO"):
            if not media_asset_urn:
                raise Exception("media_asset_urn required for IMAGE/VIDEO")
            share["media"] = [{"status": "READY", "media": media_asset_urn}]

        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": share},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
        }

        url = f"{cls.API_BASE}/ugcPosts"
        resp = requests.post(url, headers=cls._headers(access_token), json=payload, timeout=timeout)

        raw = cls._safe_json(resp)
        if resp.status_code >= 400:
            raise Exception(f"ugcPosts failed {resp.status_code}: {raw}")

        provider_post_id = resp.headers.get("x-restli-id") or resp.headers.get("location")
        return {"provider_post_id": provider_post_id, "raw": raw, "status_code": resp.status_code}
    
    @classmethod
    def _upload_to_linkedin(
        cls,
        *,
        upload_url: str,
        access_token: str,
        content_bytes: bytes,
        content_type: str,
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """
        PUT bytes to upload_url (returned by registerUpload)
        """
        if not content_bytes:
            raise Exception("Empty media bytes")

        headers = {
            "Content-Type": content_type or "application/octet-stream",
            "Content-Length": str(len(content_bytes)),
            # Some upload URLs may not require Authorization, but including is usually OK.
            "Authorization": f"Bearer {access_token}",
        }

        resp = requests.put(upload_url, headers=headers, data=content_bytes, timeout=timeout)

        if resp.status_code >= 400:
            raise Exception(f"LinkedIn upload PUT failed {resp.status_code}: {resp.text[:500]}")

        return {"status_code": resp.status_code, "etag": resp.headers.get("etag")}
    
    @classmethod
    def _upload_bytes(
        cls,
        *,
        upload_url: str,
        access_token: str,
        content_bytes: bytes,
        content_type: str,
        log_tag: str,
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """
        PUT bytes to LinkedIn-provided uploadUrl
        """
        if not upload_url:
            raise Exception("Missing upload_url")
        if not content_bytes:
            raise Exception("Empty media bytes for upload")

        headers = cls._headers_upload(access_token, content_type, len(content_bytes))

        # LinkedIn upload typically uses PUT
        resp = requests.put(upload_url, headers=headers, data=content_bytes, timeout=timeout)

        # LinkedIn can return 201/200, sometimes 204
        if resp.status_code >= 400:
            Log.info(f"{log_tag} linkedin upload PUT failed: {resp.status_code} {resp.text[:500]}")
            raise Exception(f"LinkedIn upload PUT error {resp.status_code}")

        return {
            "status_code": resp.status_code,
            "etag": resp.headers.get("etag"),
        }

    @classmethod
    def _build_ugc_payload(
        cls,
        *,
        author_urn: str,
        text: str,
        visibility_enum: str,
        media_category: str,
        media_asset_urn: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build UGC post payload for NONE / IMAGE / VIDEO.
        """
        share_content: Dict[str, Any] = {
            "shareCommentary": {"text": text or ""},
            "shareMediaCategory": media_category,
        }

        if media_category in (cls.MEDIA_IMAGE, cls.MEDIA_VIDEO):
            if not media_asset_urn:
                raise Exception("media_asset_urn required for IMAGE/VIDEO UGC post")

            # Minimal media entry
            share_content["media"] = [
                {
                    "status": "READY",
                    "media": media_asset_urn,
                }
            ]

        return {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": share_content
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": visibility_enum
            },
        }

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
        visibility: str = "PUBLIC",  # PUBLIC or CONNECTIONS
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

        media_list = media or []
        if not isinstance(media_list, list):
            return {
                "success": False,
                "provider_post_id": None,
                "raw": None,
                "error": "media must be a list",
            }

        # Must have some content
        if not final_text and not media_list:
            return {
                "success": False,
                "provider_post_id": None,
                "raw": None,
                "error": "LinkedIn requires text or media",
            }

        # For safety: LinkedIn UGC media posting can be finicky; enforce a single media item.
        if len(media_list) > 1:
            return {
                "success": False,
                "provider_post_id": None,
                "raw": {"media_count": len(media_list)},
                "error": "LinkedIn supports only 1 media item per post in this integration",
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
        visibility_enum = cls.VIS_PUBLIC if visibility.upper() == cls.VIS_PUBLIC else cls.VIS_CONNECTIONS

        # ----------------------------
        # Case 1: TEXT ONLY
        # ----------------------------
        if not media_list:
            payload = cls._build_ugc_payload(
                author_urn=author_urn,
                text=final_text or "",
                visibility_enum=visibility_enum,
                media_category=cls.MEDIA_NONE,
                media_asset_urn=None,
            )

            url = f"{cls.API_BASE}/ugcPosts"
            try:
                resp = requests.post(
                    url,
                    headers=cls._headers(access_token),
                    json=payload,
                    timeout=timeout,
                )

                raw = cls._safe_json(resp)
                raw_meta = {
                    "status_code": resp.status_code,
                    "headers": {
                        "x-restli-id": resp.headers.get("x-restli-id"),
                        "location": resp.headers.get("location"),
                    },
                    "body": raw,
                }

                if resp.status_code >= 400:
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

        # ----------------------------
        # Case 2: MEDIA (single image/video)
        # ----------------------------
        m = media_list[0] or {}
        asset_type = (m.get("asset_type") or "").lower().strip()
        media_url = m.get("url")

        if asset_type not in ("image", "video"):
            return {
                "success": False,
                "provider_post_id": None,
                "raw": {"asset_type": asset_type},
                "error": "linkedin media requires asset_type in ['image','video']",
            }

        if not media_url:
            return {
                "success": False,
                "provider_post_id": None,
                "raw": None,
                "error": "linkedin media requires media.url",
            }

        recipe = cls.RECIPE_IMAGE if asset_type == "image" else cls.RECIPE_VIDEO
        media_category = cls.MEDIA_IMAGE if asset_type == "image" else cls.MEDIA_VIDEO

        try:
            # 1) registerUpload
            reg = cls._register_upload(
                access_token=access_token,
                owner_urn=author_urn,  # IMPORTANT: owner MUST match author URN
                recipe=recipe,
                log_tag=log_tag,
                timeout=timeout,
            )
            upload_url, asset_urn = cls._extract_upload_url_and_asset(reg)

            # 2) download bytes
            content_bytes, content_type = cls._download_media_bytes(media_url, timeout=60)
            if not content_type:
                # fallback types
                content_type = "image/jpeg" if asset_type == "image" else "video/mp4"

            # 3) upload bytes
            upload_resp = cls._upload_bytes(
                upload_url=upload_url,
                access_token=access_token,
                content_bytes=content_bytes,
                content_type=content_type,
                log_tag=log_tag,
                timeout=180 if asset_type == "video" else 60,
            )

            # 4) create ugc post referencing asset URN
            payload = cls._build_ugc_payload(
                author_urn=author_urn,
                text=final_text or "",
                visibility_enum=visibility_enum,
                media_category=media_category,
                media_asset_urn=asset_urn,
            )

            url = f"{cls.API_BASE}/ugcPosts"
            resp = requests.post(
                url,
                headers=cls._headers(access_token),
                json=payload,
                timeout=timeout,
            )

            raw = cls._safe_json(resp)
            raw_meta = {
                "register_upload": reg,
                "upload": upload_resp,
                "ugc": {
                    "status_code": resp.status_code,
                    "headers": {
                        "x-restli-id": resp.headers.get("x-restli-id"),
                        "location": resp.headers.get("location"),
                    },
                    "body": raw,
                },
            }

            if resp.status_code >= 400:
                if resp.status_code == 403 and destination_type == "organization":
                    msg = (
                        "LinkedIn 403: insufficient permissions to post as organization. "
                        "Your app/token likely lacks organization posting access."
                    )
                else:
                    msg = f"LinkedIn publish error {resp.status_code}"

                Log.info(f"{log_tag} linkedin ugc publish failed: {resp.status_code} {resp.text}")
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
            Log.info(f"{log_tag} linkedin media publish exception: {e}")
            return {
                "success": False,
                "provider_post_id": None,
                "raw": {"exception": str(e)},
                "error": str(e),
            }