# app/utils/media/spaces_client.py

"""
DigitalOcean Spaces Storage Client
=====================================
S3-compatible object storage via boto3.
Drop-in replacement for cloudinary_client.py with matching function signatures.

Environment variables:
  DO_SPACES_KEY        - Spaces access key
  DO_SPACES_SECRET     - Spaces secret key
  DO_SPACES_REGION     - e.g. "nyc3", "ams3", "sgp1", "lon1", "fra1"
  DO_SPACES_BUCKET     - Your Space name (e.g. "worshipdesk-uploads")
  DO_SPACES_CDN_DOMAIN - Optional CDN endpoint (e.g. "cdn.worshipdesk.org")
                         If not set, uses: https://{bucket}.{region}.digitaloceanspaces.com
"""

import os
import io
import uuid
import mimetypes
from typing import Optional, Dict, Any

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from ..logger import Log


# ═══════════════════════════════════════════════════════════════
# CLIENT INITIALISATION
# ═══════════════════════════════════════════════════════════════

_client_cache = {"client": None}


def _get_config():
    return {
        "key": os.getenv("DO_SPACES_KEY", ""),
        "secret": os.getenv("DO_SPACES_SECRET", ""),
        "region": os.getenv("DO_SPACES_REGION", "nyc3"),
        "bucket": os.getenv("DO_SPACES_BUCKET", ""),
        "cdn_domain": os.getenv("DO_SPACES_CDN_DOMAIN", ""),
    }


def _get_client():
    """Get or create a cached boto3 S3 client for DigitalOcean Spaces."""
    if _client_cache["client"]:
        return _client_cache["client"]

    config = _get_config()
    if not config["key"] or not config["secret"]:
        raise ValueError("DO_SPACES_KEY and DO_SPACES_SECRET are required")

    session = boto3.session.Session()
    client = session.client(
        "s3",
        region_name=config["region"],
        endpoint_url=f"https://{config['region']}.digitaloceanspaces.com",
        aws_access_key_id=config["key"],
        aws_secret_access_key=config["secret"],
    )

    _client_cache["client"] = client
    return client


def _build_url(key: str) -> str:
    """Build the public URL for an uploaded object."""
    config = _get_config()

    # Use CDN domain if configured
    if config["cdn_domain"]:
        cdn = config["cdn_domain"].rstrip("/")
        if not cdn.startswith("http"):
            cdn = f"https://{cdn}"
        return f"{cdn}/{key}"

    # Default Spaces URL
    return f"https://{config['bucket']}.{config['region']}.digitaloceanspaces.com/{key}"


def _guess_content_type(filename: str, fallback: str = "application/octet-stream") -> str:
    """Guess content type from filename."""
    ct, _ = mimetypes.guess_type(filename)
    return ct or fallback


# ═══════════════════════════════════════════════════════════════
# UPLOAD FUNCTIONS (matching cloudinary_client.py signatures)
# ═══════════════════════════════════════════════════════════════

def upload_image_file(file_storage, folder: str, public_id: str | None = None) -> dict:
    """
    Upload a Werkzeug FileStorage image to DigitalOcean Spaces.
    Replaces cloudinary_client.upload_image_file.

    Args:
        file_storage: Werkzeug FileStorage object
        folder: Folder path in the Space (e.g. "profiles/business_123")
        public_id: Optional filename without extension

    Returns:
        dict with url, public_id, raw
    """
    log_tag = "[spaces_client.upload_image_file]"
    config = _get_config()

    try:
        client = _get_client()

        # Determine filename
        original_filename = file_storage.filename or "image"
        ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "jpg"
        filename = f"{public_id}.{ext}" if public_id else f"{uuid.uuid4().hex}.{ext}"

        # Build key (path in Space)
        key = f"{folder.strip('/')}/{filename}"

        # Determine content type
        content_type = file_storage.content_type or _guess_content_type(filename, "image/jpeg")

        # Read file bytes
        file_storage.seek(0)
        file_bytes = file_storage.read()

        # Upload
        client.put_object(
            Bucket=config["bucket"],
            Key=key,
            Body=file_bytes,
            ACL="public-read",
            ContentType=content_type,
            CacheControl="max-age=31536000",
        )

        url = _build_url(key)
        Log.info(f"{log_tag} Uploaded: {key} ({len(file_bytes)} bytes)")

        return {
            "url": url,
            "public_id": key,
            "raw": {
                "key": key,
                "bucket": config["bucket"],
                "size": len(file_bytes),
                "content_type": content_type,
            },
        }

    except (ClientError, NoCredentialsError) as e:
        Log.error(f"{log_tag} Upload failed: {e}")
        raise
    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        raise


