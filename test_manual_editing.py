"""
Test script for manual editing and group approval features
Run this after setting up the database to verify everything works.
"""

import requests
import json
from datetime import datetime, timedelta

# Configuration
BASE_URL = "http://localhost:8000"
TEST_USER_EMAIL = "test@example.com"  # Change this to your test user
TEST_USER_PASSWORD = "password123"      # Change this to your test user password

def print_section(title):
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def login(email, password):
    """Login and get JWT token"""
    print_section("🔐 Logging In")
    response = requests.post(
        f"{BASE_URL}/api/login",
        json={"email": email, "password": password}
    )
    if response.status_code == 200:
        data = response.json()
        token = data.get("access_token")
        print(f"✅ Logged in successfully!")
        print(f"Token: {token[:50]}...")
        return token
    else:
        print(f"❌ Login failed: {response.status_code}")
        print(response.text)
        return None

def test_preferences(token):
    """Test saving and loading preferences"""
    print_section("📝 Testing User Preferences")
    
    # Save preferences
    preferences = "I prefer to study in the mornings between 8-12. I like 2-3 hour blocks with breaks. Avoid Fridays."
    save_response = requests.post(
        f"{BASE_URL}/api/user/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={"study_preferences_raw": preferences}
    )
    
    if save_response.status_code == 200:
        print("✅ Preferences saved successfully")
    else:
        print(f"❌ Failed to save preferences: {save_response.status_code}")
        print(save_response.text)
        return False
    
    # Load preferences
    load_response = requests.get(
        f"{BASE_URL}/api/user/preferences",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    if load_response.status_code == 200:
        data = load_response.json()
        print(f"✅ Preferences loaded: {data.get('study_preferences_raw')[:50]}...")
        return True
    else:
        print(f"❌ Failed to load preferences: {load_response.status_code}")
        return False

def test_schedule_generation(token):
    """Test LLM-based schedule generation"""
    print_section("🤖 Testing Schedule Generation")
    
    response = requests.post(
        f"{BASE_URL}/api/weekly-plan/run-immediately",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    if response.status_code == 200:
        print("✅ Schedule generation triggered successfully")
        print("📊 Check server logs for LLM output")
        return True
    else:
        print(f"❌ Failed to generate schedule: {response.status_code}")
        print(response.text)
        return False

def test_get_schedule(token):
    """Get current week's schedule"""
    print_section("📅 Getting Current Schedule")
    
    # Calculate current week start (Sunday)
    today = datetime.now()
    days_since_sunday = (today.weekday() + 1) % 7
    week_start = (today - timedelta(days=days_since_sunday)).strftime("%Y-%m-%d")
    
    response = requests.get(
        f"{BASE_URL}/api/weekly-plan?week_start={week_start}",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    if response.status_code == 200:
        data = response.json()
        blocks = data.get("blocks", [])
        print(f"✅ Schedule loaded: {len(blocks)} blocks")
        
        # Show summary
        personal_blocks = [b for b in blocks if b.get("work_type") == "personal"]
        group_blocks = [b for b in blocks if b.get("work_type") == "group"]
        
        print(f"   📘 Personal blocks: {len(personal_blocks)}")
        print(f"   👥 Group blocks: {len(group_blocks)}")
        
        if blocks:
            print("\n   First block:")
            first_block = blocks[0]
            print(f"   - ID: {first_block.get('id')}")
            print(f"   - Course: {first_block.get('course_name')}")
            print(f"   - Day: {first_block.get('day_of_week')}")
            print(f"   - Time: {first_block.get('start_time')}")
            print(f"   - Type: {first_block.get('work_type')}")
        
        return blocks
    else:
        print(f"❌ Failed to get schedule: {response.status_code}")
        return []

def test_move_block(token, block_id, new_day, new_time):
    """Test moving a schedule block"""
    print_section("🖱️ Testing Block Movement")
    
    print(f"Attempting to move block {block_id}")
    print(f"To: Day {new_day}, Time {new_time}")
    
    response = requests.post(
        f"{BASE_URL}/api/schedule/block/move",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "block_id": block_id,
            "new_day_of_week": new_day,
            "new_start_time": new_time
        }
    )
    
    if response.status_code == 200:
        data = response.json()
        print("✅ Block moved successfully!")
        print(f"   {json.dumps(data, indent=2)}")
        return True
    elif response.status_code == 400:
        data = response.json()
        if data.get("error") == "group_block":
            print("⚠️ This is a group block - requires approval workflow")
            print("   (This is expected behavior)")
            return True
        else:
            print(f"❌ Movement failed: {data}")
            return False
    else:
        print(f"❌ Movement failed: {response.status_code}")
        print(response.text)
        return False

def test_notifications(token):
    """Test notifications system"""
    print_section("🔔 Testing Notifications")
    
    response = requests.get(
        f"{BASE_URL}/api/notifications",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    if response.status_code == 200:
        notifications = response.json()
        print(f"✅ Notifications loaded: {len(notifications)} total")
        
        # Show unread
        unread = [n for n in notifications if not n.get("read", True)]
        print(f"   📬 Unread: {len(unread)}")
        
        if unread:
            print("\n   Recent unread notifications:")
            for notif in unread[:3]:
                print(f"   - {notif.get('type')}: {notif.get('title')}")
        
        return True
    else:
        print(f"❌ Failed to load notifications: {response.status_code}")
        return False

def main():
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║  🧪 MANUAL EDITING & GROUP APPROVAL TEST SUITE          ║
    ║                                                          ║
    ║  This script tests:                                      ║
    ║  ✅ User preferences (save/load)                         ║
    ║  ✅ LLM schedule generation                              ║
    ║  ✅ Schedule retrieval                                   ║
    ║  ✅ Block movement (personal)                            ║
    ║  ✅ Group block detection                                ║
    ║  ✅ Notifications system                                 ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    # Step 1: Login
    token = login(TEST_USER_EMAIL, TEST_USER_PASSWORD)
    if not token:
        print("\n❌ Cannot proceed without authentication")
        print("Please update TEST_USER_EMAIL and TEST_USER_PASSWORD in this script")
        return
    
    # Step 2: Test preferences
    if not test_preferences(token):
        print("⚠️ Preferences test failed - check if USER_PREFERENCES_SETUP.sql was run")
    
    # Step 3: Test schedule generation
    test_schedule_generation(token)
    
    # Step 4: Get schedule
    blocks = test_get_schedule(token)
    
    # Step 5: Test block movement (if we have blocks)
    if blocks:
        # Find a personal block to move
        personal_block = next((b for b in blocks if b.get("work_type") == "personal"), None)
        if personal_block:
            # Try to move it to next day
            current_day = personal_block.get("day_of_week")
            new_day = (current_day + 1) % 7
            test_move_block(token, personal_block["id"], new_day, "14:00")
        else:
            print("\n⚠️ No personal blocks found to test movement")
        
        # Find a group block to test detection
        group_block = next((b for b in blocks if b.get("work_type") == "group"), None)
        if group_block:
            print("\n   Testing group block detection:")
            test_move_block(token, group_block["id"], 3, "15:00")
        else:
            print("\n⚠️ No group blocks found to test detection")
    else:
        print("\n⚠️ No blocks in schedule - cannot test movement")
    
    # Step 6: Test notifications
    test_notifications(token)
    
    # Summary
    print_section("📊 Test Summary")
    print("""
    ✅ Core Features Tested
    
    Next steps:
    1. Check server logs for LLM calls
    2. Try drag-and-drop in browser UI
    3. Create a group change request
    4. Test approval workflow with multiple users
    
    For full UI testing:
    - Go to http://localhost:8000/profile (set preferences)
    - Go to http://localhost:8000/schedule (drag blocks)
    - Check notifications bell for approval requests
    """)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error running tests: {e}")
        import traceback
        traceback.print_exc()

