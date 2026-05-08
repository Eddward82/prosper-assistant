from pymongo import MongoClient
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

# Connect to MongoDB
client = MongoClient(os.getenv("MONGODB_URI"))
db = client[os.getenv("DB_NAME")]

# Collections
invoices = db["invoice"]
sales = db["sales"]
customers = db["customers"]

# ── 1. SAVE AN INVOICE ──────────────────────────────
def save_invoice(customer_name, customer_email, items, total_amount, business_name):
    # Get the next invoice number
    count = invoices.count_documents({})
    invoice_number = f"INV-{str(count + 1).zfill(3)}"
    
    invoice = {
        "invoice_number": invoice_number,
        "customer_name": customer_name,
        "customer_email": customer_email,
        "items": items,
        "total_amount": total_amount,
        "status": "unpaid",
        "date_created": datetime.now().strftime("%Y-%m-%d"),
        "due_date": "",
        "business_name": business_name
    }
    
    invoices.insert_one(invoice)
    
    # Update or create customer record
    customers.update_one(
        {"customer_email": customer_email},
        {
            "$set": {"customer_name": customer_name},
            "$inc": {
                "total_invoiced": total_amount,
                "outstanding_balance": total_amount
            },
            "$setOnInsert": {"total_paid": 0}
        },
        upsert=True
    )
    
    print(f"✅ Invoice {invoice_number} saved for {customer_name} — ₦{total_amount:,}")
    return invoice_number

# ── 2. GET UNPAID INVOICES ──────────────────────────
def get_unpaid_invoices():
    unpaid = list(invoices.find({"status": "unpaid"}, {"_id": 0}))
    
    if not unpaid:
        print("✅ No unpaid invoices. Everyone has paid!")
        return []
    
    print(f"\n📋 UNPAID INVOICES ({len(unpaid)} total):")
    print("-" * 50)
    for inv in unpaid:
        print(f"• {inv['invoice_number']} | {inv['customer_name']} | ₦{inv['total_amount']:,} | Created: {inv['date_created']}")
    
    return unpaid

# ── 3. LOG A SALE ───────────────────────────────────
def log_sale(item, quantity, sale_amount, cost_amount):
    profit = sale_amount - cost_amount
    
    sale = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "item": item,
        "quantity": quantity,
        "sale_amount": sale_amount,
        "cost_amount": cost_amount,
        "profit": profit,
        "recorded_by": "Prosper Assistant"
    }
    
    sales.insert_one(sale)
    print(f"✅ Sale recorded — {quantity} {item} | Revenue: ₦{sale_amount:,} | Profit: ₦{profit:,}")
    return profit

# ── 4. MARK INVOICE AS PAID ─────────────────────────
def mark_invoice_paid(invoice_number):
    invoice = invoices.find_one({"invoice_number": invoice_number})
    
    if not invoice:
        print(f"❌ Invoice {invoice_number} not found")
        return False
    
    invoices.update_one(
        {"invoice_number": invoice_number},
        {"$set": {"status": "paid", "date_paid": datetime.now().strftime("%Y-%m-%d")}}
    )
    
    customers.update_one(
        {"customer_email": invoice["customer_email"]},
        {
            "$inc": {
                "total_paid": invoice["total_amount"],
                "outstanding_balance": -invoice["total_amount"]
            }
        }
    )
    
    print(f"✅ Invoice {invoice_number} marked as paid!")
    return True

# ── 5. GET SALES SUMMARY ────────────────────────────
def get_sales_summary():
    all_sales = list(sales.find({}, {"_id": 0}))
    
    if not all_sales:
        print("No sales recorded yet.")
        return
    
    total_revenue = sum(s["sale_amount"] for s in all_sales)
    total_profit = sum(s["profit"] for s in all_sales)
    
    print(f"\n📊 SALES SUMMARY")
    print("-" * 50)
    print(f"Total Sales: {len(all_sales)}")
    print(f"Total Revenue: ₦{total_revenue:,}")
    print(f"Total Profit: ₦{total_profit:,}")

# ── TEST ALL FUNCTIONS ──────────────────────────────
if __name__ == "__main__":
    print("🚀 Testing Prosper Assistant Database...\n")
    
    # Test 1: Save an invoice
    save_invoice(
        customer_name="Amaka Johnson",
        customer_email="amaka@example.com",
        items=[{"description": "10 cartons of Indomie", "amount": 85000}],
        total_amount=85000,
        business_name="Prosper Stores"
    )
    
    # Test 2: Log a sale
    log_sale(
        item="Bags of rice",
        quantity=20,
        sale_amount=45000,
        cost_amount=31000
    )
    
    # Test 3: Get unpaid invoices
    get_unpaid_invoices()
    
    # Test 4: Get sales summary
    get_sales_summary()