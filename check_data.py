"""
Check if you have the necessary data for schedule generation
"""
import requests

BASE_URL = "http://localhost:8000"

# Login
email = "test@example.com"  # CHANGE THIS
password = "password"        # CHANGE THIS

print("🔐 Logging in...")
login_response = requests.post(
    f"{BASE_URL}/api/login",
    json={"email": email, "password": password}
)

if login_response.status_code != 200:
    print(f"❌ Login failed: {login_response.status_code}")
    print("Please update email and password in this script")
    exit(1)

token = login_response.json()["access_token"]
print("✅ Logged in successfully!\n")

# Check user data
print("=" * 60)
print("📊 CHECKING YOUR DATA")
print("=" * 60)

# Check courses
print("\n1️⃣ Checking your courses...")
courses_response = requests.get(
    f"{BASE_URL}/api/user-data",
    headers={"Authorization": f"Bearer {token}"}
)

if courses_response.status_code == 200:
    data = courses_response.json()
    courses = data.get("courses", [])
    print(f"   ✅ You have {len(courses)} courses")
    if courses:
        for course in courses[:3]:  # Show first 3
            print(f"      - {course.get('course_name')} ({course.get('course_number')})")
        if len(courses) > 3:
            print(f"      ... and {len(courses) - 3} more")
    else:
        print("   ⚠️ You have NO courses! Add some courses first.")
else:
    print(f"   ❌ Failed to get courses: {courses_response.status_code}")

# Check groups
print("\n2️⃣ Checking your groups...")
groups_response = requests.get(
    f"{BASE_URL}/api/groups/my-groups",
    headers={"Authorization": f"Bearer {token}"}
)

if groups_response.status_code == 200:
    groups_data = groups_response.json()
    groups = groups_data.get("groups", [])
    print(f"   ✅ You're in {len(groups)} groups")
    if groups:
        for group in groups[:3]:
            print(f"      - {group.get('group_name')} ({group.get('member_count', 0)} members)")
else:
    print(f"   ⚠️ Could not check groups: {groups_response.status_code}")

# Check preferences
print("\n3️⃣ Checking your study preferences...")
prefs_response = requests.get(
    f"{BASE_URL}/api/user/preferences",
    headers={"Authorization": f"Bearer {token}"}
)

if prefs_response.status_code == 200:
    prefs = prefs_response.json()
    raw_prefs = prefs.get("study_preferences_raw")
    if raw_prefs:
        print(f"   ✅ Preferences set: {raw_prefs[:60]}...")
    else:
        print("   ⚠️ No preferences set yet. Go to /profile to set them!")
else:
    print(f"   ⚠️ Could not check preferences: {prefs_response.status_code}")

# Check current schedule
print("\n4️⃣ Checking your current schedule...")
from datetime import datetime, timedelta
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
    print(f"   ✅ You have {len(blocks)} blocks in your schedule")
    
    if blocks:
        personal = [b for b in blocks if b.get("work_type") == "personal"]
        group = [b for b in blocks if b.get("work_type") == "group"]
        print(f"      - {len(personal)} personal blocks (👤)")
        print(f"      - {len(group)} group blocks (👥)")
        
        print("\n   Sample blocks:")
        for block in blocks[:3]:
            day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            day = day_names[block.get("day_of_week", 0)]
            print(f"      - {block.get('course_name')}: {day} {block.get('start_time')} ({block.get('work_type')})")
    else:
        print("   ⚠️ Your schedule is empty! Run generate_schedule.py to create one.")
else:
    print(f"   ⚠️ Could not check schedule: {schedule_response.status_code}")

print("\n" + "=" * 60)
print("📝 SUMMARY")
print("=" * 60)

if courses:
    if blocks:
        print("✅ You have courses and a schedule - ready to test drag-and-drop!")
    else:
        print("⚠️ You have courses but no schedule - run generate_schedule.py")
else:
    print("❌ You need to add courses first before generating a schedule")
    
print("\n💡 Next steps:")
if not courses:
    print("   1. Add some courses in the system")
if not raw_prefs:
    print("   2. Set your preferences at http://localhost:8000/profile")
if not blocks:
    print("   3. Run: python generate_schedule.py")
print("   4. Go to http://localhost:8000/schedule and test drag-and-drop!")



