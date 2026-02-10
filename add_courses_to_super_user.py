"""
Script to add courses to the super user (CLI user)
Adds the courses from the image to the super user
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

# Super user ID (from auth.py)
SUPER_USER_ID = "56a2597d-62fc-49b3-9f98-1b852941b5ef"

# Create admin client (bypasses RLS)
client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Courses from the image
courses_to_add = [
    {
        "course_number": "10413",
        "course_name": "נושאים נבחרים בהנדסת נתונים",
        "credit_points": 3
    },
    {
        "course_number": "10412",
        "course_name": "מעבדה באיסוף וניהול נתונים",
        "credit_points": 3
    },
    {
        "course_number": "10406",
        "course_name": "רשתות מחשבים",
        "credit_points": 3
    },
    {
        "course_number": "10407",
        "course_name": "מערכות הפעלה",
        "credit_points": 4
    },
    {
        "course_number": "10411",
        "course_name": "מערכות נבונות אינטראקטיביות",
        "credit_points": 3
    }
]

print("🔄 Adding courses to super user...")
print("=" * 60)
print(f"Super User ID: {SUPER_USER_ID}")
print(f"Number of courses to add: {len(courses_to_add)}")
print("=" * 60)

# Check if user exists
try:
    user_result = client.table("user_profiles").select("id").eq("id", SUPER_USER_ID).limit(1).execute()
    if not user_result.data:
        print(f"❌ Error: User {SUPER_USER_ID} not found in user_profiles")
        print("   Please make sure the user exists before adding courses")
        sys.exit(1)
    print(f"✅ User found in user_profiles")
except Exception as e:
    print(f"❌ Error checking user: {e}")
    sys.exit(1)

# Add each course
added_count = 0
skipped_count = 0
error_count = 0

for idx, course_data in enumerate(courses_to_add, 1):
    course_number = course_data["course_number"]
    course_name = course_data["course_name"]
    credit_points = course_data["credit_points"]
    
    try:
        # Check if course exists in catalog
        catalog_result = client.table("course_catalog").select("*").eq("course_number", course_number).limit(1).execute()
        
        if not catalog_result.data:
            print(f"   ⚠️ Course {course_number} not found in catalog, will add anyway")
            catalog_course_name = course_name
            catalog_credit_points = credit_points
        else:
            catalog_course_name = catalog_result.data[0].get("course_name", course_name)
            catalog_credit_points = catalog_result.data[0].get("credit_points", credit_points)
            # Use catalog credit points if available
            if catalog_credit_points:
                credit_points = catalog_credit_points
        
        # Check if user already has this course
        existing_course = client.table("courses").select("*").eq("user_id", SUPER_USER_ID).eq("course_number", course_number).execute()
        
        if existing_course.data and len(existing_course.data) > 0:
            print(f"   ⚠️ Course {course_number} ({course_name}) already exists, skipping")
            skipped_count += 1
            continue
        
        # Add course
        course_insert_data = {
            "user_id": SUPER_USER_ID,
            "course_number": course_number,
            "course_name": catalog_course_name,
            "credit_points": credit_points,
            "semester": "חורף",
            "year": 2026,
            "is_passed": False,
            "retake_count": 0
        }
        
        result = client.table("courses").insert(course_insert_data).execute()
        
        if result.data:
            added_count += 1
            print(f"   ✅ [{idx}/{len(courses_to_add)}] Added: {course_number} - {catalog_course_name} ({credit_points} credit points)")
            
            # Create course_time_preferences entry
            try:
                total_hours = credit_points * 3
                default_personal_hours = max(1, int(total_hours * 0.5))  # 50% personal
                default_group_hours = max(1, total_hours - default_personal_hours)  # 50% group
                
                client.table("course_time_preferences").upsert({
                    "user_id": SUPER_USER_ID,
                    "course_number": course_number,
                    "personal_hours_per_week": default_personal_hours,
                    "group_hours_per_week": default_group_hours
                }, on_conflict="user_id,course_number").execute()
                
                print(f"      ✅ Created course_time_preferences: {default_personal_hours}h personal, {default_group_hours}h group")
            except Exception as pref_err:
                print(f"      ⚠️ Could not create course_time_preferences: {pref_err}")
        else:
            print(f"   ❌ Failed to add course {course_number}")
            error_count += 1
            
    except Exception as e:
        error_count += 1
        print(f"   ❌ Error adding course {course_number}: {str(e)[:100]}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 60)
print("📊 Summary:")
print(f"   ✅ Successfully added: {added_count} courses")
print(f"   ⚠️ Skipped (already exist): {skipped_count} courses")
print(f"   ❌ Errors: {error_count} courses")
print(f"   📝 Total processed: {len(courses_to_add)} courses")
print("\n✅ Script completed!")

