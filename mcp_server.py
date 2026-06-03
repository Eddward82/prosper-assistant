from fastmcp import FastMCP
from agent_tools import save_invoice, get_unpaid_invoices, log_sale, send_invoice_email, find_customer, update_customer_phone, get_db
from dotenv import load_dotenv
import os
import re
import logging
import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool

logger = logging.getLogger(__name__)

load_dotenv()

# ── ARIZE PHOENIX TRACING ────────────────────────────────────
from phoenix.otel import register
from openinference.instrumentation.mcp import MCPInstrumentor

os.environ["PHOENIX_API_KEY"] = os.getenv("PHOENIX_API_KEY", "")
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "https://app.phoenix.arize.com")

tracer_provider = register(
    project_name="prosper-assistant",
    auto_instrument=True
)
MCPInstrumentor().instrument(tracer_provider=tracer_provider)

# ── FASTMCP CONFIG ───────────────────────────────────────────
os.environ["FASTMCP_HOST"] = "0.0.0.0"
os.environ["FASTMCP_PORT"] = str(os.environ.get("PORT", 8080))

mcp = FastMCP(name="Prosper Assistant")


def _extract_phone(text: str) -> str | None:
    """Extract Nigerian phone number from text. Supports +234XXXXXXXXXX and 0XXXXXXXXXX."""
    match = re.search(r'\+?234\d{10}|\b0[789]\d{9}\b', text)
    if not match:
        return None
    phone = match.group(0)
    # Normalise to +234 format
    if phone.startswith("0"):
        phone = "+234" + phone[1:]
    return phone


# ── MCP TOOLS ────────────────────────────────────────────────
@mcp.tool()
def check_unpaid_invoices(business_id: str = "default") -> str:
    """Get all unpaid invoices and customers who owe money for a specific business"""
    unpaid = get_unpaid_invoices(business_id)
    if not unpaid:
        return "No unpaid invoices. Everyone has paid!"
    result = f"Found {len(unpaid)} unpaid invoices:\n"
    for inv in unpaid:
        result += f"- {inv['invoice_number']} | {inv['customer_name']} | NGN {inv['total_amount']:,}\n"
    return result


@mcp.tool()
def record_sale(item: str, quantity: int, sale_amount: float, cost_amount: float, business_id: str = "default") -> str:
    """Record a cash sale and calculate profit for a specific business"""
    profit = log_sale(item, quantity, sale_amount, cost_amount, business_id)
    return f"Sale recorded! {quantity} {item} | Revenue: NGN {sale_amount:,} | Profit: NGN {profit:,}"


@mcp.tool()
def create_invoice(customer_name: str, customer_email: str, description: str, amount: float, business_name: str = "", business_id: str = "default", customer_phone: str = "") -> str:
    """Create and send an invoice to a customer via email for a specific business"""
    db = get_db()
    biz = db["businesses"].find_one({"business_id": business_id}) or {}
    business_name = biz.get("business_name") or business_name or "Prosper Stores"
    business_email = biz.get("business_email", "")
    items = [{"description": description, "amount": amount}]
    invoice_number = save_invoice(customer_name, customer_email, items, amount, business_name, business_id, customer_phone)
    send_invoice_email(customer_name, customer_email, invoice_number, items, amount, business_name, business_email)
    return f"Invoice {invoice_number} created and emailed to {customer_email} for NGN {amount:,}"


@mcp.tool()
def get_business_report(business_id: str = "default") -> str:
    """Get today's business summary for a specific business"""
    from datetime import datetime
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    sales = list(db["sales"].find({"date": today, "business_id": business_id}, {"_id": 0}))
    unpaid = list(db["invoice"].find({"status": "unpaid", "business_id": business_id}, {"_id": 0}))
    revenue = sum(s["sale_amount"] for s in sales)
    profit = sum(s["profit"] for s in sales)
    outstanding = sum(inv["total_amount"] for inv in unpaid)
    return f"Today: {len(sales)} sales, NGN {revenue:,} revenue, NGN {profit:,} profit. {len(unpaid)} unpaid invoices = NGN {outstanding:,} outstanding"


@mcp.tool()
def get_all_sales_summary(business_id: str = "default") -> str:
    """Get summary of ALL sales ever recorded for a specific business"""
    db = get_db()
    all_sales = list(db["sales"].find({"business_id": business_id}, {"_id": 0}, sort=[("date", -1)]))
    if not all_sales:
        return "No sales recorded yet."
    total_revenue = sum(s["sale_amount"] for s in all_sales)
    total_profit = sum(s["profit"] for s in all_sales)
    lines = f"SALES-TABLE:{len(all_sales)} sales | Revenue: NGN {total_revenue:,.0f} | Profit: NGN {total_profit:,.0f}\n"
    for s in all_sales:
        date = s.get("date", "—")
        item = s.get("item", "—")
        qty = s.get("quantity", 1)
        revenue = s.get("sale_amount", 0)
        profit = s.get("profit", 0)
        lines += f"ROW:{date}|{qty} {item}|NGN {revenue:,.0f}|NGN {profit:,.0f}\n"
    return lines


@mcp.tool()
def get_sales_by_date(date: str, business_id: str = "default") -> str:
    """Get sales for a specific date in YYYY-MM-DD format for a specific business"""
    db = get_db()
    sales = list(db["sales"].find({"date": date, "business_id": business_id}, {"_id": 0}))
    if not sales:
        return f"No sales for {date}"
    total_revenue = sum(s["sale_amount"] for s in sales)
    total_profit = sum(s["profit"] for s in sales)
    return f"Sales for {date}: {len(sales)} transactions, NGN {total_revenue:,} revenue, NGN {total_profit:,} profit"