def upload_video_file(file_obj, folder: str, public_id: str) -> dict:
    """
    Upload a video file to DigitalOcean Spaces.
    Replaces cloudinary_client.upload_video_file.
    """
    log_tag = "[spaces_client.upload_video_file]"
    config = _get_config()

    try:
        client = _get_client()

        # Determine extension
        if hasattr(file_obj, "filename") and file_obj.filename:
            ext = file_obj.filename.rsplit(".", 1)[-1].lower() if "." in file_obj.filename else "mp4"
        else:
            ext = "mp4"

        filename = f"{public_id}.{ext}"
        key = f"{folder.strip('/')}/{filename}"

        content_type = _guess_content_type(filename, "video/mp4")

        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        if hasattr(file_obj, "read"):
            file_bytes = file_obj.read()
        else:
            file_bytes = file_obj

        client.put_object(
            Bucket=config["bucket"],
            Key=key,
            Body=file_bytes,
            ACL="public-read",
            ContentType=content_type,
        )

        url = _build_url(key)
        Log.info(f"{log_tag} Uploaded: {key} ({len(file_bytes)} bytes)")

        return {
            "url": url,
            "public_id": key,
            "raw": {
                "key": key,
                "bucket": config["bucket"],
                "size": len(file_bytes),
                "content_type": content_type,
            },
        }

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        raise


def upload_raw_bytes(
    file_bytes: bytes,
    *,
    folder: str,
    filename: str,
    public_id: Optional[str] = None,
    content_type: str = "application/pdf",
) -> Dict[str, Any]:
    """
    Upload raw bytes (PDF, docs, etc.) to DigitalOcean Spaces.
    Replaces cloudinary_client.upload_raw_bytes.
    """
    log_tag = "[spaces_client.upload_raw_bytes]"
    config = _get_config()

    try:
        client = _get_client()

        # Build key
        if public_id:
            ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
            key_filename = f"{public_id}.{ext}" if ext else public_id
        else:
            key_filename = filename

        key = f"{folder.strip('/')}/{key_filename}"

        client.put_object(
            Bucket=config["bucket"],
            Key=key,
            Body=file_bytes,
            ACL="public-read",
            ContentType=content_type,
            ContentDisposition=f'inline; filename="{filename}"',
        )

        url = _build_url(key)
        Log.info(f"{log_tag} Uploaded: {key} ({len(file_bytes)} bytes)")

        return {
            "url": url,
            "public_id": key,
            "bytes": len(file_bytes),
            "format": filename.rsplit(".", 1)[-1] if "." in filename else "",
            "resource_type": "raw",
            "raw": {
                "key": key,
                "bucket": config["bucket"],
                "size": len(file_bytes),
            },
            "content_type": content_type,
            "filename": filename,
        }

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        raise


def upload_invoice_and_get_asset(
    *,
    business_id: str,
    user__id: str,
    invoice_number: str,
    invoice_pdf_bytes: bytes,
) -> Dict[str, Any]:
    """
    Upload invoice PDF to DigitalOcean Spaces.
    Replaces cloudinary_client.upload_invoice_and_get_asset.
    """
    folder = f"invoices/{business_id}/{user__id}"
    public_id = f"invoice_{invoice_number}_{uuid.uuid4().hex[:8]}"

    uploaded = upload_raw_bytes(
        invoice_pdf_bytes,
        folder=folder,
        filename=f"Invoice-{invoice_number}.pdf",
        public_id=public_id,
        content_type="application/pdf",
    )

    return {
        "asset_provider": "digitalocean_spaces",
        "asset_type": "pdf",
        "public_id": uploaded.get("public_id"),
        "url": uploaded.get("url"),
        "bytes": uploaded.get("bytes"),
        "filename": uploaded.get("filename"),
        "content_type": uploaded.get("content_type"),
    }


# ═══════════════════════════════════════════════════════════════
# ADDITIONAL UTILITIES
# ═══════════════════════════════════════════════════════════════

