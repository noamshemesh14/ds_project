"""
Script to run SQL migration to add hours columns to course_time_preferences
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

print("🔄 Running SQL migration to add hours columns...")
print("=" * 60)

# Step 1: Add new columns
print("\n1️⃣ Adding new columns...")
try:
    # Use RPC or direct SQL execution
    # Since Supabase Python client doesn't support raw SQL easily, we'll use the REST API
    # But first, let's try to add columns via a simple update that will fail gracefully
    
    # Actually, we need to run this via Supabase SQL Editor or use PostgREST
    # For now, let's create a script that the user can run manually
    print("   ⚠️  SQL migration must be run manually in Supabase SQL Editor")
    print("   Please run the SQL from MIGRATE_TO_HOURS_INSTEAD_OF_RATIOS.sql")
    print("   in your Supabase SQL Editor")
    
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "=" * 60)
print("ℹ️  Please run the SQL migration manually in Supabase SQL Editor")
print("   File: MIGRATE_TO_HOURS_INSTEAD_OF_RATIOS.sql")

