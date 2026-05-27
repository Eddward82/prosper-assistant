from pymongo import MongoClient
from datetime import datetime
from dotenv import load_dotenv
import os
import logging
import httpx

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_client = None
_db = None

def get_db():
    global _client, _db
    if _db is None:
        _client = MongoClient(os.getenv("MONGODB_URI"))
        _db = _client[os.getenv("DB_NAME")]
    return _db


# ── 1. SAVE AN INVOICE ──────────────────────────────
def save_invoice(customer_name, customer_email, items, total_amount, business_name, business_id="default", customer_phone=""):
    db = get_db()
    invoices = db["invoice"]
    customers = db["customers"]

    count = invoices.count_documents({"business_id": business_id})
    invoice_number = f"INV-{str(count + 1).zfill(3)}"

    invoices.insert_one({
        "business_id": business_id,
        "invoice_number": invoice_number,
        "customer_name": customer_name,
        "customer_email": customer_email,
        "customer_phone": customer_phone,
        "items": items,
        "total_amount": total_amount,
        "status": "unpaid",
        "date_created": datetime.now().strftime("%Y-%m-%d"),
        "due_date": "",
        "business_name": business_name
    })

    # Look up customer strictly within this business only
    if customer_phone:
        existing = customers.find_one({"customer_phone": customer_phone, "business_id": business_id})
    elif customer_email:
        existing = customers.find_one({"customer_email": customer_email, "business_id": business_id})
    else:
        existing = customers.find_one({"customer_name": customer_name, "business_id": business_id})
    if existing:
        update = {"$inc": {"outstanding_balance": total_amount, "total_invoiced": total_amount}}
        # Fill in missing contact info if now provided
        set_fields = {}
        if customer_phone and not existing.get("customer_phone"):
            set_fields["customer_phone"] = customer_phone
        if customer_email and not existing.get("customer_email"):
            set_fields["customer_email"] = customer_email
        if set_fields:
            update["$set"] = set_fields
        customers.update_one({"_id": existing["_id"]}, update)
    else:
        customers.insert_one({
            "business_id": business_id,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "customer_phone": customer_phone,
            "outstanding_balance": total_amount,
            "total_invoiced": total_amount,
            "total_paid": 0
        })

    logger.info("Invoice %s saved for %s", invoice_number, customer_name)
    return invoice_number


def _customer_lookup(name, email, phone, business_id):
    """Build the best available unique lookup for a customer."""
    if phone:
        return {"customer_phone": phone}
    if email:
        return {"customer_email": email}
    return {"customer_name": name}


# ── 2. FIND CUSTOMER (with disambiguation) ──────────
def find_customer(customer_name, business_id, customer_phone="", customer_email=""):
    """
    Returns (customer_doc, ambiguous:bool, matches:list).
    If phone or email given, match exactly.
    If only name given and multiple records match, return ambiguous=True.
    """
    db = get_db()
    customers = db["customers"]

    if customer_phone:
        doc = customers.find_one({"customer_phone": customer_phone, "business_id": business_id})
        return (doc, False, [doc] if doc else [])

    if customer_email:
        doc = customers.find_one({"customer_email": customer_email, "business_id": business_id})
        return (doc, False, [doc] if doc else [])

    matches = list(customers.find({"customer_name": customer_name, "business_id": business_id}, {"_id": 0}))
    if len(matches) == 1:
        return (matches[0], False, matches)
    if len(matches) > 1:
        return (None, True, matches)
    return (None, False, [])


# ── 3. GET UNPAID INVOICES ──────────────────────────
def get_unpaid_invoices(business_id="default"):
    db = get_db()
    unpaid = list(db["invoice"].find({"status": "unpaid", "business_id": business_id}, {"_id": 0}))
    logger.info("Found %d unpaid invoices for business_id=%s", len(unpaid), business_id)
    return unpaid


# ── 4. LOG A SALE ───────────────────────────────────
def log_sale(item, quantity, sale_amount, cost_amount, business_id="default"):
    db = get_db()
    profit = sale_amount - cost_amount
    db["sales"].insert_one({
        "business_id": business_id,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "item": item,
        "quantity": quantity,
        "sale_amount": sale_amount,
        "cost_amount": cost_amount,
        "profit": profit,
        "recorded_by": "Prosper Assistant"
    })
    logger.info("Sale recorded — %d %s | Revenue: NGN %s | Profit: NGN %s", quantity, item, f"{sale_amount:,}", f"{profit:,}")
    return profit


# ── 5. UPDATE CUSTOMER PHONE ────────────────────────
def update_customer_phone(customer_name, customer_phone, business_id="default"):
    db = get_db()
    customers = db["customers"]
    result = customers.update_many(
        {"customer_name": customer_name, "business_id": business_id},
        {"$set": {"customer_phone": customer_phone}}
    )
    return result.matched_count


