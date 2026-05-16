from fastmcp import FastMCP
from agent_tools import save_invoice, get_unpaid_invoices, log_sale, send_invoice_email
from dotenv import load_dotenv
import os

load_dotenv()

# â”€â”€ ARIZE PHOENIX TRACING â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from phoenix.otel import register
from openinference.instrumentation.mcp import MCPInstrumentor

os.environ["PHOENIX_API_KEY"] = os.getenv("PHOENIX_API_KEY", "")
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = "https://app.phoenix.arize.com/s/ogunlusiolubunmi"

tracer_provider = register(
    project_name="prosper-assistant",
    auto_instrument=True
)
MCPInstrumentor().instrument(tracer_provider=tracer_provider)

# â”€â”€ FASTMCP CONFIG â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
os.environ["FASTMCP_HOST"] = "0.0.0.0"
os.environ["FASTMCP_PORT"] = str(os.environ.get("PORT", 8080))

mcp = FastMCP(name="Prosper Assistant")

# â”€â”€ MCP TOOLS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
def create_invoice(customer_name: str, customer_email: str, description: str, amount: float, business_name: str = "Prosper Stores", business_id: str = "default") -> str:
    """Create and send an invoice to a customer via email for a specific business"""
    items = [{"description": description, "amount": amount}]
    invoice_number = save_invoice(customer_name, customer_email, items, amount, business_name, business_id)
    send_invoice_email(customer_name, customer_email, invoice_number, items, amount, business_name)
    return f"Invoice {invoice_number} created and emailed to {customer_email} for NGN {amount:,}"

@mcp.tool()
@mcp.tool()
def get_business_report(business_id: str = "default") -> str:
    """Get today's business summary for a specific business"""
    from pymongo import MongoClient
    from datetime import datetime
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
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
    from pymongo import MongoClient
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    all_sales = list(db["sales"].find({"business_id": business_id}, {"_id": 0}))
    if not all_sales:
        return "No sales recorded yet."
    total_revenue = sum(s["sale_amount"] for s in all_sales)
    total_profit = sum(s["profit"] for s in all_sales)
    return f"All-time: {len(all_sales)} sales, NGN {total_revenue:,} revenue, NGN {total_profit:,} profit"

@mcp.tool()
def get_sales_by_date(date: str, business_id: str = "default") -> str:
    """Get sales for a specific date in YYYY-MM-DD format for a specific business"""
    from pymongo import MongoClient
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    sales = list(db["sales"].find({"date": date, "business_id": business_id}, {"_id": 0}))
    if not sales:
        return f"No sales for {date}"
    total_revenue = sum(s["sale_amount"] for s in sales)
    total_profit = sum(s["profit"] for s in sales)
    return f"Sales for {date}: {len(sales)} transactions, NGN {total_revenue:,} revenue, NGN {total_profit:,} profit"

@mcp.tool()
def get_lifetime_business_report(business_id: str = "default") -> str:
    """Get complete lifetime business report for a specific business"""
    from pymongo import MongoClient
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
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
    from pymongo import MongoClient
    from datetime import datetime
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    invoice = db["invoice"].find_one({"invoice_number": invoice_number, "business_id": business_id})
    if not invoice:
        return f"Invoice {invoice_number} not found"
    if invoice.get("status") == "paid":
        return f"Invoice {invoice_number} is already paid"
    db["invoice"].update_one(
    	{"invoice_number": invoice_number, "business_id": business_id},
        {"$set": {"status": "paid", "date_paid": datetime.now().strftime("%Y-%m-%d")}}
    )
    db["customers"].update_one(
        {"customer_email": invoice["customer_email"]},
        {"$inc": {"total_paid": invoice["total_amount"], "outstanding_balance": -invoice["total_amount"]}}
    )
    return f"Invoice {invoice_number} for {invoice['customer_name']} (NGN {invoice['total_amount']:,}) marked PAID!"

# â”€â”€ ADD DASHBOARD API ROUTES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.middleware.cors import CORSMiddleware

async def dashboard_data(request: Request):
    from pymongo import MongoClient
    from datetime import datetime
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    
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
            "amount": inv["total_amount"]
        } for inv in unpaid[:5]]
    })

