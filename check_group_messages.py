import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

client = create_client(supabase_url, supabase_key)

# Check group_messages for system messages
response = client.table("group_messages").select("*").eq("is_system", True).order("created_at", desc=True).limit(10).execute()

print("=== System Messages in Group Chat ===")
if response.data:
    for msg in response.data:
        print(f"\nGroup ID: {msg['group_id']}")
        print(f"Sender: {msg.get('sender_name', 'N/A')}")
        print(f"Message: {msg['message']}")
        print(f"Created: {msg['created_at']}")
        print("-" * 50)
else:
    print("No system messages found in group_messages table")

# Also check if columns exist
print("\n=== Checking table structure ===")
try:
    test = client.table("group_messages").select("is_system, sender_name").limit(1).execute()
    print("✅ Columns 'is_system' and 'sender_name' exist in table")
except Exception as e:
    print(f"❌ Error: {e}")

