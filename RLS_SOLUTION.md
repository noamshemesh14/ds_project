# RLS (Row Level Security) Solution

## The Issue
When using Supabase with RLS enabled, the backend needs to either:
1. Use `service_role` key (bypasses RLS) - **Recommended for backend**
2. Use `anon` key with user's JWT token (RLS enforced)

## Recommended Solution: Use service_role Key

Since we're already authenticating users via `get_current_user`, it's safe to use the `service_role` key for backend operations. This bypasses RLS, but we've already verified the user's identity.

### Steps:
1. Get your `service_role` key from Supabase Dashboard > Settings > API
2. Add it to your `.env` file:
   ```
   SUPABASE_SERVICE_ROLE_KEY=your_service_role_key_here
   ```
3. The code will automatically use it if available

### Alternative: Use anon key with RLS
If you prefer to use RLS (more secure but more complex):
- The code will fall back to using the `anon` key
- Make sure your RLS policies in Supabase are correctly configured
- Policies should allow users to access only their own data (see SUPABASE_SETUP.md)

## Current Implementation
The code uses `supabase_admin` (service_role) if available, otherwise falls back to `supabase` (anon key).




