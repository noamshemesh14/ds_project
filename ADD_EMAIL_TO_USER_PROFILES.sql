-- Add email column to user_profiles table if it doesn't exist
-- This is needed for creating minimal user profiles after authentication

DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'user_profiles' AND column_name = 'email'
    ) THEN
        ALTER TABLE user_profiles ADD COLUMN email TEXT;
        RAISE NOTICE 'Added email column to user_profiles table';
    ELSE
        RAISE NOTICE 'email column already exists in user_profiles table';
    END IF;
END $$;

-- Optional: Update existing records with email from auth.users
-- This will populate email for existing users
UPDATE user_profiles up
SET email = au.email
FROM auth.users au
WHERE up.id = au.id 
  AND up.email IS NULL;