# ── 6. EMAIL HELPERS ────────────────────────────────
RESEND_FROM = "Prosper Assistant <invoices@prosperassistant.online>"


def _send_via_resend(to: str, subject: str, html: str, reply_to: str = "") -> bool:
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        logger.error("RESEND_API_KEY not set")
        return False
    try:
        payload = {"from": RESEND_FROM, "to": [to], "subject": subject, "html": html}
        if reply_to:
            payload["reply_to"] = [reply_to]
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        if r.status_code == 200 or r.status_code == 201:
            logger.info("Email sent to %s via Resend", to)
            return True
        logger.error("Resend error %s: %s", r.status_code, r.text)
        return False
    except Exception as e:
        logger.error("Resend exception: %s", e)
        return False


def send_invoice_email(customer_name, customer_email, invoice_number, items, total_amount, business_name, business_email=""):
    items_html = "".join(
        f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{item['description']}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #eee;text-align:right'>NGN {item['amount']:,}</td></tr>"
        for item in items
    )
    contact_line = f"<p>To contact us, reply to this email or reach us at <a href='mailto:{business_email}'>{business_email}</a>.</p>" if business_email else ""
    html = f"""<html><body style='font-family:Arial,sans-serif;color:#1a1a2e;max-width:600px;margin:auto'>
<div style='background:#0d3d26;padding:24px;border-radius:8px 8px 0 0'>
  <h1 style='color:white;margin:0;font-size:22px'>Invoice from {business_name}</h1>
</div>
<div style='padding:24px;border:1px solid #e8eaed;border-top:none;border-radius:0 0 8px 8px'>
  <p>Dear <strong>{customer_name}</strong>,</p>
  <p>Please find your invoice details below:</p>
  <table style='width:100%;border-collapse:collapse;margin:16px 0'>
    <thead><tr style='background:#f1f5f9'>
      <th style='padding:10px;text-align:left'>Description</th>
      <th style='padding:10px;text-align:right'>Amount</th>
    </tr></thead>
    <tbody>{items_html}</tbody>
    <tfoot><tr style='background:#0d3d26;color:white'>
      <td style='padding:10px;font-weight:bold'>Total</td>
      <td style='padding:10px;text-align:right;font-weight:bold'>NGN {total_amount:,}</td>
    </tr></tfoot>
  </table>
  <p>Please make payment at your earliest convenience.</p>
  {contact_line}
  <p>Thank you for your business!</p>
  <p style='color:#666;font-size:13px'>Powered by <strong>Prosper Assistant</strong> · prosperassistant.online</p>
</div>
</body></html>"""
    return _send_via_resend(customer_email, f"Invoice {invoice_number} from {business_name}", html, reply_to=business_email)


def send_reminder_email(customer_name, customer_email, invoice_number, total_amount, days_overdue, business_email=""):
    html = f"""<html><body style='font-family:Arial,sans-serif;color:#1a1a2e;max-width:600px;margin:auto'>
<div style='background:#0d3d26;padding:24px;border-radius:8px 8px 0 0'>
  <h1 style='color:white;margin:0;font-size:22px'>Payment Reminder</h1>
</div>
<div style='padding:24px;border:1px solid #e8eaed;border-top:none;border-radius:0 0 8px 8px'>
  <p>Dear <strong>{customer_name}</strong>,</p>
  <p>This is a friendly reminder that invoice <strong>{invoice_number}</strong>
  for <strong>NGN {total_amount:,}</strong> is now <strong>{days_overdue} days overdue.</strong></p>
  <p>Please make payment as soon as possible.</p>
  <p>If you have already made payment, please disregard this message.</p>
  <p style='color:#666;font-size:13px'>Powered by <strong>Prosper Assistant</strong> · prosperassistant.online</p>
</div>
</body></html>"""
    return _send_via_resend(customer_email, f"Payment Reminder — Invoice {invoice_number}", html, reply_to=business_email)


def send_welcome_email(customer_name, customer_email, business_name):
    html = f"""<html><body style='font-family:Arial,sans-serif;color:#1a1a2e;max-width:600px;margin:auto'>
<div style='background:#0d3d26;padding:24px;border-radius:8px 8px 0 0'>
  <h1 style='color:white;margin:0;font-size:22px'>Welcome to {business_name}!</h1>
</div>
<div style='padding:24px;border:1px solid #e8eaed;border-top:none;border-radius:0 0 8px 8px'>
  <p>Dear <strong>{customer_name}</strong>,</p>
  <p>You have been added as a customer of <strong>{business_name}</strong>.</p>
  <p>You will receive invoices and updates from us going forward.</p>
  <p>Thank you for your business!</p>
  <p style='color:#666;font-size:13px'>Powered by <strong>Prosper Assistant</strong> · prosperassistant.online</p>
</div>
</body></html>"""
    return _send_via_resend(customer_email, f"Welcome! You're now a customer of {business_name}", html)
