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
# ── EMAIL FUNCTIONS ──────────────────────────────────
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_invoice_email(customer_name, customer_email, invoice_number, items, total_amount, business_name):
    try:
        sender_email = os.getenv("GMAIL_USER")
        sender_password = os.getenv("GMAIL_APP_PASSWORD")

        msg = MIMEMultipart("alternative")
        msg['Subject'] = f"Invoice {invoice_number} from {business_name}"
        msg['From'] = sender_email
        msg['To'] = customer_email

        items_html = "".join([f"<tr><td>{item['description']}</td><td>₦{item['amount']:,}</td></tr>" for item in items])

        html = f"""
        <html><body>
        <h2>Invoice from {business_name}</h2>
        <p>Dear {customer_name},</p>
        <p>Please find your invoice below:</p>
        <table border='1' cellpadding='8'>
            <tr><th>Description</th><th>Amount</th></tr>
            {items_html}
            <tr><td><strong>Total</strong></td><td><strong>₦{total_amount:,}</strong></td></tr>
        </table>
        <p>Please make payment at your earliest convenience.</p>
        <p>Thank you for your business!</p>
        <p><strong>{business_name}</strong></p>
        </body></html>
        """

        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, customer_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False


def send_reminder_email(customer_name, customer_email, invoice_number, total_amount, days_overdue):
    try:
        sender_email = os.getenv("GMAIL_USER")
        sender_password = os.getenv("GMAIL_APP_PASSWORD")

        msg = MIMEMultipart("alternative")
        msg['Subject'] = f"Payment Reminder — Invoice {invoice_number}"
        msg['From'] = sender_email
        msg['To'] = customer_email

        html = f"""
        <html><body>
        <h2>Payment Reminder</h2>
        <p>Dear {customer_name},</p>
        <p>This is a friendly reminder that invoice <strong>{invoice_number}</strong> 
        for <strong>₦{total_amount:,}</strong> is now <strong>{days_overdue} days overdue.</strong></p>
        <p>Please make payment as soon as possible to avoid any disruption to your account.</p>
        <p>If you have already made payment, please disregard this message.</p>
        <p>Thank you.</p>
        </body></html>
        """

        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, customer_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Reminder email error: {e}")
        return False


def send_welcome_email(customer_name, customer_email, business_name):
    try:
        sender_email = os.getenv("GMAIL_USER")
        sender_password = os.getenv("GMAIL_APP_PASSWORD")

        msg = MIMEMultipart("alternative")
        msg['Subject'] = f"Welcome! You're now a customer of {business_name}"
        msg['From'] = sender_email
        msg['To'] = customer_email

        html = f"""
        <html><body>
        <h2>Welcome, {customer_name}!</h2>
        <p>You have been added as a customer of <strong>{business_name}</strong>.</p>
        <p>You will receive invoices and updates from us going forward.</p>
        <p>Thank you for your business!</p>
        </body></html>
        """

        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, customer_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Welcome email error: {e}")
        return False
# ── EMAIL FUNCTIONS ──────────────────────────────────
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_invoice_email(customer_name, customer_email, invoice_number, items, total_amount, business_name):
    try:
        sender_email = os.getenv("GMAIL_USER")
        sender_password = os.getenv("GMAIL_APP_PASSWORD")

        msg = MIMEMultipart("alternative")
        msg['Subject'] = f"Invoice {invoice_number} from {business_name}"
        msg['From'] = sender_email
        msg['To'] = customer_email

        items_html = "".join([f"<tr><td>{item['description']}</td><td>₦{item['amount']:,}</td></tr>" for item in items])

        html = f"""
        <html><body>
        <h2>Invoice from {business_name}</h2>
        <p>Dear {customer_name},</p>
        <p>Please find your invoice below:</p>
        <table border='1' cellpadding='8'>
            <tr><th>Description</th><th>Amount</th></tr>
            {items_html}
            <tr><td><strong>Total</strong></td><td><strong>₦{total_amount:,}</strong></td></tr>
        </table>
        <p>Please make payment at your earliest convenience.</p>
        <p>Thank you for your business!</p>
        <p><strong>{business_name}</strong></p>
        </body></html>
        """

        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, customer_email, msg.as_string())
        print(f"✅ Invoice email sent to {customer_email}")
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False


def send_reminder_email(customer_name, customer_email, invoice_number, total_amount, days_overdue):
    try:
        sender_email = os.getenv("GMAIL_USER")
        sender_password = os.getenv("GMAIL_APP_PASSWORD")

        msg = MIMEMultipart("alternative")
        msg['Subject'] = f"Payment Reminder — Invoice {invoice_number}"
        msg['From'] = sender_email
        msg['To'] = customer_email

        html = f"""
        <html><body>
        <h2>Payment Reminder</h2>
        <p>Dear {customer_name},</p>
        <p>This is a friendly reminder that invoice <strong>{invoice_number}</strong> 
        for <strong>₦{total_amount:,}</strong> is now <strong>{days_overdue} days overdue.</strong></p>
        <p>Please make payment as soon as possible.</p>
        <p>If you have already made payment, please disregard this message.</p>
        <p>Thank you.</p>
        </body></html>
        """

        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, customer_email, msg.as_string())
        print(f"✅ Reminder sent to {customer_email}")
        return True
    except Exception as e:
        print(f"❌ Reminder error: {e}")
        return False


def send_welcome_email(customer_name, customer_email, business_name):
    try:
        sender_email = os.getenv("GMAIL_USER")
        sender_password = os.getenv("GMAIL_APP_PASSWORD")

        msg = MIMEMultipart("alternative")
        msg['Subject'] = f"Welcome! You're now a customer of {business_name}"
        msg['From'] = sender_email
        msg['To'] = customer_email

        html = f"""
        <html><body>
        <h2>Welcome, {customer_name}!</h2>
        <p>You have been added as a customer of <strong>{business_name}</strong>.</p>
        <p>You will receive invoices and updates from us going forward.</p>
        <p>Thank you for your business!</p>
        </body></html>
        """

        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, customer_email, msg.as_string())
        print(f"✅ Welcome email sent to {customer_email}")
        return True
    except Exception as e:
        print(f"❌ Welcome email error: {e}")
        return False