@mcp.tool()
def get_lifetime_business_report(business_id: str = "default") -> str:
    """Get complete lifetime business report for a specific business"""
    db = get_db()
    all_sales = list(db["sales"].find({"business_id": business_id}, {"_id": 0}))
    total_revenue = sum(s["sale_amount"] for s in all_sales)
    total_profit = sum(s["profit"] for s in all_sales)
    all_invoices = list(db["invoice"].find({"business_id": business_id}, {"_id": 0}))
    paid_invoices = [inv for inv in all_invoices if inv.get("status") == "paid"]
    unpaid_invoices = [inv for inv in all_invoices if inv.get("status") == "unpaid"]
    total_invoiced = sum(inv["total_amount"] for inv in all_invoices)
    total_paid = sum(inv["total_amount"] for inv in paid_invoices)
    total_outstanding = sum(inv["total_amount"] for inv in unpaid_invoices)
    total_customers = db["customers"].count_documents({"business_id": business_id})
    return f"""LIFETIME REPORT:
SALES: {len(all_sales)} transactions | Revenue NGN {total_revenue:,} | Profit NGN {total_profit:,}
INVOICES: {len(all_invoices)} issued | Paid NGN {total_paid:,} | Outstanding NGN {total_outstanding:,}
CUSTOMERS: {total_customers} total"""


@mcp.tool()
def mark_invoice_as_paid(invoice_number: str, business_id: str = "default") -> str:
    """Mark a specific invoice as paid for a specific business"""
    from datetime import datetime
    db = get_db()
    invoice_number = invoice_number.upper().strip()
    invoice = db["invoice"].find_one({"invoice_number": invoice_number, "business_id": business_id})
    if not invoice:
        return f"Invoice {invoice_number} not found"
    if invoice.get("status") == "paid":
        return f"Invoice {invoice_number} is already paid"
    db["invoice"].update_one(
        {"invoice_number": invoice_number, "business_id": business_id},
        {"$set": {"status": "paid", "date_paid": datetime.now().strftime("%Y-%m-%d")}}
    )
    # Update customer balance using the best available key
    customer_phone = invoice.get("customer_phone", "")
    customer_email = invoice.get("customer_email", "")
    customer_name = invoice.get("customer_name", "")
    from agent_tools import _customer_lookup
    lookup = _customer_lookup(customer_name, customer_email, customer_phone, business_id)
    db["customers"].update_one(
        {**lookup, "business_id": business_id},
        {"$inc": {"total_paid": invoice["total_amount"], "outstanding_balance": -invoice["total_amount"]}}
    )
    return f"Invoice {invoice_number} for {customer_name} (NGN {invoice['total_amount']:,}) marked PAID!"


@mcp.tool()
def get_customers(business_id: str = "default") -> str:
    """Get all customers with their phone numbers, emails, and balances for a specific business"""
    db = get_db()
    customers = list(db["customers"].find({"business_id": business_id}, {"_id": 0}))
    if not customers:
        return "No customers found."
    result = f"Found {len(customers)} customers:\n"
    for c in customers:
        name = c.get("customer_name", "Unknown")
        phone = c.get("customer_phone", "no phone")
        email = c.get("customer_email", "no email")
        balance = c.get("outstanding_balance", 0)
        result += f"- {name} | Phone: {phone} | Email: {email} | Owes: NGN {balance:,}\n"
    return result


@mcp.tool()
def set_customer_phone(customer_name: str, customer_phone: str, business_id: str = "default") -> str:
    """Update or add a phone number for an existing customer"""
    phone = _extract_phone(customer_phone) or customer_phone
    count = update_customer_phone(customer_name, phone, business_id)
    if count == 0:
        return f"No customer named '{customer_name}' found under business '{business_id}'. Create an invoice for them first."
    return f"Phone number {phone} saved for {customer_name}."


# ── DASHBOARD API ROUTES ─────────────────────────────────────
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.middleware.cors import CORSMiddleware
import asyncio
import firebase_admin
from firebase_admin import auth as fb_auth

if not firebase_admin._apps:
    firebase_admin.initialize_app(options={"projectId": "agentquest"})


async def _verify_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        decoded = await asyncio.to_thread(fb_auth.verify_id_token, header[7:])
        return decoded["uid"]
    except Exception:
        return None


def _get_business_info(business_id: str) -> tuple:
    """Returns (business_name, business_email) from DB."""
    biz = get_db()["businesses"].find_one({"business_id": business_id}) or {}
    return biz.get("business_name", ""), biz.get("business_email", "")



async def dashboard_data(request: Request):
    uid = await _verify_token(request)
    if uid is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    from datetime import datetime
    db = get_db()
    business_id = request.query_params.get("business_id", "default")
    today = request.query_params.get("date") or datetime.now().strftime("%Y-%m-%d")
    todays_sales = list(db["sales"].find({"date": today, "business_id": business_id}, {"_id": 0}))
    all_sales = list(db["sales"].find({"business_id": business_id}, {"_id": 0}))
    all_invoices = list(db["invoice"].find({"business_id": business_id}, {"_id": 0}))
    unpaid = sorted(
        [inv for inv in all_invoices if inv.get("status") == "unpaid"],
        key=lambda x: x.get("date_created", ""),
        reverse=True
    )[:50]
    customers = db["customers"].count_documents({"business_id": business_id})
    return JSONResponse({
        "today_revenue": sum(s["sale_amount"] for s in todays_sales),
        "today_profit": sum(s["profit"] for s in todays_sales),
        "today_sales_count": len(todays_sales),
        "lifetime_revenue": sum(s["sale_amount"] for s in all_sales),
        "lifetime_profit": sum(s["profit"] for s in all_sales),
        "total_sales": len(all_sales),
        "unpaid_count": len(unpaid),
        "outstanding": sum(inv["total_amount"] for inv in unpaid),
        "total_invoices": len(all_invoices),
        "total_customers": customers,
        "unpaid_invoices": [{
            "invoice_number": inv["invoice_number"],
            "customer_name": inv["customer_name"],
            "customer_phone": inv.get("customer_phone", ""),
            "customer_email": inv.get("customer_email", ""),
            "description": inv["items"][0]["description"] if inv.get("items") else "Goods / Services",
            "amount": inv["total_amount"]
        } for inv in unpaid]
    })


