"""
Full migration script: Add columns and migrate data from ratios to hours
This script uses Supabase REST API to execute SQL via RPC (if available)
or provides instructions for manual execution
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
    sys.exit(1)

# Create admin client
client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

print("🔄 Starting full migration from ratios to hours...")
print("=" * 60)

# Step 1: Check if columns exist, if not, instruct user to run SQL first
print("\n1️⃣ Checking if columns exist...")
try:
    # Try to select the new columns - if they don't exist, this will fail
    test_result = client.table("course_time_preferences").select("personal_hours_per_week").limit(1).execute()
    print("   ✅ Columns exist, proceeding with data migration...")
    columns_exist = True
except Exception as e:
    error_msg = str(e)
    if "column" in error_msg.lower() and ("does not exist" in error_msg.lower() or "not found" in error_msg.lower()):
        print("   ❌ Columns don't exist yet!")
        print("\n   📝 Please run MIGRATE_TO_HOURS_INSTEAD_OF_RATIOS.sql in Supabase SQL Editor first.")
        print("   Then run this script again to migrate the data.")
        sys.exit(1)
    else:
        # Columns might exist, continue
        columns_exist = True
        print("   ✅ Proceeding with data migration...")

# Step 2: Migrate existing data
print("\n2️⃣ Migrating existing data from ratios to hours...")
try:
    # Get all course_time_preferences with ratios
    prefs_result = client.table("course_time_preferences").select("*").execute()
    all_prefs = prefs_result.data or []
    print(f"   Found {len(all_prefs)} course_time_preferences records")
    
    updated_count = 0
    skipped_count = 0
    
    for pref in all_prefs:
        user_id = pref.get("user_id")
        course_number = pref.get("course_number")
        personal_ratio = pref.get("personal_ratio")
        group_ratio = pref.get("group_ratio")
        
        # Skip if already has hours
        if pref.get("personal_hours_per_week") is not None:
            skipped_count += 1
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
            error_msg = str(e)
            if "column" in error_msg.lower() and "does not exist" in error_msg.lower():
                print(f"   ❌ Columns don't exist yet! Please run MIGRATE_TO_HOURS_INSTEAD_OF_RATIOS.sql first")
                sys.exit(1)
            print(f"   ⚠️ Error updating {course_number} for user {user_id}: {error_msg[:100]}")
    
    print(f"   ✅ Updated {updated_count} records with hours")
    print(f"   ℹ️  Skipped {skipped_count} records (already have hours)")
    
except Exception as e:
    print(f"   ❌ Error during migration: {e}")
    import traceback
    traceback.print_exc()

# Step 3: Set defaults for any remaining NULL values
print("\n3️⃣ Setting defaults for any remaining NULL values...")
try:
    # Get records with NULL hours
    null_prefs = client.table("course_time_preferences").select("id, user_id, course_number").is_("personal_hours_per_week", "null").limit(100).execute()
    
    if null_prefs.data:
        for pref in null_prefs.data:
            # Get course to calculate proper defaults
            course_result = client.table("courses").select("credit_points").eq("user_id", pref["user_id"]).eq("course_number", pref["course_number"]).limit(1).execute()
            credit_points = course_result.data[0].get("credit_points") if course_result.data else 3
            total_hours = credit_points * 3
            default_personal = max(1, int(total_hours * 0.5))
            default_group = max(1, total_hours - default_personal)
            
            try:
                client.table("course_time_preferences").update({
                    "personal_hours_per_week": default_personal,
                    "group_hours_per_week": default_group
                }).eq("id", pref["id"]).execute()
            except Exception as e:
                print(f"   ⚠️ Error setting defaults for {pref['course_number']}: {str(e)[:100]}")
        
        print(f"   ✅ Set defaults for {len(null_prefs.data)} records")
    else:
        print("   ℹ️ No records with NULL hours")
        
except Exception as e:
    print(f"   ⚠️ Error setting defaults: {e}")

print("\n" + "=" * 60)
print("✅ Data migration completed!")
print("\n📝 Next steps:")
print("   1. Verify the migration in Supabase")
print("   2. After verification, you can drop the old ratio columns:")
print("      ALTER TABLE course_time_preferences DROP COLUMN IF EXISTS personal_ratio;")
print("      ALTER TABLE course_time_preferences DROP COLUMN IF EXISTS group_ratio;")

