from fastmcp import FastMCP
from agent_tools import save_invoice, get_unpaid_invoices, log_sale, send_invoice_email
from dotenv import load_dotenv
import os

load_dotenv()

# ── ARIZE PHOENIX TRACING ────────────────────────────
from phoenix.otel import register
from openinference.instrumentation.mcp import MCPInstrumentor

os.environ["PHOENIX_API_KEY"] = os.getenv("PHOENIX_API_KEY", "")
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = "https://app.phoenix.arize.com/s/ogunlusiolubunmi"

tracer_provider = register(
    project_name="prosper-assistant",
    auto_instrument=True
)
MCPInstrumentor().instrument(tracer_provider=tracer_provider)

# ── FASTMCP CONFIG ───────────────────────────────────
os.environ["FASTMCP_HOST"] = "0.0.0.0"
os.environ["FASTMCP_PORT"] = str(os.environ.get("PORT", 8080))

mcp = FastMCP(name="Prosper Assistant")

# ── MCP TOOLS ────────────────────────────────────────
@mcp.tool()
def check_unpaid_invoices() -> str:
    """Get all unpaid invoices and customers who owe money"""
    unpaid = get_unpaid_invoices()
    if not unpaid:
        return "No unpaid invoices. Everyone has paid!"
    result = f"Found {len(unpaid)} unpaid invoices:\n"
    for inv in unpaid:
        result += f"- {inv['invoice_number']} | {inv['customer_name']} | NGN {inv['total_amount']:,}\n"
    return result

@mcp.tool()
def record_sale(item: str, quantity: int, sale_amount: float, cost_amount: float) -> str:
    """Record a cash sale and calculate profit"""
    profit = log_sale(item, quantity, sale_amount, cost_amount)
    return f"Sale recorded! {quantity} {item} | Revenue: NGN {sale_amount:,} | Profit: NGN {profit:,}"

@mcp.tool()
def create_invoice(customer_name: str, customer_email: str, description: str, amount: float) -> str:
    """Create and send an invoice to a customer via email"""
    items = [{"description": description, "amount": amount}]
    invoice_number = save_invoice(customer_name, customer_email, items, amount, "Prosper Stores")
    send_invoice_email(customer_name, customer_email, invoice_number, items, amount, "Prosper Stores")
    return f"Invoice {invoice_number} created and emailed to {customer_email} for NGN {amount:,}"

@mcp.tool()
def get_business_report() -> str:
    """Get today's business summary"""
    from pymongo import MongoClient
    from datetime import datetime
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    today = datetime.now().strftime("%Y-%m-%d")
    sales = list(db["sales"].find({"date": today}, {"_id": 0}))
    unpaid = list(db["invoice"].find({"status": "unpaid"}, {"_id": 0}))
    revenue = sum(s["sale_amount"] for s in sales)
    profit = sum(s["profit"] for s in sales)
    outstanding = sum(inv["total_amount"] for inv in unpaid)
    return f"Today: {len(sales)} sales, NGN {revenue:,} revenue, NGN {profit:,} profit. {len(unpaid)} unpaid invoices = NGN {outstanding:,} outstanding"

@mcp.tool()
def get_all_sales_summary() -> str:
    """Get summary of ALL sales ever recorded"""
    from pymongo import MongoClient
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    all_sales = list(db["sales"].find({}, {"_id": 0}))
    if not all_sales:
        return "No sales recorded yet."
    total_revenue = sum(s["sale_amount"] for s in all_sales)
    total_profit = sum(s["profit"] for s in all_sales)
    return f"All-time: {len(all_sales)} sales, NGN {total_revenue:,} revenue, NGN {total_profit:,} profit"

@mcp.tool()
def get_sales_by_date(date: str) -> str:
    """Get sales for a specific date in YYYY-MM-DD format"""
    from pymongo import MongoClient
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    sales = list(db["sales"].find({"date": date}, {"_id": 0}))
    if not sales:
        return f"No sales for {date}"
    total_revenue = sum(s["sale_amount"] for s in sales)
    total_profit = sum(s["profit"] for s in sales)
    return f"Sales for {date}: {len(sales)} transactions, NGN {total_revenue:,} revenue, NGN {total_profit:,} profit"

