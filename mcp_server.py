from fastmcp import FastMCP
from agent_tools import save_invoice, get_unpaid_invoices, log_sale, send_invoice_email, find_customer, update_customer_phone, get_db
from dotenv import load_dotenv
import os
import re

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
def create_invoice(customer_name: str, customer_email: str, description: str, amount: float, business_name: str = "Prosper Stores", business_id: str = "default", customer_phone: str = "") -> str:
    """Create and send an invoice to a customer via email for a specific business"""
    items = [{"description": description, "amount": amount}]
    invoice_number = save_invoice(customer_name, customer_email, items, amount, business_name, business_id, customer_phone)
    send_invoice_email(customer_name, customer_email, invoice_number, items, amount, business_name)
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
    all_sales = list(db["sales"].find({"business_id": business_id}, {"_id": 0}))
    if not all_sales:
        return "No sales recorded yet."
    total_revenue = sum(s["sale_amount"] for s in all_sales)
    total_profit = sum(s["profit"] for s in all_sales)
    return f"All-time: {len(all_sales)} sales, NGN {total_revenue:,} revenue, NGN {total_profit:,} profit"


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
def set_customer_phone(customer_name: str, customer_phone: str, business_id: str = "default") -> str:
    """Update or add a phone number for an existing customer"""
    phone = _extract_phone(customer_phone) or customer_phone
    count = update_customer_phone(customer_name, phone, business_id)
    if count == 0:
        return f"No customer named '{customer_name}' found. Create an invoice for them first."
    return f"Phone number {phone} saved for {customer_name}."


# ── DASHBOARD API ROUTES ─────────────────────────────────────
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.middleware.cors import CORSMiddleware


async def dashboard_data(request: Request):
    from datetime import datetime
    db = get_db()
    business_id = request.query_params.get("business_id", "default")
    today = datetime.now().strftime("%Y-%m-%d")
    todays_sales = list(db["sales"].find({"date": today, "business_id": business_id}, {"_id": 0}))
    all_sales = list(db["sales"].find({"business_id": business_id}, {"_id": 0}))
    all_invoices = list(db["invoice"].find({"business_id": business_id}, {"_id": 0}))
    unpaid = [inv for inv in all_invoices if inv.get("status") == "unpaid"]
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
            "amount": inv["total_amount"]
        } for inv in unpaid[:5]]
    })


