from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

client = MongoClient(os.getenv("MONGODB_URI"))
db = client[os.getenv("DB_NAME")]

db["customers"].update_one(
    {"customer_email": "chidi@example.com"},
    {
        "$set": {
            "customer_name": "Chidi Okeke",
            "customer_email": "chidi@example.com"
        },
        "$setOnInsert": {
            "total_invoiced": 120000,
            "outstanding_balance": 120000,
            "total_paid": 0
        }
    },
    upsert=True
)

print("✅ Chidi Okeke added to customers!")