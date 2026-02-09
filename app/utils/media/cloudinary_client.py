# app/utils/media/cloudinary_client.py
import os
import uuid
from typing import Optional, Dict, Any

import cloudinary
import cloudinary.uploader


def init_cloudinary():
    cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET"),
        secure=True,
    )


def upload_image_file(file_storage, folder: str, public_id: str | None = None) -> dict:
    """
    Uploads a Werkzeug FileStorage image to Cloudinary.
    """
    init_cloudinary()

    options = {
        "folder": folder,
        "resource_type": "image",
        "overwrite": True,
        "secure": True,
    }
    if public_id:
        options["public_id"] = public_id

    result = cloudinary.uploader.upload(file_storage, **options)

    return {
        "url": result.get("secure_url"),
        "public_id": result.get("public_id"),
        "raw": result,
    }


def upload_video_file(file_obj, folder: str, public_id: str):
    """
    Uploads a video to Cloudinary.
    """
    init_cloudinary()

    res = cloudinary.uploader.upload(
        file_obj,
        folder=folder,
        public_id=public_id,
        resource_type="video",
        overwrite=True,
        secure=True,
    )

    return {
        "url": res.get("secure_url") or res.get("url"),
        "public_id": res.get("public_id"),
        "raw": res,
    }


def upload_raw_bytes(
    file_bytes: bytes,
    *,
    folder: str,
    filename: str,
    public_id: Optional[str] = None,
    content_type: str = "application/pdf",
) -> Dict[str, Any]:
    """
    Upload bytes to Cloudinary as a RAW asset (PDF, docs, etc).
    IMPORTANT: resource_type must be "raw" or Cloudinary will treat it as image/video.
    """
    init_cloudinary()

    options = {
        "folder": folder,
        "resource_type": "raw",
        "overwrite": True,
        "use_filename": True,
        "unique_filename": False,
        "filename_override": filename,
    }
    if public_id:
        options["public_id"] = public_id

    # Cloudinary accepts bytes directly
    result = cloudinary.uploader.upload(file_bytes, **options)

    return {
        "url": result.get("secure_url"),
        "public_id": result.get("public_id"),
        "bytes": result.get("bytes"),
        "format": result.get("format"),
        "resource_type": result.get("resource_type"),
        "raw": result,
        "content_type": content_type,
        "filename": filename,
    }


def upload_invoice_and_get_asset(
    *,
    business_id: str,
    user__id: str,
    invoice_number: str,
    invoice_pdf_bytes: bytes,
) -> Dict[str, Any]:
    """
    Upload invoice PDF bytes to Cloudinary and return a stable asset dict to store in DB.
    """
    folder = f"invoices/{business_id}/{user__id}"
    public_id = f"invoice_{invoice_number}_{uuid.uuid4().hex}"

    uploaded = upload_raw_bytes(
        invoice_pdf_bytes,
        folder=folder,
        filename=f"Invoice-{invoice_number}.pdf",
        public_id=public_id,
        content_type="application/pdf",
    )

    return {
        "asset_provider": "cloudinary",
        "asset_type": "pdf",
        "public_id": uploaded.get("public_id"),
        "url": uploaded.get("url"),
        "bytes": uploaded.get("bytes"),
        "filename": uploaded.get("filename"),
        "content_type": uploaded.get("content_type"),
    }