async def get_profile_endpoint(request: Request):
    token_uid = await _verify_token(request)
    if token_uid is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    uid = request.query_params.get("uid", "").strip()
    biz_name = request.query_params.get("bizName", "").strip()
    if not uid:
        return JSONResponse({"error": "Missing uid"}, status_code=400)
    db = get_db()
    # Try by Firebase UID first
    biz = db["businesses"].find_one({"business_id": uid}, {"_id": 0})
    # Fallback: match by business name (exact string match) for account recovery
    if not biz and biz_name:
        biz = db["businesses"].find_one(
            {"business_name": biz_name},
            {"_id": 0}
        )
        # Try case-insensitive if exact fails
        if not biz:
            import re
            safe_name = re.escape(biz_name)
            biz = db["businesses"].find_one(
                {"business_name": {"$regex": f"^{safe_name}$", "$options": "i"}},
                {"_id": 0}
            )
    if not biz:
        return JSONResponse({"found": False})
    # If found under old bizId, migrate to Firebase UID going forward
    old_biz_id = biz.get("business_id", "")
    if old_biz_id != uid:
        db["businesses"].update_one({"business_id": old_biz_id}, {"$set": {"business_id": uid}})
    return JSONResponse({
        "found": True,
        "bizName": biz.get("business_name", ""),
        "ownerName": biz.get("owner_name", ""),
        "bizEmail": biz.get("business_email", ""),
        "bizId": uid
    })