def upload_document(
    file_storage,
    *,
    folder: str,
    public_id: Optional[str] = None,
    acl: str = "public-read",
) -> Dict[str, Any]:
    """
    Upload any document (PDF, DOCX, XLSX, etc.) from a FileStorage object.
    """
    log_tag = "[spaces_client.upload_document]"
    config = _get_config()

    try:
        client = _get_client()

        original_filename = file_storage.filename or "document"
        ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else ""
        filename = f"{public_id}.{ext}" if public_id and ext else (f"{public_id}" if public_id else f"{uuid.uuid4().hex}_{original_filename}")

        key = f"{folder.strip('/')}/{filename}"
        content_type = file_storage.content_type or _guess_content_type(original_filename)

        file_storage.seek(0)
        file_bytes = file_storage.read()

        client.put_object(
            Bucket=config["bucket"],
            Key=key,
            Body=file_bytes,
            ACL=acl,
            ContentType=content_type,
            ContentDisposition=f'inline; filename="{original_filename}"',
        )

        url = _build_url(key)
        Log.info(f"{log_tag} Uploaded: {key} ({len(file_bytes)} bytes)")

        return {
            "url": url,
            "public_id": key,
            "filename": original_filename,
            "size": len(file_bytes),
            "content_type": content_type,
        }

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        raise


def delete_file(key: str) -> bool:
    """
    Delete a file from DigitalOcean Spaces by its key (public_id).

    Args:
        key: The object key (e.g. "profiles/business_123/member_456.jpg")

    Returns:
        bool
    """
    log_tag = f"[spaces_client.delete_file][{key}]"
    config = _get_config()

    try:
        client = _get_client()
        client.delete_object(Bucket=config["bucket"], Key=key)
        Log.info(f"{log_tag} Deleted")
        return True
    except Exception as e:
        Log.error(f"{log_tag} Error: {e}")
        return False


def get_presigned_url(key: str, expires_in: int = 3600) -> Optional[str]:
    """
    Generate a presigned URL for private file access.

    Args:
        key: Object key
        expires_in: URL validity in seconds (default 1 hour)

    Returns:
        Presigned URL or None
    """
    config = _get_config()
    try:
        client = _get_client()
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": config["bucket"], "Key": key},
            ExpiresIn=expires_in,
        )
        return url
    except Exception as e:
        Log.error(f"[spaces_client.get_presigned_url] {e}")
        return None


def list_files(prefix: str, max_keys: int = 100) -> list:
    """
    List files under a prefix.

    Args:
        prefix: Folder path (e.g. "profiles/business_123/")
        max_keys: Maximum results

    Returns:
        List of dicts with key, size, last_modified
    """
    config = _get_config()
    try:
        client = _get_client()
        response = client.list_objects_v2(
            Bucket=config["bucket"],
            Prefix=prefix,
            MaxKeys=max_keys,
        )

        files = []
        for obj in response.get("Contents", []):
            files.append({
                "key": obj["Key"],
                "size": obj["Size"],
                "last_modified": obj["LastModified"].isoformat() if obj.get("LastModified") else None,
                "url": _build_url(obj["Key"]),
            })

        return files

    except Exception as e:
        Log.error(f"[spaces_client.list_files] {e}")
        return []


def get_storage_usage(prefix: str = "") -> Dict[str, Any]:
    """
    Calculate total storage usage under a prefix.

    Args:
        prefix: Optional prefix to scope (e.g. "profiles/business_123/")

    Returns:
        dict with total_bytes, file_count
    """
    config = _get_config()
    try:
        client = _get_client()
        paginator = client.get_paginator("list_objects_v2")

        total_bytes = 0
        file_count = 0

        for page in paginator.paginate(Bucket=config["bucket"], Prefix=prefix):
            for obj in page.get("Contents", []):
                total_bytes += obj.get("Size", 0)
                file_count += 1

        return {
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / (1024 * 1024), 2),
            "total_gb": round(total_bytes / (1024 * 1024 * 1024), 4),
            "file_count": file_count,
        }

    except Exception as e:
        Log.error(f"[spaces_client.get_storage_usage] {e}")
        return {"total_bytes": 0, "total_mb": 0, "total_gb": 0, "file_count": 0}
