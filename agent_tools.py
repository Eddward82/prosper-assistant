from pymongo import MongoClient
from datetime import datetime
from dotenv import load_dotenv
import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

    # Use phone as primary key if available, fall back to email, then name
    lookup = _customer_lookup(customer_name, customer_email, customer_phone, business_id)
    existing = customers.find_one({**lookup, "business_id": business_id})
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
    return result.modified_count


# ── 6. EMAIL HELPERS ────────────────────────────────
def _make_smtp_connection():
    sender_email = os.getenv("GMAIL_USER")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
    server.login(sender_email, sender_password)
    return server, sender_email


def send_invoice_email(customer_name, customer_email, invoice_number, items, total_amount, business_name):
    try:
        server, sender_email = _make_smtp_connection()
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Invoice {invoice_number} from {business_name}"
        msg["From"] = sender_email
        msg["To"] = customer_email

        items_html = "".join(
            f"<tr><td>{item['description']}</td><td>NGN {item['amount']:,}</td></tr>"
            for item in items
        )
        html = f"""<html><body>
<h2>Invoice from {business_name}</h2>
<p>Dear {customer_name},</p>
<p>Please find your invoice below:</p>
<table border='1' cellpadding='8'>
  <tr><th>Description</th><th>Amount</th></tr>
  {items_html}
  <tr><td><strong>Total</strong></td><td><strong>NGN {total_amount:,}</strong></td></tr>
</table>
<p>Please make payment at your earliest convenience.</p>
<p>Thank you for your business!</p>
<p><strong>{business_name}</strong></p>
</body></html>"""

        msg.attach(MIMEText(html, "html"))
        with server:
            server.sendmail(sender_email, customer_email, msg.as_string())
        logger.info("Invoice email sent to %s", customer_email)
        return True
    except Exception as e:
        logger.error("Invoice email error: %s", e)
        return False


def send_reminder_email(customer_name, customer_email, invoice_number, total_amount, days_overdue):
    try:
        server, sender_email = _make_smtp_connection()
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Payment Reminder — Invoice {invoice_number}"
        msg["From"] = sender_email
        msg["To"] = customer_email

        html = f"""<html><body>
<h2>Payment Reminder</h2>
<p>Dear {customer_name},</p>
<p>This is a friendly reminder that invoice <strong>{invoice_number}</strong>
for <strong>NGN {total_amount:,}</strong> is now <strong>{days_overdue} days overdue.</strong></p>
<p>Please make payment as soon as possible.</p>
<p>If you have already made payment, please disregard this message.</p>
<p>Thank you.</p>
</body></html>"""

        msg.attach(MIMEText(html, "html"))
        with server:
            server.sendmail(sender_email, customer_email, msg.as_string())
        logger.info("Reminder email sent to %s", customer_email)
        return True
    except Exception as e:
        logger.error("Reminder email error: %s", e)
        return False


def send_welcome_email(customer_name, customer_email, business_name):
    try:
        server, sender_email = _make_smtp_connection()
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Welcome! You're now a customer of {business_name}"
        msg["From"] = sender_email
        msg["To"] = customer_email

        html = f"""<html><body>
<h2>Welcome, {customer_name}!</h2>
<p>You have been added as a customer of <strong>{business_name}</strong>.</p>
<p>You will receive invoices and updates from us going forward.</p>
<p>Thank you for your business!</p>
</body></html>"""

        msg.attach(MIMEText(html, "html"))
        with server:
            server.sendmail(sender_email, customer_email, msg.as_string())
        logger.info("Welcome email sent to %s", customer_email)
        return True
    except Exception as e:
        logger.error("Welcome email error: %s", e)
        return False
