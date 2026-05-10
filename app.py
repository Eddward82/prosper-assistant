from flask import Flask, request, jsonify
from agent_tools import save_invoice, get_unpaid_invoices, log_sale, mark_invoice_paid, get_sales_summary, send_invoice_email, send_reminder_email, send_welcome_email
import os

app = Flask(__name__)

# ── 1. SAVE INVOICE ─────────────────────────────────
@app.route('/save_invoice', methods=['POST'])
def api_save_invoice():
    data = request.json
    invoice_number = save_invoice(
        customer_name=data['customer_name'],
        customer_email=data['customer_email'],
        items=data['items'],
        total_amount=data['total_amount'],
        business_name=data.get('business_name', 'Prosper Stores')
    )
    return jsonify({
        "success": True,
        "message": f"Invoice {invoice_number} saved for {data['customer_name']}",
        "invoice_number": invoice_number
    })

# ── 2. GET UNPAID INVOICES ───────────────────────────
@app.route('/unpaid_invoices', methods=['GET'])
def api_unpaid_invoices():
    unpaid = get_unpaid_invoices()
    return jsonify({
        "success": True,
        "count": len(unpaid),
        "invoices": unpaid
    })

# ── 3. LOG A SALE ────────────────────────────────────
@app.route('/log_sale', methods=['POST'])
def api_log_sale():
    data = request.json
    profit = log_sale(
        item=data['item'],
        quantity=data['quantity'],
        sale_amount=data['sale_amount'],
        cost_amount=data['cost_amount']
    )
    return jsonify({
        "success": True,
        "message": f"Sale recorded successfully",
        "profit": profit
    })

# ── 4. MARK INVOICE PAID ─────────────────────────────
@app.route('/mark_paid', methods=['POST'])
def api_mark_paid():
    data = request.json
    result = mark_invoice_paid(data['invoice_number'])
    return jsonify({
        "success": result,
        "message": f"Invoice {data['invoice_number']} marked as paid" if result else "Invoice not found"
    })

# ── 5. SALES SUMMARY ─────────────────────────────────
@app.route('/sales_summary', methods=['GET'])
def api_sales_summary():
    from pymongo import MongoClient
    from dotenv import load_dotenv
    load_dotenv()
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    all_sales = list(db["sales"].find({}, {"_id": 0}))
    total_revenue = sum(s["sale_amount"] for s in all_sales)
    total_profit = sum(s["profit"] for s in all_sales)
    return jsonify({
        "success": True,
        "total_sales": len(all_sales),
        "total_revenue": total_revenue,
        "total_profit": total_profit
    })

# ── 6. HEALTH CHECK ──────────────────────────────────
@app.route('/', methods=['GET'])
def health():
    return jsonify({
        "status": "Prosper Assistant API is running",
        "version": "1.0"
    })
# ── 7. CREATE AND SEND INVOICE (Multi-step) ──────────
@app.route('/create_and_send_invoice', methods=['POST'])
def api_create_and_send_invoice():
    data = request.json
    results = []

    # Step 1 — Save invoice to MongoDB
    invoice_number = save_invoice(
        customer_name=data['customer_name'],
        customer_email=data['customer_email'],
        items=data['items'],
        total_amount=data['total_amount'],
        business_name=data.get('business_name', 'Prosper Stores')
    )
    results.append(f"Step 1 ✅ Invoice {invoice_number} saved to database")

    # Step 2 — Send invoice email
    email_sent = send_invoice_email(
        customer_name=data['customer_name'],
        customer_email=data['customer_email'],
        invoice_number=invoice_number,
        items=data['items'],
        total_amount=data['total_amount'],
        business_name=data.get('business_name', 'Prosper Stores')
    )
    results.append(f"Step 2 ✅ Invoice emailed to {data['customer_email']}")

    # Step 3 — Schedule payment reminder
    from datetime import datetime, timedelta
    reminder_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    from pymongo import MongoClient
    from dotenv import load_dotenv
    load_dotenv()
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    db["invoice"].update_one(
        {"invoice_number": invoice_number},
        {"$set": {"reminder_date": reminder_date}}
    )
    results.append(f"Step 3 ✅ Payment reminder scheduled for {reminder_date}")

    return jsonify({
        "success": True,
        "invoice_number": invoice_number,
        "steps_completed": results,
        "message": f"Invoice {invoice_number} created, sent to {data['customer_email']}, and reminder set for {reminder_date}"
    })