async def register_business_endpoint(request: Request):
    uid = await _verify_token(request)
    if uid is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    import json
    from datetime import datetime
    try:
        body = await request.body()
        data = json.loads(body)
    except (json.JSONDecodeError, Exception):
        return JSONResponse({"error": "Invalid request"}, status_code=400)
    business_name = data.get("bizName", "").strip()
    owner_name = data.get("ownerName", "").strip()
    business_email = data.get("bizEmail", "").strip()

    if not business_name or not owner_name or not business_email:
        return JSONResponse({"error": "Missing required fields"}, status_code=400)

    uid = data.get("uid", "").strip()
    business_id = uid if uid else business_name.lower().replace(" ", "-")
    db = get_db()

    existing = db["businesses"].find_one({"business_id": business_id})
    if not existing:
        db["businesses"].insert_one({
            "business_id": business_id,
            "business_name": business_name,
            "owner_name": owner_name,
            "business_email": business_email,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        return JSONResponse({"status": "registered", "business_id": business_id})
    else:
        db["businesses"].update_one(
            {"business_id": business_id},
            {"$set": {"owner_name": owner_name, "business_email": business_email}}
        )
        return JSONResponse({"status": "updated", "business_id": business_id})


async def chat_endpoint(request: Request):
    uid = await _verify_token(request)
    if uid is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    import json
    try:
        body = await request.body()
        data = json.loads(body)
    except (json.JSONDecodeError, Exception):
        return JSONResponse({"error": "Invalid request"}, status_code=400)
    user_message = data.get("message", "")
    history = data.get("history", [])  # [{role, text}, ...]
    profile = data.get("profile", {})
    business_id = profile.get("bizName", "default").lower().replace(" ", "-")
    business_name = profile.get("bizName", "Prosper Stores")
    db = get_db()

    # ── Handle pending email action (user replied with phone number) ──
    pending_email = db["pending_email"].find_one({"business_id": business_id})
    if pending_email:
        phone = _extract_phone(user_message)
        if phone:
            customer_name = pending_email["customer_name"]
            customer_email = pending_email["customer_email"]
            db["pending_email"].delete_one({"business_id": business_id})
            cust_doc, ambiguous, matches = find_customer(customer_name, business_id, phone)
            if ambiguous:
                options = "\n".join(
                    f"  {i+1}. {m['customer_name']} | Phone: {m.get('customer_phone','no phone')}"
                    for i, m in enumerate(matches)
                )
                result = f"I found {len(matches)} customers named {customer_name}:\n{options}\nReply with 1 or 2."
            elif not cust_doc:
                result = f"No customer named {customer_name} with that phone found."
            else:
                db["customers"].update_one({"_id": cust_doc["_id"]}, {"$set": {"customer_email": customer_email}})
                db["invoice"].update_many(
                    {"customer_name": customer_name, "business_id": business_id, "customer_email": ""},
                    {"$set": {"customer_email": customer_email}}
                )
                inv = db["invoice"].find_one({"customer_name": customer_name, "business_id": business_id}, sort=[("date_created", -1)])
                if inv:
                    _biz_name, _biz_email = _get_business_info(business_id)
                    sent = send_invoice_email(customer_name, customer_email, inv["invoice_number"], inv.get("items", []), inv["total_amount"], _biz_name or business_name, _biz_email)
                    result = f"Sharp! Email saved for {customer_name} and invoice {inv['invoice_number']} sent to {customer_email}!" if sent else f"Email saved for {customer_name} but couldn't send the invoice. Try again."
                else:
                    result = f"Email {customer_email} saved for {customer_name}. No invoice found to send."
            return JSONResponse({"response": result})

    # ── Handle pending disambiguation (numbered selection) ──────
    pending_disambig = db["pending_disambig"].find_one({"business_id": business_id})
    if pending_disambig and user_message.strip() in ["1", "2", "3", "4"]:
        idx = int(user_message.strip()) - 1
        matches = pending_disambig.get("matches", [])
        if idx < len(matches):
            chosen = matches[idx]
            action = pending_disambig.get("action", "invoice")
            db["pending_disambig"].delete_one({"business_id": business_id})
            customer_name = chosen.get("customer_name")
            customer_phone = chosen.get("customer_phone", "")
            customer_email = chosen.get("customer_email", "")
            description = pending_disambig.get("description", "goods/services")
            amount = pending_disambig.get("amount", 0)
            if customer_email:
                result = create_invoice(customer_name, customer_email, description, amount, business_name, business_id, customer_phone)
            else:
                invoice_number = save_invoice(customer_name, "", [{"description": description, "amount": amount}], amount, business_name, business_id, customer_phone)
                label = "Credit sale recorded! Invoice" if action == "credit" else "Invoice"
                result = f"{label} {invoice_number} for {customer_name} - NGN {amount:,}. No email on file."
        else:
            db["pending_disambig"].delete_one({"business_id": business_id})
            result = "Invalid choice. Please start over."
        return JSONResponse({"response": result})

    # ── Handle pending cost-price reply ─────────────────────────
    pending = db["pending_sales"].find_one({"business_id": business_id})
    if pending:
        cost_numbers = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', user_message.replace(",", ""))
        if cost_numbers and len(user_message.strip()) < 30:
            cost_amount = float(cost_numbers[0])
            if "k" in user_message.lower() and cost_amount < 1000:
                cost_amount *= 1000
            result = record_sale(pending["item"], pending["quantity"], pending["sale_amount"], cost_amount, business_id)
            db["pending_sales"].delete_one({"business_id": business_id})
            return JSONResponse({"response": result})

    # ── Direct handler: "send/email to NAME at EMAIL" ────────────
    # Handle before Gemini to avoid conversational loops
    direct_email_match = re.search(
        r'(?:send|email|resend|forward)\s+(?:invoice\s+)?(?:to\s+)?([A-Za-z]+)\s+(?:at|@)\s+([\w\.-]+@[\w\.-]+)',
        user_message, re.IGNORECASE
    )
    if not direct_email_match:
        direct_email_match = re.search(
            r'([A-Za-z]+)[\'s]*\s+email\s+(?:is\s+)?([\w\.-]+@[\w\.-]+)',
            user_message, re.IGNORECASE
        )
    if direct_email_match:
        customer_name = direct_email_match.group(1).capitalize()
        customer_email = direct_email_match.group(2)
        phone_in_msg = _extract_phone(user_message)
        cust_doc, ambiguous, matches = find_customer(customer_name, business_id, phone_in_msg or "")
        if ambiguous:
            options = "\n".join(
                f"  {i+1}. {m['customer_name']} | Phone: {m.get('customer_phone','no phone')}"
                for i, m in enumerate(matches)
            )
            db["pending_email"].update_one(
                {"business_id": business_id},
                {"$set": {"business_id": business_id, "customer_name": customer_name, "customer_email": customer_email}},
                upsert=True
            )
            return JSONResponse({"response": f"I found {len(matches)} customers named {customer_name}:\n{options}\nWhich one? Reply with 1 or 2."})
        elif not cust_doc and not phone_in_msg:
            db["pending_email"].update_one(
                {"business_id": business_id},
                {"$set": {"business_id": business_id, "customer_name": customer_name, "customer_email": customer_email}},
                upsert=True
            )
            return JSONResponse({"response": f"Abeg, what is {customer_name}'s phone number so I can identify them?"})
        elif not cust_doc:
            return JSONResponse({"response": f"No customer named {customer_name} found. Create an invoice for them first."})
        else:
            db["pending_email"].delete_many({"business_id": business_id})
            db["customers"].update_one({"_id": cust_doc["_id"]}, {"$set": {"customer_email": customer_email}})
            db["invoice"].update_many(
                {"customer_name": customer_name, "business_id": business_id, "customer_email": ""},
                {"$set": {"customer_email": customer_email}}
            )
            inv = db["invoice"].find_one({"customer_name": customer_name, "business_id": business_id}, sort=[("date_created", -1)])
            if inv:
                _biz_name, _biz_email = _get_business_info(business_id)
                sent = send_invoice_email(customer_name, customer_email, inv["invoice_number"], inv.get("items", []), inv["total_amount"], _biz_name or business_name, _biz_email)
                result = f"Sharp! Email saved and invoice {inv['invoice_number']} sent to {customer_email}!" if sent else f"Email saved for {customer_name} but couldn't send invoice."
            else:
                result = f"Updated! {customer_name}'s email is now {customer_email}."
            return JSONResponse({"response": result})

    # ── Gemini function-calling intent router ────────────────────
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

    tools = Tool(function_declarations=[
        FunctionDeclaration(
            name="create_invoice",
            description="Create an invoice or credit sale for a customer. Use when a customer is buying on credit, owes money, or when the user wants to send an invoice.",
            parameters={"type": "object", "properties": {
                "customer_name": {"type": "string", "description": "Full name of the customer"},
                "customer_phone": {"type": "string", "description": "Nigerian phone number e.g. 08012345678"},
                "customer_email": {"type": "string", "description": "Customer email address if provided, else empty string"},
                "description": {"type": "string", "description": "What was sold or the invoice description"},
                "amount": {"type": "number", "description": "Total invoice amount in Naira"},
            }, "required": ["customer_name", "customer_phone", "description", "amount"]},
        ),
        FunctionDeclaration(
            name="record_sale",
            description="Record a completed cash sale. Use when items were sold and payment was received in full.",
            parameters={"type": "object", "properties": {
                "item": {"type": "string", "description": "Name of the item sold"},
                "quantity": {"type": "integer", "description": "Number of units sold"},
                "sale_amount": {"type": "number", "description": "Total revenue from the sale"},
                "cost_amount": {"type": "number", "description": "Total cost price. Use 0 if not mentioned — system will ask."},
            }, "required": ["item", "quantity", "sale_amount", "cost_amount"]},
        ),
        FunctionDeclaration(
            name="split_payment",
            description="Record a transaction where the customer paid part in cash and owes the rest on credit.",
            parameters={"type": "object", "properties": {
                "customer_name": {"type": "string"},
                "customer_phone": {"type": "string"},
                "customer_email": {"type": "string"},
                "description": {"type": "string", "description": "What was purchased"},
                "total_amount": {"type": "number"},
                "cash_paid": {"type": "number", "description": "Amount paid in cash now"},
                "balance_owed": {"type": "number", "description": "Amount still owed"},
            }, "required": ["customer_name", "customer_phone", "description", "total_amount", "cash_paid", "balance_owed"]},
        ),
        FunctionDeclaration(
            name="check_unpaid_invoices",
            description="Show all unpaid invoices and customers who owe money.",
            parameters={"type": "object", "properties": {
                "business_id": {"type": "string", "description": "The business ID"}
            }},
        ),
        FunctionDeclaration(
            name="get_all_customers",
            description="Show all customers and their details including contact info and balances. Use when user asks to see customers, show customers, list customers, my customers, who are my customers.",
            parameters={"type": "object", "properties": {}},
        ),
        FunctionDeclaration(
            name="get_business_report",
            description="Get today's sales report, revenue and profit summary.",
            parameters={"type": "object", "properties": {}},
        ),
        FunctionDeclaration(
            name="get_lifetime_business_report",
            description="Get all-time lifetime business report including all sales and invoices.",
            parameters={"type": "object", "properties": {}},
        ),
        FunctionDeclaration(
            name="get_all_sales_summary",
            description="Get summary of all sales ever recorded.",
            parameters={"type": "object", "properties": {}},
        ),
        FunctionDeclaration(
            name="mark_invoice_paid",
            description="Mark an invoice as paid. ONLY use when user explicitly says 'mark as paid', 'mark paid', 'payment received for INV-xxx'. Do NOT use when user just types an invoice number alone.",
            parameters={"type": "object", "properties": {
                "invoice_number": {"type": "string", "description": "Invoice number like INV-001"},
            }, "required": ["invoice_number"]},
        ),
        FunctionDeclaration(
            name="update_customer_email",
            description="Update or add an email address for an existing customer. Use when user says '[name] email is ...' or 'send email to [name] at ...' or 'update [name] email'. Also use when user wants to send an invoice email to a customer who already has an invoice — save the email then resend.",
            parameters={"type": "object", "properties": {
                "customer_name": {"type": "string"},
                "customer_phone": {"type": "string", "description": "Phone number to identify customer if name is ambiguous, else empty string"},
                "customer_email": {"type": "string"},
                "resend_invoice_number": {"type": "string", "description": "If user wants to send/resend an invoice after updating the email, include the invoice number here. Else empty string."},
            }, "required": ["customer_name", "customer_email"]},
        ),
        FunctionDeclaration(
            name="update_customer_phone",
            description="Update or add a phone number for an existing customer.",
            parameters={"type": "object", "properties": {
                "customer_name": {"type": "string"},
                "customer_phone": {"type": "string"},
            }, "required": ["customer_name", "customer_phone"]},
        ),
        FunctionDeclaration(
            name="resend_invoice",
            description="Resend an invoice email to a customer. Use when user says 'resend', 'send again', 'I didn't receive it' and provides an invoice number.",
            parameters={"type": "object", "properties": {
                "invoice_number": {"type": "string"},
            }, "required": ["invoice_number"]},
        ),
    ])

    system_prompt = (
        f"You are Prosper Assistant, a business tool for Nigerian SMEs. "
        f"Business: {business_name} (ID: {business_id}). "
        f"Today's date: {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}. "
        f"CRITICAL RULES — follow exactly:\n"
        f"1. ALWAYS call a function. Never reply with only text if a function fits.\n"
        f"2. If the user gives a phone number after being asked for one, call update_customer_email with that phone number.\n"
        f"3. If the user gives an invoice number after being asked, call resend_invoice with it.\n"
        f"4. 'send invoice to NAME at EMAIL' → call update_customer_email with resend_invoice_number set to the most recent invoice for that customer (use empty string if unknown).\n"
        f"5. Only ask ONE clarifying question maximum, then on the very next user reply — call the function.\n"
        f"6. Nigerian phone numbers: 08012345678 → +2348012345678.\n"
        f"7. Amounts like '20k' mean 20000.\n"
        f"8. If cost price not mentioned for a sale, use 0.\n"
        f"9. Respond in friendly Nigerian English only when NOT calling a function.\n"
        f"10. CRITICAL: When a function returns data, show it EXACTLY as returned — do NOT reword, summarize or reformat it. "
        f"Just add a brief friendly intro line before the data, then show the raw function result unchanged."
    )

    try:
        model = genai.GenerativeModel("gemini-2.0-flash", tools=[tools], system_instruction=system_prompt)
        # Collapse recent history into the current message so Gemini has full context
        # but still produces a single function call rather than continuing the conversation
        if history:
            context_lines = []
            for h in history[-6:]:  # last 3 turns
                role = "User" if h.get("role") == "user" else "Assistant"
                context_lines.append(f"{role}: {h.get('text','')}")
            context_block = "\n".join(context_lines)
            full_message = f"Previous conversation:\n{context_block}\n\nUser now says: {user_message}\n\nBased on the full conversation above, call the appropriate function with all available details."
        else:
            full_message = user_message
        response = model.generate_content(full_message)

        # Find the function call part if present
        fn = None
        args = {}
        plain_text = None
        for part in response.candidates[0].content.parts:
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", None):
                fn = fc.name
                args = dict(fc.args)
                break
            txt = getattr(part, "text", None)
            if txt:
                plain_text = txt

        if not fn:
            return JSONResponse({"response": plain_text or "No wahala! How can I help you today?"})

        # ── Execute the chosen function ──────────────────────────
        if fn == "get_all_customers":
            db = get_db()
            customers = list(db["customers"].find({"business_id": business_id}, {"_id": 0}))
            if not customers:
                return JSONResponse({"response": "No customers found yet. Create an invoice or record a sale to add customers."})
            result = f"Found {len(customers)} customers:\n"
            for c in customers:
                name = c.get("customer_name", "Unknown")
                phone = c.get("customer_phone", "no phone")
                email = c.get("customer_email", "no email")
                balance = c.get("outstanding_balance", 0)
                paid = c.get("total_paid", 0)
                result += f"- **{name}** | Phone: {phone} | Email: {email} | Owes: NGN {balance:,} | Paid: NGN {paid:,}\n"
            return JSONResponse({"response": result})

        elif fn == "check_unpaid_invoices":
            return JSONResponse({"response": check_unpaid_invoices(business_id)})

        elif fn == "get_business_report":
            return JSONResponse({"response": get_business_report(business_id)})

        elif fn == "get_lifetime_business_report":
            return JSONResponse({"response": get_lifetime_business_report(business_id)})

        elif fn == "get_all_sales_summary":
            return JSONResponse({"response": get_all_sales_summary(business_id)})

        elif fn == "mark_invoice_paid":
            result = mark_invoice_as_paid(args["invoice_number"].upper(), business_id)

        elif fn == "update_customer_phone":
            phone = _extract_phone(args["customer_phone"]) or args["customer_phone"]
            result = set_customer_phone(args["customer_name"], phone, business_id)

        elif fn == "update_customer_email":
            customer_name = args["customer_name"]
            customer_email = args["customer_email"]
            phone_in_msg = _extract_phone(args.get("customer_phone", "")) or args.get("customer_phone", "")
            resend_inv = args.get("resend_invoice_number", "").upper().strip()
            cust_doc, ambiguous, matches = find_customer(customer_name, business_id, phone_in_msg)
            if ambiguous:
                options = "\n".join(
                    f"  {i+1}. {m['customer_name']} | Phone: {m.get('customer_phone','no phone')}"
                    for i, m in enumerate(matches)
                )
                result = f"I found {len(matches)} customers named {customer_name}:\n{options}\nInclude their phone number to specify."
            elif not cust_doc and not phone_in_msg:
                # No phone given and no unique customer found — save context and ask for phone
                db["pending_email"].update_one(
                    {"business_id": business_id},
                    {"$set": {"business_id": business_id, "customer_name": customer_name, "customer_email": customer_email}},
                    upsert=True
                )
                result = f"Abeg, what is {customer_name}'s phone number so I can identify them?"
            elif not cust_doc:
                result = f"No customer named {customer_name} found. Create an invoice for them first."
            else:
                db["pending_email"].delete_many({"business_id": business_id})
                db["customers"].update_one({"_id": cust_doc["_id"]}, {"$set": {"customer_email": customer_email}})
                db["invoice"].update_many(
                    {"customer_name": customer_name, "business_id": business_id, "customer_email": ""},
                    {"$set": {"customer_email": customer_email}}
                )
                # Always try to send the most recent invoice after saving email
                inv_to_send = None
                if resend_inv:
                    inv_to_send = db["invoice"].find_one({"invoice_number": resend_inv, "business_id": business_id})
                if not inv_to_send:
                    inv_to_send = db["invoice"].find_one({"customer_name": customer_name, "business_id": business_id}, sort=[("date_created", -1)])
                if inv_to_send:
                    _biz_name, _biz_email = _get_business_info(business_id)
                    sent = send_invoice_email(customer_name, customer_email, inv_to_send["invoice_number"], inv_to_send.get("items", []), inv_to_send["total_amount"], _biz_name or business_name, _biz_email)
                    result = f"Sharp! Email saved for {customer_name} and invoice {inv_to_send['invoice_number']} sent to {customer_email}!" if sent else f"Email saved for {customer_name} but couldn't send invoice. Try 'resend {inv_to_send['invoice_number']}'."
                else:
                    result = f"Updated! {customer_name}'s email is now {customer_email}."

        elif fn == "resend_invoice":
            inv_number = args["invoice_number"].upper()
            inv = db["invoice"].find_one({"invoice_number": inv_number, "business_id": business_id})
            if not inv:
                result = f"Invoice {inv_number} not found."
            elif not inv.get("customer_email"):
                result = f"No email on file for {inv.get('customer_name')}. Add their email first."
            else:
                _biz_name, _biz_email = _get_business_info(business_id)
                sent = send_invoice_email(inv["customer_name"], inv["customer_email"], inv_number, inv.get("items", []), inv["total_amount"], _biz_name or business_name, _biz_email)
                result = f"Invoice {inv_number} resent to {inv['customer_email']}!" if sent else "Failed to send email. Please try again."

        elif fn == "record_sale":
            item = args["item"]
            quantity = int(args.get("quantity", 1))
            sale_amount = float(args["sale_amount"])
            cost_amount = float(args.get("cost_amount", 0))
            if cost_amount == 0:
                db["pending_sales"].update_one(
                    {"business_id": business_id},
                    {"$set": {"business_id": business_id, "item": item, "quantity": quantity, "sale_amount": sale_amount}},
                    upsert=True
                )
                result = f"Got it! {quantity} {item} sold for NGN {sale_amount:,.0f}. What was your cost price so I can calculate profit?"
            else:
                result = record_sale(item, quantity, sale_amount, cost_amount, business_id)

        elif fn == "create_invoice":
            customer_name = args["customer_name"]
            customer_phone = _extract_phone(args.get("customer_phone", "")) or args.get("customer_phone", "")
            customer_email = args.get("customer_email", "")
            description = args["description"]
            amount = float(args["amount"])

            cust_doc, ambiguous, matches = find_customer(customer_name, business_id, customer_phone, customer_email)
            if ambiguous:
                options = "\n".join(
                    f"  {i+1}. {m['customer_name']} | Phone: {m.get('customer_phone','no phone')} | Email: {m.get('customer_email','no email')}"
                    for i, m in enumerate(matches)
                )
                db["pending_disambig"].update_one(
                    {"business_id": business_id},
                    {"$set": {"business_id": business_id, "action": "invoice", "description": description, "amount": amount, "matches": matches}},
                    upsert=True
                )
                result = f"I found {len(matches)} customers named {customer_name}. Which one?\n{options}\nReply with 1 or 2."
            else:
                if cust_doc:
                    customer_phone = customer_phone or cust_doc.get("customer_phone", "")
                    customer_email = customer_email or cust_doc.get("customer_email", "")
                if not customer_phone:
                    result = f"Please include {customer_name}'s phone number. Example: '{customer_name} 08012345678'"
                elif customer_email:
                    result = create_invoice(customer_name, customer_email, description, amount, business_name, business_id, customer_phone)
                else:
                    invoice_number = save_invoice(customer_name, "", [{"description": description, "amount": amount}], amount, business_name, business_id, customer_phone)
                    result = f"Invoice {invoice_number} created for {customer_name} - NGN {amount:,.0f}. No email on file, so I didn't send it."

        elif fn == "split_payment":
            customer_name = args["customer_name"]
            customer_phone = _extract_phone(args.get("customer_phone", "")) or args.get("customer_phone", "")
            customer_email = args.get("customer_email", "")
            description = args["description"]
            total_amount = float(args["total_amount"])
            cash_paid = float(args["cash_paid"])
            balance_owed = float(args["balance_owed"])

            cust_doc, ambiguous, matches = find_customer(customer_name, business_id, customer_phone, customer_email)
            if ambiguous:
                options = "\n".join(
                    f"  {i+1}. {m['customer_name']} | Phone: {m.get('customer_phone','no phone')}"
                    for i, m in enumerate(matches)
                )
                db["pending_disambig"].update_one(
                    {"business_id": business_id},
                    {"$set": {"business_id": business_id, "action": "invoice", "description": description, "amount": balance_owed, "matches": matches}},
                    upsert=True
                )
                result = f"I found {len(matches)} customers named {customer_name}. Which one?\n{options}\nReply with 1 or 2."
            else:
                if cust_doc:
                    customer_phone = customer_phone or cust_doc.get("customer_phone", "")
                    customer_email = customer_email or cust_doc.get("customer_email", "")
                if cash_paid > 0:
                    log_sale(description, 1, cash_paid, 0, business_id)  # cost unknown for split payment cash portion
                if balance_owed > 0:
                    if not customer_phone:
                        result = f"Please include {customer_name}'s phone number for the balance invoice."
                    else:
                        invoice_number = save_invoice(customer_name, customer_email or "", [{"description": f"{description} (balance)", "amount": balance_owed}], balance_owed, business_name, business_id, customer_phone)
                        result = f"Split payment recorded for {customer_name}!\n• Cash received: NGN {cash_paid:,.0f}\n• Balance invoice {invoice_number}: NGN {balance_owed:,.0f}\n• Total transaction: NGN {total_amount:,.0f}"
                else:
                    result = f"Full payment of NGN {cash_paid:,.0f} recorded for {customer_name}."

        else:
            result = "I'm not sure how to handle that. Try: 'Send invoice to Chidi for 50000' or 'Who owes me money?'"

    except Exception as e:
        logger.error("Gemini error: %s", e)
        return JSONResponse({"response": "Something went wrong. Please try again."})

    return JSONResponse({"response": result})


async def customers_endpoint(request: Request):
    uid = await _verify_token(request)
    if uid is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    db = get_db()
    business_id = request.query_params.get("business_id", "default")
    customers = list(db["customers"].find({"business_id": business_id}, {"_id": 0}))
    return JSONResponse({"customers": [{
        "customer_name": c.get("customer_name", ""),
        "customer_phone": c.get("customer_phone", ""),
        "customer_email": c.get("customer_email", ""),
        "outstanding_balance": c.get("outstanding_balance", 0),
        "total_invoiced": c.get("total_invoiced", 0),
        "total_paid": c.get("total_paid", 0),
    } for c in customers]})


async def sales_endpoint(request: Request):
    uid = await _verify_token(request)
    if uid is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    db = get_db()
    business_id = request.query_params.get("business_id", "default")
    date_from = request.query_params.get("from", "")
    date_to = request.query_params.get("to", "")
    query = {"business_id": business_id}
    if date_from and date_to:
        query["date"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        query["date"] = {"$gte": date_from}
    sales = list(db["sales"].find(query, {"_id": 0}).sort("date", -1))
    return JSONResponse({"sales": [{
        "date": s.get("date", ""),
        "item": s.get("item", ""),
        "quantity": s.get("quantity", 0),
        "sale_amount": s.get("sale_amount", 0),
        "cost_amount": s.get("cost_amount", 0),
        "profit": s.get("profit", 0),
    } for s in sales]})


async def agent_chat_endpoint(request: Request):
    """Run user message through ADK agent with per-business session memory."""
    uid = await _verify_token(request)
    if uid is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    import json
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types as genai_types
    from agent import root_agent

    try:
        body = await request.body()
        data = json.loads(body)
    except (json.JSONDecodeError, Exception):
        return JSONResponse({"error": "Invalid request"}, status_code=400)
    user_message = data.get("message", "")
    profile = data.get("profile", {})
    business_name = profile.get("bizName", "Prosper Stores")
    # Use bizId from profile (Firebase UID) if available, else fall back to name-based ID
    business_id = profile.get("bizId") or data.get("session_id") or profile.get("bizName", "default").lower().replace(" ", "-")
    session_id = data.get("session_id") or business_id
    # Use client date if provided (avoids server timezone issues)
    client_date = data.get("date")
    if client_date:
        import agent_tools
        agent_tools.set_client_date(client_date)

    try:
        # Re-use or create session for this business
        if not hasattr(agent_chat_endpoint, "_sessions"):
            agent_chat_endpoint._sessions = InMemorySessionService()
            agent_chat_endpoint._runners = {}

        session_service = agent_chat_endpoint._sessions

        # Get or create runner for this app
        if "runner" not in agent_chat_endpoint._runners:
            agent_chat_endpoint._runners["runner"] = Runner(
                agent=root_agent,
                app_name="prosper-assistant",
                session_service=session_service,
            )
        runner = agent_chat_endpoint._runners["runner"]

        # Get or create session for this business
        session = await session_service.get_session(
            app_name="prosper-assistant",
            user_id=business_id,
            session_id=session_id,
        )
        if session is None:
            session = await session_service.create_session(
                app_name="prosper-assistant",
                user_id=business_id,
                session_id=session_id,
                state={"business_id": business_id, "business_name": business_name},
            )

        # Inject business context so agent always passes the right business_id to tools
        contextualized_message = (
            f"[Business: {business_name} | business_id: {business_id}]\n{user_message}"
        )

        # Run the agent
        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=contextualized_message)]
        )
        response_text = ""
        async for event in runner.run_async(
            user_id=business_id,
            session_id=session_id,
            new_message=content,
        ):
            if event.is_final_response():
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        response_text += part.text

        return JSONResponse({"response": response_text or "No wahala! How can I help you?"})

    except Exception as e:
        logger.error("ADK agent error: %s", e)
        return JSONResponse({"response": "Something went wrong. Please try again."}, status_code=500)


