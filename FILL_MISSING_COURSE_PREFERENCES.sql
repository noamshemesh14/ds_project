-- =====================================================
-- FILL MISSING COURSE PREFERENCES
-- =====================================================
-- This script fills course_time_preferences for existing courses
-- that don't have preferences yet (created before the auto-creation feature)
-- =====================================================

-- Insert course_time_preferences for all courses that don't have preferences yet
INSERT INTO course_time_preferences (user_id, course_number, personal_ratio, group_ratio)
SELECT DISTINCT
    c.user_id,
    c.course_number,
    0.5 AS personal_ratio,  -- Default 50/50 split
    0.5 AS group_ratio      -- Default 50/50 split
FROM courses c
WHERE c.course_number IS NOT NULL
  AND c.course_number != ''
  AND NOT EXISTS (
      SELECT 1
      FROM course_time_preferences ctp
      WHERE ctp.user_id = c.user_id
        AND ctp.course_number = c.course_number
  )
ON CONFLICT (user_id, course_number) DO NOTHING;

-- Log how many were created
DO $$
DECLARE
    inserted_count INTEGER;
BEGIN
    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    RAISE NOTICE 'Created course_time_preferences for % existing courses', inserted_count;
END $$;

-- =====================================================
-- FILL MISSING GROUP PREFERENCES
-- =====================================================
-- This script fills group_preferences for existing groups
-- that don't have preferences yet (created before the auto-creation feature)
-- =====================================================

-- Insert group_preferences for all groups that don't have preferences yet
INSERT INTO group_preferences (group_id, preferred_hours_per_week, hours_change_history)
SELECT DISTINCT
    sg.id AS group_id,
    4 AS preferred_hours_per_week,  -- Default 4 hours per week
    '[]'::jsonb AS hours_change_history
FROM study_groups sg
WHERE NOT EXISTS (
      SELECT 1
      FROM group_preferences gp
      WHERE gp.group_id = sg.id
  )
ON CONFLICT (group_id) DO NOTHING;

-- Log how many were created
DO $$
DECLARE
    inserted_count INTEGER;
BEGIN
    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    RAISE NOTICE 'Created group_preferences for % existing groups', inserted_count;
END $$;

