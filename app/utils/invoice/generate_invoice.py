#app/utils/invoice/generate_invoice.py

import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

from app.utils.logger import Log


INVOICE_DIR = os.getenv("INVOICE_STORAGE_PATH", "/tmp/invoices")


def generate_invoice_pdf(
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
    Generates invoice PDF and stores on disk.

    Returns absolute file path.
    """

    os.makedirs(INVOICE_DIR, exist_ok=True)

    filename = f"invoice-{invoice_number}.pdf"
    filepath = os.path.join(INVOICE_DIR, filename)

    Log.info(f"[generate_invoice_pdf] Creating invoice at {filepath}")

    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4

    # ------------------------------------------------
    # HEADER
    # ------------------------------------------------
    c.setFont("Helvetica-Bold", 18)
    c.drawString(30 * mm, height - 30 * mm, "PAYMENT RECEIPT")

    c.setFont("Helvetica", 10)
    c.drawString(30 * mm, height - 38 * mm, f"Invoice #: {invoice_number}")
    c.drawString(30 * mm, height - 44 * mm, f"Date: {paid_date}")

    # ------------------------------------------------
    # CUSTOMER
    # ------------------------------------------------
    y = height - 65 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(30 * mm, y, "Billed To:")

    c.setFont("Helvetica", 10)
    c.drawString(30 * mm, y - 14, fullname)
    c.drawString(30 * mm, y - 28, email)

    # ------------------------------------------------
    # DETAILS TABLE
    # ------------------------------------------------
    y -= 70

    c.setFont("Helvetica-Bold", 11)
    c.drawString(30 * mm, y, "Subscription Details")

    rows = [
        ("Plan", plan_name),
        ("Payment Method", payment_method),
        ("Receipt #", receipt_number),
    ]

    if addon_users:
        rows.append(("Addon users", str(addon_users)))

    if package_amount:
        rows.append(("Package amount", f"{currency} {package_amount:,.2f}"))

    if total_from_amount:
        rows.append(("Total billed", f"{currency} {total_from_amount:,.2f}"))

    y -= 20
    c.setFont("Helvetica", 10)

    for label, value in rows:
        c.drawString(30 * mm, y, label)
        c.drawRightString(180 * mm, y, value)
        y -= 14

    # ------------------------------------------------
    # TOTAL
    # ------------------------------------------------
    y -= 15
    c.setFont("Helvetica-Bold", 12)
    c.drawString(30 * mm, y, "Amount Paid")
    c.drawRightString(180 * mm, y, f"{currency} {amount:,.2f}")

    # ------------------------------------------------
    # FOOTER
    # ------------------------------------------------
    c.setFont("Helvetica", 9)
    c.drawString(30 * mm, 30 * mm, "Thank you for your business.")
    c.drawString(30 * mm, 24 * mm, "— Schedulefy")

    c.showPage()
    c.save()

    return filepath