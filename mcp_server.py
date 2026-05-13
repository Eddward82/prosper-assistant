from fastmcp import FastMCP
from agent_tools import save_invoice, get_unpaid_invoices, log_sale, send_invoice_email
from dotenv import load_dotenv
import os

load_dotenv()

# ── ARIZE PHOENIX TRACING ────────────────────────────
from phoenix.otel import register
from openinference.instrumentation.mcp import MCPInstrumentor

# Configure Phoenix
os.environ["PHOENIX_API_KEY"] = os.getenv("PHOENIX_API_KEY", "")
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = "https://app.phoenix.arize.com/s/ogunlusiolubunmi"

tracer_provider = register(
    project_name="prosper-assistant",
    auto_instrument=True
)

MCPInstrumentor().instrument(tracer_provider=tracer_provider)

# Set environment variables for FastMCP
os.environ["FASTMCP_HOST"] = "0.0.0.0"
os.environ["FASTMCP_PORT"] = str(os.environ.get("PORT", 8080))

mcp = FastMCP(name="Prosper Assistant")

# ... rest of your tool definitions ...

# Set environment variables for FastMCP
os.environ["FASTMCP_HOST"] = "0.0.0.0"
os.environ["FASTMCP_PORT"] = str(os.environ.get("PORT", 8080))

mcp = FastMCP(name="Prosper Assistant")

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
    """Record a sale and calculate profit"""
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
    """Get summary of ALL sales ever recorded (not just today). Shows total revenue, profit, and sales count across all time."""
    from pymongo import MongoClient
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    all_sales = list(db["sales"].find({}, {"_id": 0}))
    if not all_sales:
        return "No sales recorded yet."
    total_revenue = sum(s["sale_amount"] for s in all_sales)
    total_profit = sum(s["profit"] for s in all_sales)
    return f"All-time summary: {len(all_sales)} total sales, NGN {total_revenue:,} total revenue, NGN {total_profit:,} total profit"


@mcp.tool()
def get_sales_by_date(date: str) -> str:
    """Get sales for a specific date. Date must be in YYYY-MM-DD format. Use for 'yesterday's report' or any past date queries."""
    from pymongo import MongoClient
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    sales = list(db["sales"].find({"date": date}, {"_id": 0}))
    if not sales:
        return f"No sales recorded for {date}"
    total_revenue = sum(s["sale_amount"] for s in sales)
    total_profit = sum(s["profit"] for s in sales)
    return f"Sales for {date}: {len(sales)} transactions, NGN {total_revenue:,} revenue, NGN {total_profit:,} profit"
@mcp.tool()
def get_lifetime_business_report() -> str:
    """Get the complete lifetime business report covering all sales, invoices, customers, and finances since the business started. Use this when user asks for overall business performance, all-time numbers, or comprehensive report."""
    from pymongo import MongoClient
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    
    # All sales
    all_sales = list(db["sales"].find({}, {"_id": 0}))
    total_revenue = sum(s["sale_amount"] for s in all_sales)
    total_profit = sum(s["profit"] for s in all_sales)
    
    # All invoices
    all_invoices = list(db["invoice"].find({}, {"_id": 0}))
    paid_invoices = [inv for inv in all_invoices if inv.get("status") == "paid"]
    unpaid_invoices = [inv for inv in all_invoices if inv.get("status") == "unpaid"]
    total_invoiced = sum(inv["total_amount"] for inv in all_invoices)
    total_paid = sum(inv["total_amount"] for inv in paid_invoices)
    total_outstanding = sum(inv["total_amount"] for inv in unpaid_invoices)
    
    # All customers
    total_customers = db["customers"].count_documents({})
    
    # First and last activity
    first_sale_date = min([s["date"] for s in all_sales]) if all_sales else "N/A"
    last_sale_date = max([s["date"] for s in all_sales]) if all_sales else "N/A"
    
    report = f"""LIFETIME BUSINESS REPORT
    
SALES:
- Total Sales: {len(all_sales)}
- Total Revenue: NGN {total_revenue:,}
- Total Profit: NGN {total_profit:,}
- First Sale: {first_sale_date}
- Last Sale: {last_sale_date}

INVOICES:
- Total Invoices Issued: {len(all_invoices)}
- Total Amount Invoiced: NGN {total_invoiced:,}
- Total Paid: NGN {total_paid:,}
- Total Outstanding: NGN {total_outstanding:,}
- Paid: {len(paid_invoices)} | Unpaid: {len(unpaid_invoices)}

CUSTOMERS:
- Total Customers: {total_customers}"""
    
    return report
@mcp.tool()
def mark_invoice_as_paid(invoice_number: str) -> str:
    """Mark a specific invoice as paid. Use when user confirms a customer has paid their invoice. Invoice number format example: INV-001"""
    from pymongo import MongoClient
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    
    invoice = db["invoice"].find_one({"invoice_number": invoice_number})
    if not invoice:
        return f"Invoice {invoice_number} not found in records"
    
    if invoice.get("status") == "paid":
        return f"Invoice {invoice_number} is already marked as paid"
    
    from datetime import datetime
    db["invoice"].update_one(
        {"invoice_number": invoice_number},
        {"$set": {"status": "paid", "date_paid": datetime.now().strftime("%Y-%m-%d")}}
    )
    
    db["customers"].update_one(
        {"customer_email": invoice["customer_email"]},
        {
            "$inc": {
                "total_paid": invoice["total_amount"],
                "outstanding_balance": -invoice["total_amount"]
            }
        }
    )
    
    return f"Invoice {invoice_number} for {invoice['customer_name']} (NGN {invoice['total_amount']:,}) has been marked as PAID!"

if __name__ == "__main__":
    import asyncio
    port = int(os.environ.get("PORT", 8080))
    asyncio.run(mcp.run_http_async(host="0.0.0.0", port=port))