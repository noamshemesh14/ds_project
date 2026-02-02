-- =====================================================
-- SYNC GROUP HOURS TO MEMBERS
-- =====================================================
-- This script syncs group_preferences.preferred_hours_per_week
-- to course_time_preferences.group_hours_per_week for all members
-- =====================================================

-- Update course_time_preferences.group_hours_per_week for all members
-- based on their group's preferred_hours_per_week
UPDATE course_time_preferences ctp
SET group_hours_per_week = (
    SELECT gp.preferred_hours_per_week
    FROM group_preferences gp
    JOIN study_groups sg ON sg.id = gp.group_id
    JOIN group_members gm ON gm.group_id = sg.id
    WHERE gm.user_id = ctp.user_id
      AND gm.status = 'approved'
      AND sg.course_id = ctp.course_number
    LIMIT 1
)
WHERE EXISTS (
    SELECT 1
    FROM group_preferences gp
    JOIN study_groups sg ON sg.id = gp.group_id
    JOIN group_members gm ON gm.group_id = sg.id
    WHERE gm.user_id = ctp.user_id
      AND gm.status = 'approved'
      AND sg.course_id = ctp.course_number
);

-- Log how many were updated
DO $$
DECLARE
    updated_count INTEGER;
BEGIN
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE 'Synced group hours to % course_time_preferences records', updated_count;
END $$;

