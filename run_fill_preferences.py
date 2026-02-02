"""
Script to fill missing course_time_preferences and group_preferences
for existing courses and groups that were created before auto-creation feature
"""
import os
import sys
import io
# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ncvchkyncwdeysqzkssk.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

if not SUPABASE_SERVICE_ROLE_KEY:
    print("❌ Error: SUPABASE_SERVICE_ROLE_KEY environment variable is required")
    print("Please set it in your .env file or environment variables")
    sys.exit(1)

# Create admin client (bypasses RLS)
client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

print("🔄 Starting to fill missing preferences...")
print("=" * 60)

# 1. Fill course_time_preferences for existing courses
print("\n1️⃣ Filling course_time_preferences for existing courses...")
try:
    # Get all courses that don't have preferences
    courses_result = client.table("courses").select("user_id, course_number").execute()
    all_courses = courses_result.data or []
    
    # Get existing preferences
    prefs_result = client.table("course_time_preferences").select("user_id, course_number").execute()
    existing_prefs = {(p["user_id"], p["course_number"]) for p in (prefs_result.data or [])}
    
    # Find courses without preferences
    courses_to_add = []
    for course in all_courses:
        course_number = course.get("course_number")
        user_id = course.get("user_id")
        if course_number and user_id and (user_id, course_number) not in existing_prefs:
            # Calculate default hours based on credit points
            course_info = client.table("courses").select("credit_points").eq("user_id", user_id).eq("course_number", course_number).limit(1).execute()
            credit_points = course_info.data[0].get("credit_points") if course_info.data else 3
            total_hours = credit_points * 3
            default_personal_hours = max(1, int(total_hours * 0.5))
            default_group_hours = max(1, total_hours - default_personal_hours)
            
            courses_to_add.append({
                "user_id": user_id,
                "course_number": course_number,
                "personal_hours_per_week": default_personal_hours,
                "group_hours_per_week": default_group_hours
            })
    
    if courses_to_add:
        # Insert in batches of 100
        batch_size = 100
        total_inserted = 0
        for i in range(0, len(courses_to_add), batch_size):
            batch = courses_to_add[i:i + batch_size]
            try:
                result = client.table("course_time_preferences").insert(batch).execute()
                if result.data:
                    total_inserted += len(result.data)
                    print(f"   ✅ Inserted batch {i//batch_size + 1}: {len(result.data)} preferences")
            except Exception as e:
                # Some might already exist due to race conditions, that's okay
                print(f"   ⚠️ Batch {i//batch_size + 1} had some conflicts (may already exist): {str(e)[:100]}")
        
        print(f"   ✅ Total: Created course_time_preferences for {total_inserted} courses")
    else:
        print("   ℹ️ No courses need course_time_preferences (all already have them)")
        
except Exception as e:
    print(f"   ❌ Error filling course_time_preferences: {e}")
    import traceback
    traceback.print_exc()

# 2. Fill group_preferences for existing groups
print("\n2️⃣ Filling group_preferences for existing groups...")
try:
    # Get all groups
    groups_result = client.table("study_groups").select("id").execute()
    all_groups = groups_result.data or []
    
    # Get existing preferences
    gp_result = client.table("group_preferences").select("group_id").execute()
    existing_gp = {gp["group_id"] for gp in (gp_result.data or [])}
    
    # Find groups without preferences
    groups_to_add = []
    for group in all_groups:
        group_id = group.get("id")
        if group_id and group_id not in existing_gp:
            groups_to_add.append({
                "group_id": group_id,
                "preferred_hours_per_week": 4,
                "hours_change_history": []
            })
    
    if groups_to_add:
        # Insert in batches of 100
        batch_size = 100
        total_inserted = 0
        for i in range(0, len(groups_to_add), batch_size):
            batch = groups_to_add[i:i + batch_size]
            try:
                result = client.table("group_preferences").insert(batch).execute()
                if result.data:
                    total_inserted += len(result.data)
                    print(f"   ✅ Inserted batch {i//batch_size + 1}: {len(result.data)} preferences")
            except Exception as e:
                # Some might already exist due to race conditions, that's okay
                print(f"   ⚠️ Batch {i//batch_size + 1} had some conflicts (may already exist): {str(e)[:100]}")
        
        print(f"   ✅ Total: Created group_preferences for {total_inserted} groups")
    else:
        print("   ℹ️ No groups need group_preferences (all already have them)")
        
except Exception as e:
    print(f"   ❌ Error filling group_preferences: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("✅ Script completed!")

