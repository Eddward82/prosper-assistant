from pymongo import MongoClient, ReturnDocument
from datetime import datetime
from dotenv import load_dotenv
from html import escape as _esc
import os
import logging
import httpx

load_dotenv()

import threading

# Thread-local client date — safe under concurrent requests
_local = threading.local()

def set_client_date(date_str):
    _local.client_date = date_str

def _today():
    return getattr(_local, "client_date", None) or datetime.now().strftime("%Y-%m-%d")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_client = None
_db = None
_db_uri = None

def get_db():
    global _client, _db, _db_uri
    uri = os.getenv("MONGODB_URI", "")
    db_name = os.getenv("DB_NAME", "")
    if _db is None or uri != _db_uri:
        if _client is not None:
            try:
                _client.close()
            except Exception:
                pass
        _client = MongoClient(uri)
        _db = _client[db_name]
        _db_uri = uri
        _ensure_indexes(_db)
    return _db


def _ensure_indexes(db):
    """Create the indexes every query path relies on. Idempotent."""
    try:
        db["sales"].create_index([("business_id", 1), ("date", -1)])
        db["invoice"].create_index([("business_id", 1), ("status", 1)])
        db["invoice"].create_index([("business_id", 1), ("invoice_number", 1)])
        db["customers"].create_index([("business_id", 1), ("customer_name", 1)])
        db["businesses"].create_index("business_id")
        db["businesses"].create_index("business_email")
        db["plans"].create_index("business_id")
    except Exception as e:
        logger.warning("Could not create indexes: %s", e)


# ── PLAN / USAGE HELPERS ────────────────────────────

FREE_LIMITS = {"invoices": 5, "sales": 5}
UPGRADE_URL = os.getenv("PAYSTACK_PAYMENT_LINK", "#upgrade")

def get_plan(business_id: str) -> dict:
    """Return the plan doc for a business, creating a free plan if missing."""
    db = get_db()
    plan = db["plans"].find_one({"business_id": business_id})
    if not plan:
        month = datetime.now().strftime("%Y-%m")
        plan = {
            "business_id": business_id,
            "plan": "free",
            "month": month,
            "invoices_used": 0,
            "sales_used": 0,
        }
        db["plans"].insert_one(plan)
    return plan

def _reset_month_if_needed(business_id: str):
    """Reset monthly counters if we're in a new month."""
    db = get_db()
    current_month = datetime.now().strftime("%Y-%m")
    db["plans"].update_one(
        {"business_id": business_id, "month": {"$ne": current_month}},
        {"$set": {"month": current_month, "invoices_used": 0, "sales_used": 0}},
    )

def check_usage_limit(business_id: str, action: str) -> str | None:
    """
    Check if a free user has hit their limit.
    action: "invoice" or "sale"
    Returns an error string if blocked, None if allowed.
    """
    _reset_month_if_needed(business_id)
    plan = get_plan(business_id)
    if plan.get("plan") == "business":
        return None
    key = "invoices_used" if action == "invoice" else "sales_used"
    limit = FREE_LIMITS["invoices"] if action == "invoice" else FREE_LIMITS["sales"]
    used = plan.get(key, 0)
    if used >= limit:
        action_label = "invoices" if action == "invoice" else "cash sales"
        return (
            f"You've used all {limit} free {action_label} this month. "
            f"Upgrade to the Business plan for unlimited access. "
            f"UPGRADE_LINK:{UPGRADE_URL}"
        )
    return None

def increment_usage(business_id: str, action: str):
    """Increment the monthly usage counter for a given action."""
    db = get_db()
    key = "invoices_used" if action == "invoice" else "sales_used"
    db["plans"].update_one(
        {"business_id": business_id},
        {"$inc": {key: 1}},
        upsert=True,
    )


# ── 1. SAVE AN INVOICE ──────────────────────────────
def save_invoice(customer_name, customer_email, items, total_amount, business_name, business_id="default", customer_phone=""):
    db = get_db()
    invoices = db["invoice"]
    customers = db["customers"]

    # Atomic invoice numbering — safe under concurrent requests.
    # $setOnInsert seeds the counter from existing invoice count on first use (migration safe).
    counter_id = f"invoice_seq_{business_id}"
    existing_count = invoices.count_documents({"business_id": business_id})
    db["counters"].update_one(
        {"_id": counter_id},
        {"$setOnInsert": {"seq": existing_count}},
        upsert=True
    )
    counter = db["counters"].find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        return_document=ReturnDocument.AFTER
    )
    invoice_number = f"INV-{str(counter['seq']).zfill(3)}"

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
        "date": _today(),
        "item": item,
        "quantity": quantity,
        "sale_amount": sale_amount,
        "cost_amount": cost_amount,
        "profit": profit,
        "recorded_by": "Prosper Assistant"
    })
    logger.info("Sale recorded — %d %s | Revenue: NGN %s | Profit: NGN %s", quantity, item, f"{sale_amount:,}", f"{profit:,}")
    return profit


# ── 5. UPDATE / DELETE SALE ────────────────────────
def update_sale(sale_id, business_id, item=None, quantity=None, sale_amount=None, cost_amount=None, date=None):
    """Update a sale record by its MongoDB _id string."""
    from bson import ObjectId
    db = get_db()
    updates = {}
    if item is not None: updates["item"] = item
    if quantity is not None: updates["quantity"] = quantity
    if sale_amount is not None: updates["sale_amount"] = sale_amount
    if cost_amount is not None: updates["cost_amount"] = cost_amount
    if date is not None: updates["date"] = date
    if sale_amount is not None or cost_amount is not None:
        sale = db["sales"].find_one({"_id": ObjectId(sale_id), "business_id": business_id})
        if sale:
            sa = updates.get("sale_amount", sale["sale_amount"])
            ca = updates.get("cost_amount", sale["cost_amount"])
            updates["profit"] = sa - ca
    result = db["sales"].update_one(
        {"_id": ObjectId(sale_id), "business_id": business_id},
        {"$set": updates}
    )
    return "Sale updated successfully." if result.modified_count else "Sale not found or no changes made."


