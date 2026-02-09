#app/utils/media/cloudinary_client.py

import os, uuid
import cloudinary
import cloudinary.uploader

def init_cloudinary():
    cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET"),
        secure=True
    )

def upload_image_file(file_storage, folder: str, public_id: str | None = None) -> dict:
    """
    Uploads a Werkzeug FileStorage to Cloudinary and returns {url, public_id, raw}.
    """
    init_cloudinary()

    options = {
        "folder": folder,
        "resource_type": "image",
        "overwrite": True,
    }
    if public_id:
        options["public_id"] = public_id

    # file_storage is request.files["image"]
    result = cloudinary.uploader.upload(file_storage, **options)

    return {
        "url": result.get("secure_url"),
        "public_id": result.get("public_id"),
        "raw": result
    }

def upload_video_file(file_obj, folder: str, public_id: str):
    """
    Uploads a video file to Cloudinary and returns:
      {"url": <secure_url>, "public_id": <public_id>, "raw": <full response>}
    """
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

def _upload_raw_file(
    file_bytes: bytes,
    folder: str,
    filename: str,
    public_id: str | None = None,
    content_type: str = "application/pdf",
) -> dict:
    """
    Uploads bytes (PDF) to Cloudinary as a raw asset and returns {url, public_id, raw}.
    """
    init_cloudinary()

    options = {
        "folder": folder,
        "resource_type": "raw",     # ✅ IMPORTANT for pdf
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
        "raw": result,
        "bytes": result.get("bytes"),
        "format": result.get("format"),
        "resource_type": result.get("resource_type"),
    }

def upload_invoice_and_get_asset(
    business_id: str,
    user__id: str,
    invoice_number: str,
    invoice_pdf_bytes: bytes,
) -> dict:
    folder = f"invoices/{business_id}/{user__id}"
    public_id = f"invoice_{invoice_number}_{uuid.uuid4().hex}"

    uploaded = _upload_raw_file(
        file_bytes=invoice_pdf_bytes,
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
    }









