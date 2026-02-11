"""
Script to fix all course_time_preferences based on credit points (prior)
Recalculates personal_hours_per_week and group_hours_per_week for all courses
based on their credit points: total_hours = credit_points * 3, then 50/50 split
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

print("🔄 Starting to fix course_time_preferences based on credit points...")
print("=" * 60)

# Get all course_time_preferences
print("\n1️⃣ Fetching all course_time_preferences...")
try:
    prefs_result = client.table("course_time_preferences").select("user_id, course_number").execute()
    all_prefs = prefs_result.data or []
    print(f"   ✅ Found {len(all_prefs)} course_time_preferences entries")
    
    if not all_prefs:
        print("   ℹ️ No course_time_preferences found. Nothing to fix.")
        sys.exit(0)
    
except Exception as e:
    print(f"   ❌ Error fetching course_time_preferences: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Process each preference entry
print("\n2️⃣ Processing and updating preferences...")
updated_count = 0
skipped_count = 0
error_count = 0

for idx, pref in enumerate(all_prefs, 1):
    user_id = pref.get("user_id")
    course_number = pref.get("course_number")
    
    if not user_id or not course_number:
        print(f"   ⚠️ Entry {idx}: Missing user_id or course_number, skipping")
        skipped_count += 1
        continue
    
    try:
        # Try to get credit points from user's course first
        course_result = client.table("courses").select("credit_points").eq("user_id", user_id).eq("course_number", course_number).limit(1).execute()
        
        credit_points = None
        if course_result.data and course_result.data[0].get("credit_points"):
            credit_points = course_result.data[0].get("credit_points")
        
        # If not found in user's courses, try catalog
        if credit_points is None:
            catalog_result = client.table("course_catalog").select("credit_points").eq("course_number", course_number).limit(1).execute()
            if catalog_result.data and catalog_result.data[0].get("credit_points"):
                credit_points = catalog_result.data[0].get("credit_points")
        
        # Default to 3 if still not found
        if credit_points is None:
            credit_points = 3
            print(f"   ⚠️ Entry {idx}: Course {course_number} not found, using default 3 credit points")
        
        # Calculate hours based on credit points
        total_hours = credit_points * 3
        default_personal_hours = max(1, int(total_hours * 0.5))  # 50% personal
        default_group_hours = max(1, total_hours - default_personal_hours)  # 50% group
        
        # Update the preference
        update_result = client.table("course_time_preferences").update({
            "personal_hours_per_week": default_personal_hours,
            "group_hours_per_week": default_group_hours
        }).eq("user_id", user_id).eq("course_number", course_number).execute()
        
        if update_result.data:
            updated_count += 1
            if (idx % 10 == 0) or (idx == len(all_prefs)):
                print(f"   ✅ Updated {idx}/{len(all_prefs)}: Course {course_number} (user {user_id[:8]}...): {default_personal_hours}h personal, {default_group_hours}h group (from {credit_points} credit points)")
        else:
            print(f"   ⚠️ Entry {idx}: Update returned no data for course {course_number}")
            skipped_count += 1
            
    except Exception as e:
        error_count += 1
        print(f"   ❌ Entry {idx}: Error processing course {course_number} (user {user_id[:8] if user_id else 'N/A'}...): {str(e)[:100]}")
        if error_count > 10:
            print(f"   ⚠️ Too many errors, stopping...")
            break

print("\n" + "=" * 60)
print("📊 Summary:")
print(f"   ✅ Successfully updated: {updated_count} entries")
print(f"   ⚠️ Skipped: {skipped_count} entries")
print(f"   ❌ Errors: {error_count} entries")
print(f"   📝 Total processed: {len(all_prefs)} entries")
print("\n✅ Script completed!")