async def register_business_endpoint(request: Request):
    import json
    from datetime import datetime
    body = await request.body()
    data = json.loads(body)
    business_name = data.get("bizName", "").strip()
    owner_name = data.get("ownerName", "").strip()
    business_email = data.get("bizEmail", "").strip()

    if not business_name or not owner_name or not business_email:
        return JSONResponse({"error": "Missing required fields"}, status_code=400)

    business_id = business_name.lower().replace(" ", "-")
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
    import json
    from datetime import datetime
    body = await request.body()
    data = json.loads(body)
    user_message = data.get("message", "")
    profile = data.get("profile", {})
    business_id = profile.get("bizName", "default").lower().replace(" ", "-")
    business_name = profile.get("bizName", "Prosper Stores")
    msg_lower = user_message.lower()
    db = get_db()

    # ── Check if user is replying with cost for a pending sale ──
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

    # ── Intent routing ───────────────────────────────────────────
    if "owe" in msg_lower or "unpaid" in msg_lower:
        result = check_unpaid_invoices(business_id)

    elif "today" in msg_lower and "report" in msg_lower:
        result = get_business_report(business_id)

    elif "lifetime" in msg_lower or "all time" in msg_lower or "overall" in msg_lower:
        result = get_lifetime_business_report(business_id)

    elif "all sales" in msg_lower or "all my sales" in msg_lower:
        result = get_all_sales_summary(business_id)

    elif "email" in msg_lower and ("update" in msg_lower or "is" in msg_lower or "add" in msg_lower or "set" in msg_lower):
        email_match = re.search(r'[\w\.-]+@[\w\.-]+', user_message)
        if not email_match:
            result = "Please include the email address. Example: 'Bayo's email is bayo@gmail.com'"
        else:
            customer_email = email_match.group(0)
            name_match = re.search(r"([A-Z][a-zA-Z]+)['s]*\s+email", user_message)
            if not name_match:
                name_match = re.search(r"(?:for|to|of)\s+([A-Z][a-zA-Z]+)", user_message)
            if not name_match:
                result = "Please mention the customer's name. Example: 'Bayo's email is bayo@gmail.com'"
            else:
                customer_name = name_match.group(1)
                existing = db["customers"].find_one({"customer_name": customer_name, "business_id": business_id})
                if not existing:
                    result = f"I don't have {customer_name} in your customer list. Create an invoice for them first."
                else:
                    db["customers"].update_one(
                        {"customer_name": customer_name, "business_id": business_id},
                        {"$set": {"customer_email": customer_email}}
                    )
                    db["invoice"].update_many(
                        {"customer_name": customer_name, "business_id": business_id, "customer_email": ""},
                        {"$set": {"customer_email": customer_email}}
                    )
                    result = f"Updated! {customer_name}'s email is now {customer_email}."

    elif "phone" in msg_lower and ("update" in msg_lower or "is" in msg_lower or "add" in msg_lower or "set" in msg_lower):
        phone = _extract_phone(user_message)
        if not phone:
            result = "Please include the phone number. Example: 'Bayo's phone is 08012345678'"
        else:
            name_match = re.search(r"([A-Z][a-zA-Z]+)['s]*\s+phone", user_message)
            if not name_match:
                name_match = re.search(r"(?:for|to|of)\s+([A-Z][a-zA-Z]+)", user_message)
            if not name_match:
                result = "Please mention the customer's name. Example: 'Bayo's phone is 08012345678'"
            else:
                customer_name = name_match.group(1)
                result = set_customer_phone(customer_name, phone, business_id)

    elif ("credit sale" in msg_lower) or ("on credit" in msg_lower):
        numbers = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', user_message.replace(",", ""))
        numbers = [float(n) for n in numbers]
        amount = numbers[-1] if numbers else 0

        name_match = re.search(r'(?:to|for|,)\s+([A-Z][a-zA-Z]+)\s+(?:took|bought|owes|at|for|worth)', user_message)
        if not name_match:
            name_match = re.search(r'to\s+([A-Z][a-zA-Z]+)', user_message)
        if not name_match:
            name_match = re.search(r'(?:^|\s)([A-Z][a-zA-Z]+)\s+(?:took|bought|owes)', user_message)

        if not name_match:
            result = "I couldn't find the customer's name. Try: 'Credit sale to Chidi for 50000'"
        else:
            customer_name = name_match.group(1)
            phone_in_msg = _extract_phone(user_message)
            email_match = re.search(r'[\w\.-]+@[\w\.-]+', user_message)
            customer_email = email_match.group(0) if email_match else None
            item_match = re.search(r'(?:credit sale of|sold)\s+(.+?)\s+(?:worth|for|to)', user_message, re.IGNORECASE)
            description = item_match.group(1).strip() if item_match else "items"

            cust_doc, ambiguous, matches = find_customer(customer_name, business_id, phone_in_msg or "", customer_email or "")

            if ambiguous:
                options = "\n".join(
                    f"  - {m['customer_name']} | Phone: {m.get('customer_phone', 'no phone')} | Email: {m.get('customer_email', 'no email')}"
                    for m in matches
                )
                result = f"I found {len(matches)} customers named {customer_name}. Which one do you mean?\n{options}\nPlease include their phone number to specify."
            else:
                customer_phone = phone_in_msg
                if cust_doc:
                    customer_phone = customer_phone or cust_doc.get("customer_phone", "")
                    customer_email = customer_email or cust_doc.get("customer_email", "")

                if not customer_phone:
                    result = f"Please include {customer_name}'s phone number. Example: 'Credit sale to {customer_name} 08012345678 for 50000'"
                elif customer_email:
                    result = create_invoice(customer_name, customer_email, description, amount, business_name, business_id, customer_phone)
                else:
                    invoice_number = save_invoice(customer_name, "", [{"description": description, "amount": amount}], amount, business_name, business_id, customer_phone)
                    result = f"Credit sale recorded! Invoice {invoice_number} for {customer_name} - NGN {amount:,}. No email on file so I didn't send it."

    elif "sold" in msg_lower or "i sold" in msg_lower or "sale of" in msg_lower:
        expanded = re.sub(r'(\d+(?:\.\d+)?)k\b', lambda m: str(int(float(m.group(1)) * 1000)), user_message, flags=re.IGNORECASE)
        numbers = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', expanded.replace(",", ""))
        numbers = [float(n) for n in numbers]

        if len(numbers) < 2:
            result = "Please include quantity and amount. Example: 'Sold 10 biscuits for 5000'"
        else:
            quantity = int(numbers[0])
            msg_lower_local = expanded.lower()

            if "total" in msg_lower_local:
                sale_amount = max(numbers[1:])
            elif "each" in msg_lower_local and len(numbers) >= 2:
                sale_amount = quantity * numbers[1]
            else:
                sale_amount = numbers[1]

            item_match = re.search(r'(?:sold|sale of|sell)\s+\d+\s+([a-zA-Z\s]+?)(?:\s+for|\s+at|\s+worth|\s+total)', user_message, re.IGNORECASE)
            item = item_match.group(1).strip() if item_match else "item"

            if "cost" in msg_lower_local:
                cost_numbers = [n for n in numbers if n != quantity and n != sale_amount]
                cost_amount = cost_numbers[-1] if cost_numbers else sale_amount * 0.7
                result = record_sale(item, quantity, sale_amount, cost_amount, business_id)
            else:
                db["pending_sales"].update_one(
                    {"business_id": business_id},
                    {"$set": {"business_id": business_id, "item": item, "quantity": quantity, "sale_amount": sale_amount}},
                    upsert=True
                )
                result = f"Got it! {quantity} {item} sold for NGN {sale_amount:,}. What was your cost price so I can calculate profit?"

    elif "mark" in msg_lower and "paid" in msg_lower:
        inv_match = re.search(r'INV-\d+', user_message, re.IGNORECASE)
        if not inv_match:
            result = "Please include the invoice number. Example: 'Mark INV-009 as paid'"
        else:
            result = mark_invoice_as_paid(inv_match.group(0).upper(), business_id)

    elif "invoice" in msg_lower:
        numbers = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', user_message.replace(",", ""))
        numbers = [float(n) for n in numbers]
        amount = numbers[-1] if numbers else 0

        if amount == 0:
            result = "Please include an amount. Try: 'Send invoice to Chidi at chidi@gmail.com for 50000'"
        else:
            name_match = re.search(r'(?:to|for|,)\s+([A-Z][a-zA-Z]+)\s+(?:took|bought|owes|at|for|worth)', user_message)
            if not name_match:
                name_match = re.search(r'to\s+([A-Z][a-zA-Z]+)', user_message)
            if not name_match:
                name_match = re.search(r'(?:^|\s)([A-Z][a-zA-Z]+)\s+(?:took|bought|owes)', user_message)

            if not name_match:
                result = "I couldn't find the customer's name. Try: 'Send invoice to Chidi for 50000'"
            else:
                customer_name = name_match.group(1)
                phone_in_msg = _extract_phone(user_message)
                email_match = re.search(r'[\w\.-]+@[\w\.-]+', user_message)
                customer_email = email_match.group(0) if email_match else None
                item_match = re.search(r'for\s+(.+?)(?:\s+worth|\s+at|\s+for|$)', user_message, re.IGNORECASE)
                description = item_match.group(1).strip() if item_match else "goods/services"

                cust_doc, ambiguous, matches = find_customer(customer_name, business_id, phone_in_msg or "", customer_email or "")

                if ambiguous:
                    options = "\n".join(
                        f"  - {m['customer_name']} | Phone: {m.get('customer_phone', 'no phone')} | Email: {m.get('customer_email', 'no email')}"
                        for m in matches
                    )
                    result = f"I found {len(matches)} customers named {customer_name}. Which one do you mean?\n{options}\nPlease include their phone number to specify."
                else:
                    customer_phone = phone_in_msg
                    if cust_doc:
                        customer_phone = customer_phone or cust_doc.get("customer_phone", "")
                        customer_email = customer_email or cust_doc.get("customer_email", "")

                    if not customer_phone:
                        result = f"Please include {customer_name}'s phone number. Example: 'Send invoice to {customer_name} 08012345678 for 50000'"
                    elif customer_email:
                        result = create_invoice(customer_name, customer_email, description, amount, business_name, business_id, customer_phone)
                    else:
                        invoice_number = save_invoice(customer_name, "", [{"description": description, "amount": amount}], amount, business_name, business_id, customer_phone)
                        result = f"Invoice {invoice_number} created for {customer_name} - NGN {amount:,}. No email on file, so I didn't send it."

    else:
        try:
            import google.generativeai as genai
            genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"You are Prosper Assistant for Nigerian SMEs. Use Nigerian English. User said: {user_message}. Respond helpfully and suggest: Who owes me money? Today report. Lifetime report."
            response = model.generate_content(prompt)
            result = response.text
        except Exception:
            result = "Hello oga! Try: 'Who owes me money?' or 'Show my lifetime report'"

    return JSONResponse({"response": result})


app = mcp.http_app()
app.routes.append(Route("/api/register", register_business_endpoint, methods=["POST", "OPTIONS"]))
app.routes.append(Route("/api/dashboard", dashboard_data, methods=["GET"]))
app.routes.append(Route("/api/chat", chat_endpoint, methods=["POST", "OPTIONS"]))
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
