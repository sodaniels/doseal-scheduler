# app/utils/invoice/generate_invoice.py
import os
from io import BytesIO
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

from app.utils.logger import Log

INVOICE_DIR = os.getenv("INVOICE_STORAGE_PATH", "/tmp/invoices")


def _draw_invoice(
    c: canvas.Canvas,
    *,
    invoice_number: str,
    fullname: str,
    email: str,
    plan_name: str,
    amount: float,
    currency: str,
    payment_method: str,
    receipt_number: str,
    paid_date: str,
    addon_users: Optional[int] = None,
    package_amount: Optional[float] = None,
    total_from_amount: Optional[float] = None,
):
    width, height = A4

    # HEADER
    c.setFont("Helvetica-Bold", 18)
    c.drawString(30 * mm, height - 30 * mm, "PAYMENT RECEIPT")

    c.setFont("Helvetica", 10)
    c.drawString(30 * mm, height - 38 * mm, f"Invoice #: {invoice_number}")
    c.drawString(30 * mm, height - 44 * mm, f"Date: {paid_date}")

    # CUSTOMER
    y = height - 65 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(30 * mm, y, "Billed To:")

    c.setFont("Helvetica", 10)
    c.drawString(30 * mm, y - 14, fullname)
    c.drawString(30 * mm, y - 28, email)

    # DETAILS
    y -= 70
    c.setFont("Helvetica-Bold", 11)
    c.drawString(30 * mm, y, "Subscription Details")

    rows = [
        ("Plan", plan_name),
        ("Payment Method", payment_method),
        ("Receipt #", receipt_number),
    ]

    if addon_users is not None:
        rows.append(("Addon users", str(addon_users)))

    if package_amount is not None:
        rows.append(("Package amount", f"{currency} {package_amount:,.2f}"))

    if total_from_amount is not None:
        rows.append(("Total billed", f"{currency} {total_from_amount:,.2f}"))

    y -= 20
    c.setFont("Helvetica", 10)

    for label, value in rows:
        c.drawString(30 * mm, y, label)
        c.drawRightString(180 * mm, y, str(value))
        y -= 14

    # TOTAL
    y -= 15
    c.setFont("Helvetica-Bold", 12)
    c.drawString(30 * mm, y, "Amount Paid")
    c.drawRightString(180 * mm, y, f"{currency} {amount:,.2f}")

    # FOOTER
    c.setFont("Helvetica", 9)
    c.drawString(30 * mm, 30 * mm, "Thank you for your business.")
    c.drawString(30 * mm, 24 * mm, "— Schedulefy")


def generate_invoice_pdf_bytes(
    *,
    invoice_number: str,
    fullname: str,
    email: str,
    plan_name: str,
    amount: float,
    currency: str,
    payment_method: str,
    receipt_number: str,
    paid_date: str,
    addon_users: int | None = None,
    package_amount: float | None = None,
    total_from_amount: float | None = None,
) -> bytes:
    """
    ✅ Best option: generate invoice into memory and return bytes.
    Avoids permission issues (like /var/app).
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    _draw_invoice(
        c,
        invoice_number=invoice_number,
        fullname=fullname,
        email=email,
        plan_name=plan_name,
        amount=amount,
        currency=currency,
        payment_method=payment_method,
        receipt_number=receipt_number,
        paid_date=paid_date,
        addon_users=addon_users,
        package_amount=package_amount,
        total_from_amount=total_from_amount,
    )

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def generate_invoice_pdf_to_disk(
    *,
    invoice_number: str,
    fullname: str,
    email: str,
    plan_name: str,
    amount: float,
    currency: str,
    payment_method: str,
    receipt_number: str,
    paid_date: str,
    addon_users: int | None = None,
    package_amount: float | None = None,
    total_from_amount: float | None = None,
) -> str:
    """
    Optional: generate invoice to disk under INVOICE_DIR (default /tmp/invoices).
    """
    os.makedirs(INVOICE_DIR, exist_ok=True)

    filename = f"invoice-{invoice_number}.pdf"
    filepath = os.path.join(INVOICE_DIR, filename)

    Log.info(f"[generate_invoice_pdf_to_disk] Creating invoice at {filepath}")

    c = canvas.Canvas(filepath, pagesize=A4)

    _draw_invoice(
        c,
        invoice_number=invoice_number,
        fullname=fullname,
        email=email,
        plan_name=plan_name,
        amount=amount,
        currency=currency,
        payment_method=payment_method,
        receipt_number=receipt_number,
        paid_date=paid_date,
        addon_users=addon_users,
        package_amount=package_amount,
        total_from_amount=total_from_amount,
    )

    c.showPage()
    c.save()

    return filepath