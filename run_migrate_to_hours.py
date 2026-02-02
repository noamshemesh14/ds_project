"""
Script to migrate course_time_preferences from ratios to hours
and update existing data
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

print("🔄 Starting migration from ratios to hours...")
print("=" * 60)

# Step 1: Get all course_time_preferences with ratios
print("\n1️⃣ Fetching existing course_time_preferences...")
try:
    prefs_result = client.table("course_time_preferences").select("*").execute()
    all_prefs = prefs_result.data or []
    print(f"   Found {len(all_prefs)} course_time_preferences records")
    
    # Step 2: For each preference, calculate hours from ratios
    print("\n2️⃣ Calculating hours from ratios...")
    updated_count = 0
    
    for pref in all_prefs:
        user_id = pref.get("user_id")
        course_number = pref.get("course_number")
        personal_ratio = pref.get("personal_ratio")
        group_ratio = pref.get("group_ratio")
        
        # Skip if already has hours
        if pref.get("personal_hours_per_week") is not None:
            continue
        
        # Get course credit_points to calculate total hours
        course_result = client.table("courses").select("credit_points").eq("user_id", user_id).eq("course_number", course_number).limit(1).execute()
        
        if course_result.data and course_result.data[0].get("credit_points"):
            credit_points = course_result.data[0]["credit_points"]
            total_hours = credit_points * 3
        else:
            # Default: 3 credits = 9 hours
            total_hours = 9
        
        # Calculate hours from ratios
        if personal_ratio is not None:
            personal_hours = max(1, int(total_hours * personal_ratio))
        else:
            personal_hours = max(1, int(total_hours * 0.5))  # Default 50%
        
        if group_ratio is not None:
            group_hours = max(1, int(total_hours * group_ratio))
        else:
            group_hours = max(1, total_hours - personal_hours)  # Remainder
        
        # Update the record
        try:
            client.table("course_time_preferences").update({
                "personal_hours_per_week": personal_hours,
                "group_hours_per_week": group_hours
            }).eq("id", pref["id"]).execute()
            updated_count += 1
        except Exception as e:
            print(f"   ⚠️ Error updating {course_number} for user {user_id}: {str(e)[:100]}")
    
    print(f"   ✅ Updated {updated_count} records with hours")
    
except Exception as e:
    print(f"   ❌ Error during migration: {e}")
    import traceback
    traceback.print_exc()

# Step 3: Update any records that still have NULL hours (set defaults)
print("\n3️⃣ Setting defaults for any remaining NULL values...")
try:
    # Get records with NULL hours
    null_prefs = client.table("course_time_preferences").select("id, user_id, course_number").is_("personal_hours_per_week", "null").execute()
    
    if null_prefs.data:
        for pref in null_prefs.data:
            # Set default values
            client.table("course_time_preferences").update({
                "personal_hours_per_week": 5,  # Default
                "group_hours_per_week": 4      # Default
            }).eq("id", pref["id"]).execute()
        
        print(f"   ✅ Set defaults for {len(null_prefs.data)} records")
    else:
        print("   ℹ️ No records with NULL hours")
        
except Exception as e:
    print(f"   ⚠️ Error setting defaults: {e}")

print("\n" + "=" * 60)
print("✅ Migration completed!")

