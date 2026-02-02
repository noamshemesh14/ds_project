"""Check if schedule was generated and notifications sent"""
import requests
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000"

# UPDATE THESE!
email = "your_email@example.com"  # CHANGE THIS
password = "your_password"        # CHANGE THIS

print("Logging in...")
login_response = requests.post(
    f"{BASE_URL}/api/login",
    json={"email": email, "password": password}
)

if login_response.status_code != 200:
    print("ERROR: Update email/password in script!")
    exit(1)

token = login_response.json()["access_token"]
print("Logged in successfully!\n")

# Calculate week
today = datetime.now()
days_since_sunday = (today.weekday() + 1) % 7
week_start = (today - timedelta(days=days_since_sunday)).strftime("%Y-%m-%d")

# Check schedule
print(f"Checking schedule for week {week_start}...")
schedule_response = requests.get(
    f"{BASE_URL}/api/weekly-plan?week_start={week_start}",
    headers={"Authorization": f"Bearer {token}"}
)

if schedule_response.status_code == 200:
    data = schedule_response.json()
    blocks = data.get("blocks", [])
    print(f"  Schedule has {len(blocks)} blocks")
    
    personal = [b for b in blocks if b.get("work_type") == "personal"]
    group = [b for b in blocks if b.get("work_type") == "group"]
    
    print(f"    {len(personal)} personal blocks")
    print(f"    {len(group)} group blocks")
    
    # Check sources
    for source_type in ["llm", "auto", "auto_fallback", "group", "manual"]:
        count = len([b for b in blocks if b.get("source") == source_type])
        if count > 0:
            print(f"    {count} blocks from source: {source_type}")

# Check notifications
print("\nChecking notifications...")
notif_response = requests.get(
    f"{BASE_URL}/api/notifications",
    headers={"Authorization": f"Bearer {token}"}
)

if notif_response.status_code == 200:
    notifications = notif_response.json()
    unread = [n for n in notifications if not n.get("read", True)]
    print(f"  {len(notifications)} total, {len(unread)} unread")
    
    if unread:
        print("\n  Recent unread:")
        for n in unread[:5]:
            print(f"    - [{n.get('type')}] {n.get('title')}")

# Check groups and messages
print("\nChecking group messages...")
groups_response = requests.get(
    f"{BASE_URL}/api/groups/my-groups",
    headers={"Authorization": f"Bearer {token}"}
)

if groups_response.status_code == 200:
    groups_data = groups_response.json()
    groups = groups_data.get("groups", [])
    
    for group in groups[:2]:  # Check first 2 groups
        group_id = group["id"]
        group_name = group["group_name"]
        
        messages_response = requests.get(
            f"{BASE_URL}/api/groups/{group_id}/messages",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if messages_response.status_code == 200:
            messages = messages_response.json()
            system_messages = [m for m in messages if m.get("is_system") or m.get("sender_name") == "סוכן אקדמי"]
            
            print(f"  {group_name}: {len(messages)} messages, {len(system_messages)} from agent")
            
            if system_messages:
                latest = system_messages[0]
                print(f"    Latest agent message: {latest.get('message', '')[:60]}...")

print("\n" + "="*60)
print("Done!")