async def register_business_endpoint(request: Request):
    import json
    body = await request.body()
    data = json.loads(body)
    business_name = data.get("bizName", "").strip()
    owner_name = data.get("ownerName", "").strip()
    business_email = data.get("bizEmail", "").strip()
    
    if not business_name or not owner_name or not business_email:
        return JSONResponse({"error": "Missing required fields"}, status_code=400)
    
    business_id = business_name.lower().replace(" ", "-")
    
    from pymongo import MongoClient
    from datetime import datetime
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    
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
    body = await request.body()
    data = json.loads(body)
    user_message = data.get("message", "")
    profile = data.get("profile", {})
    business_id = profile.get("bizName", "default").lower().replace(" ", "-")
    business_name = profile.get("bizName", "Prosper Stores")
    msg_lower = user_message.lower()

    if "owe" in msg_lower or "unpaid" in msg_lower:
        result = check_unpaid_invoices(business_id)
    elif "today" in msg_lower and "report" in msg_lower:
        result = get_business_report(business_id)
    elif "lifetime" in msg_lower or "all time" in msg_lower or "overall" in msg_lower:
        result = get_lifetime_business_report(business_id)
    elif "all sales" in msg_lower or "all my sales" in msg_lower:
       result = get_all_sales_summary(business_id)
    
    elif "email" in msg_lower and ("update" in msg_lower or "is" in msg_lower or "add" in msg_lower or "set" in msg_lower):
        try:
            import re
            from pymongo import MongoClient
            client = MongoClient(os.getenv("MONGODB_URI"))
            db = client[os.getenv("DB_NAME")]
            
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
                        result = f"Updated! {customer_name}'s email is now {customer_email}. Any future invoices will be sent there."
        except Exception as e:
            result = "Sorry, couldn't update email. Try: 'Bayo's email is bayo@gmail.com'"
    
    elif ("credit sale" in msg_lower) or ("on credit" in msg_lower):
        try:
            import re
            from pymongo import MongoClient
            client = MongoClient(os.getenv("MONGODB_URI"))
            db = client[os.getenv("DB_NAME")]
            
            numbers = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', user_message.replace(",", ""))
            numbers = [float(n) for n in numbers]
            amount = numbers[-1] if numbers else 0
            name_match = re.search(r'(?:to|for|,)\s+([A-Z][a-zA-Z]+)\s+(?:took|bought|owes|at|for|worth)', user_message)
            if not name_match:
                name_match = re.search(r'to\s+([A-Z][a-zA-Z]+)', user_message)
            if not name_match:
                name_match = re.search(r'(?:^|\s)([A-Z][a-zA-Z]+)\s+(?:took|bought|owes)', user_message)
            customer_name = name_match.group(1) if name_match else "Customer"
            email_match = re.search(r'[\w\.-]+@[\w\.-]+', user_message)
            customer_email = email_match.group(0) if email_match else None
            item_match = re.search(r'(?:credit sale of|sold)\s+(.+?)\s+(?:worth|for|to)', user_message, re.IGNORECASE)
            description = item_match.group(1).strip() if item_match else "items"
            
            # If no email, just save invoice + customer without sending
            if not customer_email:
                from datetime import datetime
                inv_count = db["invoice"].count_documents({"business_id": business_id})
                invoice_number = f"INV-{(inv_count+1):03d}"
                db["invoice"].insert_one({
                    "business_id": business_id,
                    "invoice_number": invoice_number,
                    "customer_name": customer_name,
                    "customer_email": "",
                    "items": [{"description": description, "amount": amount}],
                    "total_amount": amount,
                    "status": "unpaid",
                    "business_name": business_name,
                    "date_created": datetime.now().strftime("%Y-%m-%d")
                })
                # Add as customer
                existing = db["customers"].find_one({"customer_name": customer_name, "business_id": business_id})
                if existing:
                    db["customers"].update_one(
                        {"customer_name": customer_name, "business_id": business_id},
                        {"$inc": {"outstanding_balance": amount, "total_invoiced": amount}}
                    )
                else:
                    db["customers"].insert_one({
                        "business_id": business_id,
                        "customer_name": customer_name,
                        "customer_email": "",
                        "outstanding_balance": amount,
                        "total_invoiced": amount,
                        "total_paid": 0
                    })
                result = f"Credit sale recorded! Invoice {invoice_number} for {customer_name} - NGN {amount:,}. No email on file so I didn't send it."
            else:
                result = create_invoice(customer_name, customer_email, description, amount, business_name, business_id)
        except Exception as e:
            result = "Sorry, couldn't parse credit sale. Try: 'Credit sale to Bayo for 50 bags of cement worth 100000'"
    elif "sold" in msg_lower or "i sold" in msg_lower or "sale of" in msg_lower:
        try:
            import re
            numbers = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', user_message.replace(",", ""))
            numbers = [float(n) for n in numbers]
            if len(numbers) < 2:
                result = "Please include quantity and amount. Example: 'Sold 10 biscuits for 5000, cost 3000'"
            else:
                quantity = int(numbers[0])
                sale_amount = numbers[1]
                cost_amount = numbers[2] if len(numbers) > 2 else sale_amount * 0.7
                item_match = re.search(r'(?:sold|sale of|sell)\s+\d+\s+([a-zA-Z\s]+?)(?:\s+for|\s+at)', user_message, re.IGNORECASE)
                item = item_match.group(1).strip() if item_match else "item"
                result = record_sale(item, quantity, sale_amount, cost_amount, business_id)
        except Exception as e:
            result = "Sorry, couldn't parse. Try: 'I sold 10 biscuits for 5000, cost 3000'"
    elif "mark" in msg_lower and "paid" in msg_lower:
        try:
            import re
            inv_match = re.search(r'INV-\d+', user_message, re.IGNORECASE)
            if not inv_match:
                result = "Please include the invoice number. Example: 'Mark INV-009 as paid'"
            else:
                invoice_number = inv_match.group(0).upper()
                result = mark_invoice_as_paid(invoice_number, business_id)
        except Exception as e:
            result = "Sorry, couldn't mark invoice paid. Try: 'Mark INV-009 as paid'"	
    elif "invoice" in msg_lower:
        try:
            import re
            from pymongo import MongoClient
            client = MongoClient(os.getenv("MONGODB_URI"))
            db = client[os.getenv("DB_NAME")]
            
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
                customer_name = name_match.group(1) if name_match else "Customer"
                email_match = re.search(r'[\w\.-]+@[\w\.-]+', user_message)
                customer_email = email_match.group(0) if email_match else None
                item_match = re.search(r'for\s+(.+?)(?:\s+worth|\s+at|\s+for|$)', user_message, re.IGNORECASE)
                description = item_match.group(1).strip() if item_match else "goods/services"

                if not customer_email:
                    existing_cust = db["customers"].find_one({"customer_name": customer_name, "business_id": business_id})
                    if existing_cust and existing_cust.get("customer_email"):
                        customer_email = existing_cust["customer_email"]
                if customer_email:
                    result = create_invoice(customer_name, customer_email, description, amount, business_name, business_id)
                else:
                    from datetime import datetime
                    inv_count = db["invoice"].count_documents({"business_id": business_id})
                    invoice_number = f"INV-{(inv_count+1):03d}"
                    db["invoice"].insert_one({
                        "business_id": business_id,
                        "invoice_number": invoice_number,
                        "customer_name": customer_name,
                        "customer_email": "",
                        "items": [{"description": description, "amount": amount}],
                        "total_amount": amount,
                        "status": "unpaid",
                        "business_name": business_name,
                        "date_created": datetime.now().strftime("%Y-%m-%d")
                    })
                    existing = db["customers"].find_one({"customer_name": customer_name, "business_id": business_id})
                    if existing:
                        db["customers"].update_one(
                            {"customer_name": customer_name, "business_id": business_id},
                            {"$inc": {"outstanding_balance": amount, "total_invoiced": amount}}
                        )
                    else:
                        db["customers"].insert_one({
                            "business_id": business_id,
                            "customer_name": customer_name,
                            "customer_email": "",
                            "outstanding_balance": amount,
                            "total_invoiced": amount,
                            "total_paid": 0
                        })
                    result = f"Invoice {invoice_number} created for {customer_name} - NGN {amount:,}. No email on file, so I didn't send it."
        except Exception as e:
            result = "Sorry, couldn't create invoice. Try: 'Send invoice to Chidi at chidi@gmail.com for 50000'"
    else:
        try:
            import google.generativeai as genai
            genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"You are Prosper Assistant for Nigerian SMEs. Use Nigerian English. User said: {user_message}. Respond helpfully and suggest: Who owes me money? Today report. Lifetime report."
            response = model.generate_content(prompt)
            result = response.text
        except Exception as e:
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