async def delete_account_endpoint(request: Request):
    token_uid = await _verify_token(request)
    if token_uid is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    import json
    try:
        body = await request.body()
        data = json.loads(body)
    except (json.JSONDecodeError, Exception):
        return JSONResponse({"error": "Invalid request"}, status_code=400)
    uid = data.get("uid", "").strip()
    if not uid:
        return JSONResponse({"error": "Missing uid"}, status_code=400)
    db = get_db()
    db["businesses"].delete_many({"business_id": uid})
    db["invoice"].delete_many({"business_id": uid})
    db["sales"].delete_many({"business_id": uid})
    db["customers"].delete_many({"business_id": uid})
    db["pending_sales"].delete_many({"business_id": uid})
    db["pending_disambig"].delete_many({"business_id": uid})
    return JSONResponse({"success": True})


app = mcp.http_app()
app.routes.append(Route("/api/profile", get_profile_endpoint, methods=["GET"]))
app.routes.append(Route("/api/delete-account", delete_account_endpoint, methods=["POST", "OPTIONS"]))
app.routes.append(Route("/api/register", register_business_endpoint, methods=["POST", "OPTIONS"]))
app.routes.append(Route("/api/dashboard", dashboard_data, methods=["GET"]))
app.routes.append(Route("/api/chat", chat_endpoint, methods=["POST", "OPTIONS"]))
app.routes.append(Route("/api/agent-chat", agent_chat_endpoint, methods=["POST", "OPTIONS"]))
app.routes.append(Route("/api/customers", customers_endpoint, methods=["GET"]))
app.routes.append(Route("/api/sales", sales_endpoint, methods=["GET"]))
ALLOWED_ORIGINS = [
    "https://prosperassistant.online",
    "https://www.prosperassistant.online",
    "https://prosper-assistant.web.app",
    "https://agentquest.web.app",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
