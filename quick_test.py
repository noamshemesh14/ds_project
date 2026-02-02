"""
Quick diagnostic to check if everything is working
"""
import requests
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000"

print("="*60)
print("🔍 QUICK DIAGNOSTIC CHECK")
print("="*60)

# 1. Check if server is responding
print("\n1️⃣ Checking server...")
try:
    response = requests.get(f"{BASE_URL}/", timeout=5)
    print(f"   ✅ Server is responding (status {response.status_code})")
except Exception as e:
    print(f"   ❌ Server not responding: {e}")
    exit(1)

# 2. Login (update these!)
email = "your_email@example.com"  # ⚠️ CHANGE THIS
password = "your_password"         # ⚠️ CHANGE THIS

print(f"\n2️⃣ Logging in as {email}...")
login_response = requests.post(
    f"{BASE_URL}/api/login",
    json={"email": email, "password": password}
)

if login_response.status_code != 200:
    print(f"   ❌ Login failed! Update email/password in this script")
    print(f"   Status: {login_response.status_code}")
    exit(1)

token = login_response.json()["access_token"]
print("   ✅ Logged in successfully!")

# 3. Check preferences
print("\n3️⃣ Checking user preferences...")
prefs_response = requests.get(
    f"{BASE_URL}/api/user/preferences",
    headers={"Authorization": f"Bearer {token}"}
)

if prefs_response.status_code == 200:
    prefs = prefs_response.json()
    raw = prefs.get("study_preferences_raw")
    if raw:
        print(f"   ✅ Preferences found: {raw[:60]}...")
    else:
        print("   ⚠️ No preferences set! Go to /profile to set them")
else:
    print(f"   ❌ Failed to check preferences: {prefs_response.status_code}")

# 4. Check schedule
print("\n4️⃣ Checking current schedule...")
today = datetime.now()
days_since_sunday = (today.weekday() + 1) % 7
week_start = (today - timedelta(days=days_since_sunday)).strftime("%Y-%m-%d")

schedule_response = requests.get(
    f"{BASE_URL}/api/weekly-plan?week_start={week_start}",
    headers={"Authorization": f"Bearer {token}"}
)

if schedule_response.status_code == 200:
    schedule_data = schedule_response.json()
    blocks = schedule_data.get("blocks", [])
    print(f"   ✅ Schedule has {len(blocks)} blocks")
    
    personal = [b for b in blocks if b.get("work_type") == "personal"]
    group = [b for b in blocks if b.get("work_type") == "group"]
    
    print(f"      📘 {len(personal)} personal blocks")
    print(f"      👥 {len(group)} group blocks")
    
    # Check source to see if LLM was used
    llm_blocks = [b for b in personal if b.get("source") == "llm"]
    manual_blocks = [b for b in personal if b.get("source") == "manual"]
    auto_blocks = [b for b in personal if b.get("source") in ["auto", "auto_fallback", None]]
    
    if llm_blocks:
        print(f"      🤖 {len(llm_blocks)} blocks placed by LLM! ✅")
    if auto_blocks:
        print(f"      🔧 {len(auto_blocks)} blocks placed by deterministic logic")
    if manual_blocks:
        print(f"      ✋ {len(manual_blocks)} blocks manually edited")
        
else:
    print(f"   ❌ Failed to get schedule: {schedule_response.status_code}")

# 5. Check notifications
print("\n5️⃣ Checking notifications...")
notif_response = requests.get(
    f"{BASE_URL}/api/notifications",
    headers={"Authorization": f"Bearer {token}"}
)

if notif_response.status_code == 200:
    notifications = notif_response.json()
    unread = [n for n in notifications if not n.get("read", True)]
    print(f"   ✅ {len(notifications)} total notifications, {len(unread)} unread")
    
    if unread:
        print("\n   Recent unread:")
        for n in unread[:3]:
            print(f"      - [{n.get('type')}] {n.get('title', '')[:50]}")
else:
    print(f"   ❌ Failed to check notifications: {notif_response.status_code}")

# 6. Check groups
print("\n6️⃣ Checking groups...")
groups_response = requests.get(
    f"{BASE_URL}/api/groups/my-groups",
    headers={"Authorization": f"Bearer {token}"}
)

if groups_response.status_code == 200:
    groups_data = groups_response.json()
    groups = groups_data.get("groups", [])
    print(f"   ✅ You're in {len(groups)} groups")
    
    if groups:
        for g in groups[:2]:
            print(f"      - {g.get('group_name')}")
else:
    print(f"   ⚠️ Could not check groups: {groups_response.status_code}")

print("\n" + "="*60)
print("📊 SUMMARY")
print("="*60)

if llm_blocks:
    print("✅ LLM IS WORKING! Your schedule was optimized based on preferences!")
    print(f"   {len(llm_blocks)} personal blocks were placed by GPT-4o mini")
else:
    print("⚠️  LLM NOT USED - blocks were placed by deterministic logic")
    print("   Possible reasons:")
    print("   - No user preferences set")
    print("   - OpenAI API key not set in .env")
    print("   - LLM call failed (check server logs)")

print("\n💡 Next steps:")
print("   1. Go to http://localhost:8000/schedule")
print("   2. Try dragging a blue block (👤 Personal)")
print("   3. Try dragging a purple block (👥 Group)")
print("   4. Check notifications bell (🔔)")



