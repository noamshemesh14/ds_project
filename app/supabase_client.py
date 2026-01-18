"""
Supabase client configuration
"""
import os
from typing import Optional
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ncvchkyncwdeysqzkssk.supabase.co")
# Use anon/public key (publishable) - safe for backend when used with RLS
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
# Optional: service_role key for admin operations (keep secret!)
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

if not SUPABASE_ANON_KEY:
    raise ValueError("SUPABASE_ANON_KEY environment variable is required")

# Client with anon key (for normal operations with RLS)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# Optional: Admin client with service_role key (for operations that bypass RLS)
supabase_admin: Optional[Client] = None
if SUPABASE_SERVICE_ROLE_KEY:
    supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

