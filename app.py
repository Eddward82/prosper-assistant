from flask import Flask, request, jsonify
from agent_tools import save_invoice, get_unpaid_invoices, log_sale, mark_invoice_paid, get_sales_summary
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

if __name__ == '__main__':
    app.run(debug=True, port=5000)