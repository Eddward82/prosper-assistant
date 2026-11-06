from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

client = MongoClient(os.getenv("MONGODB_URI"))
db = client[os.getenv("DB_NAME")]

# Add empty phone field to all existing customers without one
result = db["customers"].update_many(
    {"phone": {"$exists": False}},
    {"$set": {"phone": ""}}
)
print(f"Updated {result.modified_count} customer records with empty phone field")
print("Migration complete!")