# ── 8. CHASE MY MONEY (Multi-step) ───────────────────
@app.route('/chase_money', methods=['POST'])
def api_chase_money():
    from pymongo import MongoClient
    from dotenv import load_dotenv
    from datetime import datetime, timedelta
    load_dotenv()
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    results = []
    reminders_sent = []

    # Step 1 — Find all unpaid invoices
    unpaid = list(db["invoice"].find({"status": "unpaid"}, {"_id": 0}))
    results.append(f"Step 1 ✅ Found {len(unpaid)} unpaid invoices")

    # Step 2 — Filter overdue ones (older than 7 days)
    today = datetime.now()
    overdue = []
    for inv in unpaid:
        created = datetime.strptime(inv['date_created'], "%Y-%m-%d")
        days_overdue = (today - created).days
        if days_overdue >= 7:
            inv['days_overdue'] = days_overdue
            overdue.append(inv)
    results.append(f"Step 2 ✅ {len(overdue)} invoices are overdue by 7+ days")

    # Step 3 — Send reminder to each overdue customer
    for inv in overdue:
        send_reminder_email(
            customer_name=inv['customer_name'],
            customer_email=inv['customer_email'],
            invoice_number=inv['invoice_number'],
            total_amount=inv['total_amount'],
            days_overdue=inv['days_overdue']
        )
        # Step 4 — Log reminder in MongoDB
        db["invoice"].update_one(
            {"invoice_number": inv['invoice_number']},
            {"$set": {"last_reminder_sent": today.strftime("%Y-%m-%d")}}
        )
        reminders_sent.append({
            "customer": inv['customer_name'],
            "amount": inv['total_amount'],
            "days_overdue": inv['days_overdue']
        })
    results.append(f"Step 3 ✅ Reminders sent to {len(overdue)} customers")
    results.append(f"Step 4 ✅ Reminder dates logged in database")

    # Step 5 — Calculate total outstanding
    total_outstanding = sum(inv['total_amount'] for inv in overdue)
    results.append(f"Step 5 ✅ Total outstanding calculated")

    return jsonify({
        "success": True,
        "steps_completed": results,
        "reminders_sent": reminders_sent,
        "total_outstanding": total_outstanding,
        "message": f"Sent reminders to {len(overdue)} customers. Total outstanding: ₦{total_outstanding:,}"
    })


# ── 9. END OF DAY REPORT (Multi-step) ────────────────
@app.route('/daily_report', methods=['GET'])
def api_daily_report():
    from pymongo import MongoClient
    from dotenv import load_dotenv
    from datetime import datetime
    load_dotenv()
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    today = datetime.now().strftime("%Y-%m-%d")
    results = []

    # Step 1 — Get today's sales
    todays_sales = list(db["sales"].find(
        {"date": today}, {"_id": 0}
    ))
    total_revenue = sum(s["sale_amount"] for s in todays_sales)
    total_profit = sum(s["profit"] for s in todays_sales)
    results.append(f"Step 1 ✅ Found {len(todays_sales)} sales today")

    # Step 2 — Get all unpaid invoices
    unpaid = list(db["invoice"].find({"status": "unpaid"}, {"_id": 0}))
    total_outstanding = sum(inv["total_amount"] for inv in unpaid)
    results.append(f"Step 2 ✅ Found {len(unpaid)} unpaid invoices")

    # Step 3 — Get exchange rate
    try:
        import requests
        rate_response = requests.get(
            "https://api.exchangerate-api.com/v4/latest/USD",
            timeout=5
        )
        usd_ngn_rate = rate_response.json()["rates"]["NGN"]
    except:
        usd_ngn_rate = "unavailable"
    results.append(f"Step 3 ✅ Live exchange rate fetched")

    # Step 4 — Build report
    report = {
        "date": today,
        "sales_count": len(todays_sales),
        "total_revenue": total_revenue,
        "total_profit": total_profit,
        "unpaid_invoices": len(unpaid),
        "total_outstanding": total_outstanding,
        "usd_ngn_rate": usd_ngn_rate
    }
    results.append(f"Step 4 ✅ Report compiled")

    return jsonify({
        "success": True,
        "steps_completed": results,
        "report": report,
        "message": f"Today: {len(todays_sales)} sales, ₦{total_revenue:,} revenue, ₦{total_profit:,} profit. Outstanding debt: ₦{total_outstanding:,}. USD/NGN: {usd_ngn_rate}"
    })