def delete_sale(sale_id, business_id):
    """Delete a sale record by its MongoDB _id string."""
    from bson import ObjectId
    db = get_db()
    result = db["sales"].delete_one({"_id": ObjectId(sale_id), "business_id": business_id})
    return "Sale deleted successfully." if result.deleted_count else "Sale not found."


# ── 5b. RECORD PARTIAL PAYMENT ON AN INVOICE ───────────────
def record_partial_payment(invoice_number: str, amount_paid: float, business_id: str) -> str:
    """
    Record a partial or full payment against an existing unpaid invoice.
    - If amount_paid >= invoice total: marks invoice as fully paid.
    - If amount_paid < invoice total: reduces the invoice amount to the remaining balance.
    Updates the customer's outstanding_balance and total_paid accordingly.
    """
    db = get_db()
    invoice_number = invoice_number.upper().strip()
    invoice = db["invoice"].find_one({"invoice_number": invoice_number, "business_id": business_id})
    if not invoice:
        return f"Invoice {invoice_number} not found."
    if invoice.get("status") == "paid":
        return f"Invoice {invoice_number} is already fully paid."

    total = invoice["total_amount"]
    remaining = total - amount_paid
    customer_name = invoice.get("customer_name", "")
    customer_phone = invoice.get("customer_phone", "")
    customer_email = invoice.get("customer_email", "")
    lookup = _customer_lookup(customer_name, customer_email, customer_phone, business_id)

    if amount_paid >= total:
        # Full payment
        db["invoice"].update_one(
            {"invoice_number": invoice_number, "business_id": business_id},
            {"$set": {"status": "paid", "date_paid": datetime.now().strftime("%Y-%m-%d")}}
        )
        db["customers"].update_one(
            {**lookup, "business_id": business_id},
            {"$inc": {"total_paid": total, "outstanding_balance": -total}}
        )
        return f"Invoice {invoice_number} fully paid! NGN {total:,} received from {customer_name}."
    else:
        # Partial payment — reduce invoice to remaining balance
        db["invoice"].update_one(
            {"invoice_number": invoice_number, "business_id": business_id},
            {"$set": {
                "total_amount": remaining,
                "items": [{"description": invoice["items"][0]["description"] if invoice.get("items") else "Balance", "amount": remaining}],
                "amount_paid_so_far": invoice.get("amount_paid_so_far", 0) + amount_paid
            }}
        )
        db["customers"].update_one(
            {**lookup, "business_id": business_id},
            {"$inc": {"total_paid": amount_paid, "outstanding_balance": -amount_paid}}
        )
        return (
            f"Partial payment of NGN {amount_paid:,} recorded for {customer_name}.\n"
            f"Invoice {invoice_number} updated — new balance: NGN {remaining:,}."
        )


# ── 6. UPDATE CUSTOMER PHONE ────────────────────────
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
    # Escape everything user-supplied in the HTML — these emails go out from
    # our domain, so unescaped HTML here is a phishing vector. The plain-text
    # subject stays unescaped.
    safe_customer = _esc(str(customer_name))
    safe_business = _esc(str(business_name))
    safe_biz_email = _esc(str(business_email))
    items_html = "".join(
        f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{_esc(str(item['description']))}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #eee;text-align:right'>NGN {item['amount']:,}</td></tr>"
        for item in items
    )
    contact_line = f"<p>To contact us, reply to this email or reach us at <a href='mailto:{safe_biz_email}'>{safe_biz_email}</a>.</p>" if business_email else ""
    html = f"""<html><body style='font-family:Arial,sans-serif;color:#1a1a2e;max-width:600px;margin:auto'>
<div style='background:#0d3d26;padding:24px;border-radius:8px 8px 0 0'>
  <h1 style='color:white;margin:0;font-size:22px'>Invoice from {safe_business}</h1>
</div>
<div style='padding:24px;border:1px solid #e8eaed;border-top:none;border-radius:0 0 8px 8px'>
  <p>Dear <strong>{safe_customer}</strong>,</p>
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
    customer_name = _esc(str(customer_name))
    invoice_number = _esc(str(invoice_number))
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
    safe_customer = _esc(str(customer_name))
    safe_business = _esc(str(business_name))
    html = f"""<html><body style='font-family:Arial,sans-serif;color:#1a1a2e;max-width:600px;margin:auto'>
<div style='background:#0d3d26;padding:24px;border-radius:8px 8px 0 0'>
  <h1 style='color:white;margin:0;font-size:22px'>Welcome to {safe_business}!</h1>
</div>
<div style='padding:24px;border:1px solid #e8eaed;border-top:none;border-radius:0 0 8px 8px'>
  <p>Dear <strong>{safe_customer}</strong>,</p>
  <p>You have been added as a customer of <strong>{safe_business}</strong>.</p>
  <p>You will receive invoices and updates from us going forward.</p>
  <p>Thank you for your business!</p>
  <p style='color:#666;font-size:13px'>Powered by <strong>Prosper Assistant</strong> · prosperassistant.online</p>
</div>
</body></html>"""
    return _send_via_resend(customer_email, f"Welcome! You're now a customer of {business_name}", html)
