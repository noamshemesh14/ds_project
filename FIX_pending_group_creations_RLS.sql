-- ============================================
-- Fix: Add RLS Policies for pending_group_creations
-- ============================================
-- This script adds Row Level Security policies for pending_group_creations
-- Run this in Supabase SQL Editor
-- ============================================

-- Option 1: Enable RLS (if you want to use RLS)
-- Uncomment the line below if you want to enable RLS:
-- ALTER TABLE pending_group_creations ENABLE ROW LEVEL SECURITY;

-- Option 2: Keep RLS disabled (if using service role)
-- If your code uses supabase_admin (service role), RLS can stay disabled
-- The policies below are optional in that case, but won't hurt

-- Policies for pending_group_creations
DROP POLICY IF EXISTS "Users can view their own pending group creations" ON pending_group_creations;
CREATE POLICY "Users can view their own pending group creations"
    ON pending_group_creations FOR SELECT
    USING (inviter_id = auth.uid());

DROP POLICY IF EXISTS "Users can create their own pending group creations" ON pending_group_creations;
CREATE POLICY "Users can create their own pending group creations"
    ON pending_group_creations FOR INSERT
    WITH CHECK (inviter_id = auth.uid());

DROP POLICY IF EXISTS "Users can delete their own pending group creations" ON pending_group_creations;
CREATE POLICY "Users can delete their own pending group creations"
    ON pending_group_creations FOR DELETE
    USING (inviter_id = auth.uid());

-- Also update group_invitations policy to allow NULL group_id
DROP POLICY IF EXISTS "Users can create invitations with NULL group_id" ON group_invitations;
CREATE POLICY "Users can create invitations with NULL group_id"
    ON group_invitations FOR INSERT
    WITH CHECK (inviter_id = auth.uid());



