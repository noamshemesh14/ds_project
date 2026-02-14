-- ============================================
-- Fix: Make group_id nullable in group_invitations
-- ============================================
-- This allows creating invitations before the group exists
-- Run this in Supabase SQL Editor
-- ============================================

-- Step 1: Drop the NOT NULL constraint on group_id
ALTER TABLE group_invitations 
ALTER COLUMN group_id DROP NOT NULL;

-- Step 2: Verify the change
-- Run this to check if the constraint was removed:
-- SELECT column_name, is_nullable 
-- FROM information_schema.columns 
-- WHERE table_name = 'group_invitations' AND column_name = 'group_id';
-- 
-- Expected result: is_nullable = 'YES'

