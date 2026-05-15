from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

client = MongoClient(os.getenv("MONGODB_URI"))
db = client[os.getenv("DB_NAME")]

# Your business_id (use lowercase, no spaces — like a slug)
BUSINESS_ID = "smartbloom-ai"
BUSINESS_NAME = "SmartBloom AI"
OWNER_NAME = "Olubunmi Edward Ogunlusi"
BUSINESS_EMAIL = "ogunlusiolubunmi@gmail.com"

# Migrate invoices
invoices_updated = db["invoice"].update_many(
    {"business_id": {"$exists": False}},
    {"$set": {"business_id": BUSINESS_ID}}
)
print(f"Updated {invoices_updated.modified_count} invoices")

# Migrate sales
sales_updated = db["sales"].update_many(
    {"business_id": {"$exists": False}},
    {"$set": {"business_id": BUSINESS_ID}}
)
print(f"Updated {sales_updated.modified_count} sales")

# Migrate customers
customers_updated = db["customers"].update_many(
    {"business_id": {"$exists": False}},
    {"$set": {"business_id": BUSINESS_ID}}
)
print(f"Updated {customers_updated.modified_count} customers")

# Create a businesses collection to track all businesses
businesses = db["businesses"]
businesses.update_one(
    {"business_id": BUSINESS_ID},
    {
        "$set": {
            "business_id": BUSINESS_ID,
            "business_name": BUSINESS_NAME,
            "owner_name": OWNER_NAME,
            "business_email": BUSINESS_EMAIL
        }
    },
    upsert=True
)
print(f"Created/updated business: {BUSINESS_NAME}")
print("\n✅ Migration complete!")