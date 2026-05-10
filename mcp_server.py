from mcp.server.fastmcp import FastMCP
from agent_tools import save_invoice, get_unpaid_invoices, log_sale, mark_invoice_paid, send_invoice_email
from dotenv import load_dotenv
import os

load_dotenv()

mcp = FastMCP("Prosper Assistant")

@mcp.tool()
def check_unpaid_invoices() -> str:
    """Get all unpaid invoices and who owes money"""
    unpaid = get_unpaid_invoices()
    if not unpaid:
        return "No unpaid invoices. Everyone has paid!"
    result = f"Found {len(unpaid)} unpaid invoices:\n"
    for inv in unpaid:
        result += f"• {inv['invoice_number']} | {inv['customer_name']} | ₦{inv['total_amount']:,} | Created: {inv['date_created']}\n"
    return result

@mcp.tool()
def record_sale(item: str, quantity: int, sale_amount: float, cost_amount: float) -> str:
    """Record a sale and calculate profit"""
    profit = log_sale(item, quantity, sale_amount, cost_amount)
    return f"Sale recorded! {quantity} {item} | Revenue: ₦{sale_amount:,} | Profit: ₦{profit:,}"

@mcp.tool()
def create_invoice(customer_name: str, customer_email: str, description: str, amount: float, business_name: str = "Prosper Stores") -> str:
    """Create and send an invoice to a customer"""
    items = [{"description": description, "amount": amount}]
    invoice_number = save_invoice(customer_name, customer_email, items, amount, business_name)
    send_invoice_email(customer_name, customer_email, invoice_number, items, amount, business_name)
    return f"Invoice {invoice_number} created and sent to {customer_email} for ₦{amount:,}"

@mcp.tool()
def get_daily_report() -> str:
    """Get today's business summary including sales and outstanding debt"""
    from pymongo import MongoClient
    from datetime import datetime
    import requests as req
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    today = datetime.now().strftime("%Y-%m-%d")
    todays_sales = list(db["sales"].find({"date": today}, {"_id": 0}))
    unpaid = list(db["invoice"].find({"status": "unpaid"}, {"_id": 0}))
    total_revenue = sum(s["sale_amount"] for s in todays_sales)
    total_profit = sum(s["profit"] for s in todays_sales)
    total_outstanding = sum(inv["total_amount"] for inv in unpaid)
    try:
        rate = req.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5).json()["rates"]["NGN"]
    except:
        rate = "unavailable"
    return f"""Today's Report ({today}):
- Sales: {len(todays_sales)} transactions
- Revenue: ₦{total_revenue:,}
- Profit: ₦{total_profit:,}
- Unpaid Invoices: {len(unpaid)}
- Outstanding Debt: ₦{total_outstanding:,}
- USD/NGN Rate: {rate}"""

if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8080)