@mcp.tool()
def get_lifetime_business_report() -> str:
    """Get complete lifetime business report"""
    from pymongo import MongoClient
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    all_sales = list(db["sales"].find({}, {"_id": 0}))
    total_revenue = sum(s["sale_amount"] for s in all_sales)
    total_profit = sum(s["profit"] for s in all_sales)
    all_invoices = list(db["invoice"].find({}, {"_id": 0}))
    paid_invoices = [inv for inv in all_invoices if inv.get("status") == "paid"]
    unpaid_invoices = [inv for inv in all_invoices if inv.get("status") == "unpaid"]
    total_invoiced = sum(inv["total_amount"] for inv in all_invoices)
    total_paid = sum(inv["total_amount"] for inv in paid_invoices)
    total_outstanding = sum(inv["total_amount"] for inv in unpaid_invoices)
    total_customers = db["customers"].count_documents({})
    return f"""LIFETIME REPORT:
SALES: {len(all_sales)} transactions | Revenue NGN {total_revenue:,} | Profit NGN {total_profit:,}
INVOICES: {len(all_invoices)} issued | Paid NGN {total_paid:,} | Outstanding NGN {total_outstanding:,}
CUSTOMERS: {total_customers} total"""

@mcp.tool()
def mark_invoice_as_paid(invoice_number: str) -> str:
    """Mark a specific invoice as paid"""
    from pymongo import MongoClient
    from datetime import datetime
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    invoice = db["invoice"].find_one({"invoice_number": invoice_number})
    if not invoice:
        return f"Invoice {invoice_number} not found"
    if invoice.get("status") == "paid":
        return f"Invoice {invoice_number} is already paid"
    db["invoice"].update_one(
        {"invoice_number": invoice_number},
        {"$set": {"status": "paid", "date_paid": datetime.now().strftime("%Y-%m-%d")}}
    )
    db["customers"].update_one(
        {"customer_email": invoice["customer_email"]},
        {"$inc": {"total_paid": invoice["total_amount"], "outstanding_balance": -invoice["total_amount"]}}
    )
    return f"Invoice {invoice_number} for {invoice['customer_name']} (NGN {invoice['total_amount']:,}) marked PAID!"

# ── ADD DASHBOARD API ROUTES ─────────────────────────
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.middleware.cors import CORSMiddleware

async def dashboard_data(request: Request):
    from pymongo import MongoClient
    from datetime import datetime
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    today = datetime.now().strftime("%Y-%m-%d")
    todays_sales = list(db["sales"].find({"date": today}, {"_id": 0}))
    all_sales = list(db["sales"].find({}, {"_id": 0}))
    all_invoices = list(db["invoice"].find({}, {"_id": 0}))
    unpaid = [inv for inv in all_invoices if inv.get("status") == "unpaid"]
    customers = db["customers"].count_documents({})
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
            "amount": inv["total_amount"]
        } for inv in unpaid[:5]]
    })

async def chat_endpoint(request: Request):
    import json
    body = await request.body()
    data = json.loads(body)
    user_message = data.get("message", "")
    msg_lower = user_message.lower()
    if "owe" in msg_lower or "unpaid" in msg_lower or "who owes" in msg_lower:
        result = check_unpaid_invoices()
    elif ("today" in msg_lower and "report" in msg_lower) or "today's report" in msg_lower or "daily report" in msg_lower:
        result = get_business_report()
    elif "lifetime" in msg_lower or "all time" in msg_lower or "overall" in msg_lower or "entire business" in msg_lower:
        result = get_lifetime_business_report()
    elif "all sales" in msg_lower or "show all" in msg_lower or "all my sales" in msg_lower or "total sales" in msg_lower:
        result = get_all_sales_summary()
    else:
        try:
            import google.generativeai as genai
            genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"You are Prosper Assistant, helping Nigerian SME owners. Use warm Nigerian English when appropriate. User said: {user_message}. Respond helpfully."
            response = model.generate_content(prompt)
            result = response.text
        except Exception as e:
            result = "Hello oga! I'm Prosper Assistant. Try asking: 'Who owes me money?' or 'Show my lifetime report'"
    return JSONResponse({"response": result})

app = mcp.http_app()
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