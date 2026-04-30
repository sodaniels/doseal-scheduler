# app/utils/media/storage_router.py

"""
Storage Provider Router
=========================
Switch between Cloudinary and DigitalOcean Spaces with one env var.

Environment variable:
  STORAGE_PROVIDER = "cloudinary" | "spaces"  (default: "cloudinary")

Usage:
  from ...utils.media.storage_router import (
      upload_image_file,
      upload_video_file,
      upload_raw_bytes,
      upload_invoice_and_get_asset,
      upload_document,
      delete_file,
  )

All functions have identical signatures regardless of provider.
"""

import os

STORAGE_PROVIDER = os.getenv("STORAGE_PROVIDER", "cloudinary").strip().lower()


if STORAGE_PROVIDER == "spaces":
    from .spaces_client import (
        upload_image_file,
        upload_video_file,
        upload_raw_bytes,
        upload_invoice_and_get_asset,
        upload_document,
        delete_file,
        get_presigned_url,
        list_files,
        get_storage_usage,
    )
elif STORAGE_PROVIDER == "cloudinary":
    from .cloudinary_client import (
        upload_image_file,
        upload_video_file,
        upload_raw_bytes,
        upload_invoice_and_get_asset,
    )

    # Cloudinary doesn't have these — provide safe stubs
    def upload_document(file_storage, *, folder, public_id=None, acl="public-read"):
        """Route to upload_raw_bytes for Cloudinary."""
        file_storage.seek(0)
        file_bytes = file_storage.read()
        filename = file_storage.filename or "document"
        content_type = file_storage.content_type or "application/octet-stream"
        return upload_raw_bytes(
            file_bytes,
            folder=folder,
            filename=filename,
            public_id=public_id,
            content_type=content_type,
        )

    def delete_file(key):
        """Delete a Cloudinary asset by public_id."""
        try:
            import cloudinary
            import cloudinary.uploader
            from .cloudinary_client import init_cloudinary
            init_cloudinary()
            result = cloudinary.uploader.destroy(key)
            return result.get("result") == "ok"
        except Exception:
            return False

    def get_presigned_url(key, expires_in=3600):
        """Cloudinary doesn't use presigned URLs — return the direct URL."""
        try:
            import cloudinary.utils
            from .cloudinary_client import init_cloudinary
            init_cloudinary()
            url, _ = cloudinary.utils.cloudinary_url(key, secure=True)
            return url
        except Exception:
            return None

    def list_files(prefix, max_keys=100):
        """List Cloudinary assets by prefix."""
        try:
            import cloudinary.api
            from .cloudinary_client import init_cloudinary
            init_cloudinary()
            result = cloudinary.api.resources(
                type="upload",
                prefix=prefix,
                max_results=max_keys,
            )
            return [
                {
                    "key": r.get("public_id"),
                    "size": r.get("bytes", 0),
                    "url": r.get("secure_url"),
                    "last_modified": r.get("created_at"),
                }
                for r in result.get("resources", [])
            ]
        except Exception:
            return []

    def get_storage_usage(prefix=""):
        """Approximate storage usage from Cloudinary."""
        try:
            import cloudinary.api
            from .cloudinary_client import init_cloudinary
            init_cloudinary()
            result = cloudinary.api.usage()
            total_bytes = result.get("storage", {}).get("usage", 0)
            return {
                "total_bytes": total_bytes,
                "total_mb": round(total_bytes / (1024 * 1024), 2),
                "total_gb": round(total_bytes / (1024 * 1024 * 1024), 4),
                "file_count": result.get("resources", 0),
            }
        except Exception:
            return {"total_bytes": 0, "total_mb": 0, "total_gb": 0, "file_count": 0}

else:
    raise ValueError(
        f"Unknown STORAGE_PROVIDER: '{STORAGE_PROVIDER}'. "
        f"Set STORAGE_PROVIDER to 'cloudinary' or 'spaces'."
    )
