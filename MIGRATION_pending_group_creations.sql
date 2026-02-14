-- ============================================
-- Migration Script: Handle existing data for pending_group_creations
-- ============================================
-- This script handles existing invitations with NULL group_id
-- that were created before the pending_group_creations table existed
--
-- Run this AFTER creating the pending_group_creations table
-- ============================================

-- Step 1: Find all invitations with NULL group_id (pending groups that weren't created yet)
-- and create pending_group_creations records for them
-- Note: We'll use the inviter's course info to reconstruct the group metadata
-- 
-- IMPORTANT: This finds the common course between the inviter and all their invitees
-- to determine which course the pending group is for

INSERT INTO pending_group_creations (inviter_id, course_id, course_name, group_name, description)
SELECT DISTINCT
    gi.inviter_id,
    c.course_number AS course_id,
    c.course_name,
    -- Use a default group name based on course (since we don't have the original name)
    'Study Group - ' || c.course_name AS group_name,
    NULL AS description  -- We don't have the original description
FROM group_invitations gi
INNER JOIN courses c ON c.user_id = gi.inviter_id
WHERE gi.group_id IS NULL
  AND gi.status = 'pending'
  AND NOT EXISTS (
    -- Don't insert if already exists
    SELECT 1 FROM pending_group_creations pgc
    WHERE pgc.inviter_id = gi.inviter_id
      AND pgc.course_id = c.course_number
  )
  -- Only include courses where at least one invitee also has this course
  -- (to ensure we're matching the right course)
  AND EXISTS (
    SELECT 1 FROM group_invitations gi2
    INNER JOIN courses c2 ON c2.user_id = gi2.invitee_user_id
    WHERE gi2.inviter_id = gi.inviter_id
      AND gi2.group_id IS NULL
      AND gi2.status = 'pending'
      AND c2.course_number = c.course_number
  )
GROUP BY gi.inviter_id, c.course_number, c.course_name
ON CONFLICT (inviter_id, course_id) DO NOTHING;

-- Step 2: Clean up old pending invitations that are expired or rejected
-- (Optional - uncomment if you want to clean up old data)
-- DELETE FROM group_invitations
-- WHERE group_id IS NULL
--   AND status IN ('rejected', 'expired')
--   AND expires_at < NOW() - INTERVAL '30 days';

-- Step 3: Verify the migration
-- Run this to see how many pending_group_creations were created:
-- SELECT COUNT(*) as pending_groups_count FROM pending_group_creations;
-- 
-- Run this to see pending invitations without group_id:
-- SELECT inviter_id, COUNT(*) as pending_invitations
-- FROM group_invitations
-- WHERE group_id IS NULL AND status = 'pending'
-- GROUP BY inviter_id;