# ── 10. ADD CUSTOMER (Multi-step) ─────────────────────
@app.route('/add_customer', methods=['POST'])
def api_add_customer():
    from pymongo import MongoClient
    from dotenv import load_dotenv
    from datetime import datetime
    load_dotenv()
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DB_NAME")]
    data = request.json
    results = []

    # Step 1 — Save customer to MongoDB
    existing = db["customers"].find_one({"customer_email": data["customer_email"]})
    if existing:
        return jsonify({
            "success": False,
            "message": f"{data['customer_name']} already exists in your records"
        })
    db["customers"].insert_one({
        "customer_name": data["customer_name"],
        "customer_email": data["customer_email"],
        "phone": data.get("phone", ""),
        "total_invoiced": 0,
        "total_paid": 0,
        "outstanding_balance": 0,
        "date_added": datetime.now().strftime("%Y-%m-%d")
    })
    results.append(f"Step 1 ✅ {data['customer_name']} saved to database")

    # Step 2 — Send welcome email
    send_welcome_email(
        customer_name=data["customer_name"],
        customer_email=data["customer_email"],
        business_name=data.get("business_name", "Prosper Stores")
    )
    results.append(f"Step 2 ✅ Welcome email sent to {data['customer_email']}")

    return jsonify({
        "success": True,
        "steps_completed": results,
        "message": f"{data['customer_name']} added successfully! Welcome email sent."
    })
# ── MCP ENDPOINT ─────────────────────────────────────
@app.route('/mcp', methods=['GET', 'POST'])
def mcp_endpoint():
    return jsonify({
        "name": "Prosper Assistant API",
        "version": "1.0",
        "description": "AI-powered business agent for Nigerian SMEs",
        "tools": [
            {
                "name": "get_unpaid_invoices",
                "description": "Get all unpaid invoices and who owes money",
                "endpoint": "/unpaid_invoices",
                "method": "GET"
            },
            {
                "name": "log_sale",
                "description": "Log a sale with revenue and profit calculation",
                "endpoint": "/log_sale",
                "method": "POST"
            },
            {
                "name": "create_and_send_invoice",
                "description": "Create invoice, save to database and email to customer",
                "endpoint": "/create_and_send_invoice",
                "method": "POST"
            },
            {
                "name": "chase_money",
                "description": "Send payment reminders to all overdue customers",
                "endpoint": "/chase_money",
                "method": "POST"
            },
            {
                "name": "daily_report",
                "description": "Get daily business report with sales, revenue and outstanding debt",
                "endpoint": "/daily_report",
                "method": "GET"
            },
            {
                "name": "mark_invoice_paid",
                "description": "Mark an invoice as paid",
                "endpoint": "/mark_paid",
                "method": "POST"
            },
            {
                "name": "add_customer",
                "description": "Add a new customer and send welcome email",
                "endpoint": "/add_customer",
                "method": "POST"
            }
        ]
    })
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)