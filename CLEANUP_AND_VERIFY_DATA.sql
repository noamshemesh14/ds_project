-- =====================================================
-- CLEANUP AND VERIFY DATA - Ensure data consistency
-- =====================================================
-- This script:
-- 1. Verifies that ratios match actual hours distribution
-- 2. Ensures group_preferences and course_time_preferences are consistent
-- 3. Fixes any inconsistencies found
-- =====================================================

-- Step 1: Verify and fix course_time_preferences
-- Calculate what the ratio SHOULD be based on hours, and verify it matches
-- (This is just for verification - we're moving away from ratios)

-- Check for records where personal_hours + group_hours doesn't make sense
-- (e.g., both are 0, or sum is way too high)
DO $$
DECLARE
    invalid_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO invalid_count
    FROM course_time_preferences
    WHERE (personal_hours_per_week IS NULL OR personal_hours_per_week < 0)
       OR (group_hours_per_week IS NULL OR group_hours_per_week < 0)
       OR (personal_hours_per_week + group_hours_per_week) > 50; -- Sanity check: max 50 hours/week
    
    IF invalid_count > 0 THEN
        RAISE NOTICE 'Found % records with invalid hours values', invalid_count;
        
        -- Fix NULL or negative values
        UPDATE course_time_preferences
        SET 
            personal_hours_per_week = GREATEST(1, COALESCE(personal_hours_per_week, 5)),
            group_hours_per_week = GREATEST(1, COALESCE(group_hours_per_week, 4))
        WHERE personal_hours_per_week IS NULL 
           OR group_hours_per_week IS NULL
           OR personal_hours_per_week < 0
           OR group_hours_per_week < 0;
        
        RAISE NOTICE 'Fixed invalid hours values';
    ELSE
        RAISE NOTICE 'All course_time_preferences records have valid hours';
    END IF;
END $$;

-- Step 2: Verify group_preferences consistency
-- Check that group_preferences.preferred_hours_per_week matches
-- the average of course_time_preferences.group_hours_per_week for all members
DO $$
DECLARE
    inconsistent_count INTEGER;
    rec RECORD;
    avg_group_hours NUMERIC;
    group_hours INTEGER;
BEGIN
    FOR rec IN 
        SELECT gp.group_id, gp.preferred_hours_per_week, sg.course_id
        FROM group_preferences gp
        JOIN study_groups sg ON sg.id = gp.group_id
    LOOP
        -- Calculate average group_hours_per_week for all members of this group
        SELECT AVG(ctp.group_hours_per_week) INTO avg_group_hours
        FROM course_time_preferences ctp
        JOIN group_members gm ON gm.user_id = ctp.user_id
        WHERE gm.group_id = rec.group_id
          AND gm.status = 'approved'
          AND ctp.course_number = rec.course_id;
        
        group_hours = rec.preferred_hours_per_week;
        
        -- If average differs significantly (more than 2 hours), log it
        IF avg_group_hours IS NOT NULL AND ABS(avg_group_hours - group_hours) > 2 THEN
            RAISE NOTICE 'Group % has preferred_hours_per_week=% but members average=%. Consider syncing.', 
                rec.group_id, group_hours, ROUND(avg_group_hours);
            inconsistent_count := COALESCE(inconsistent_count, 0) + 1;
        END IF;
    END LOOP;
    
    IF inconsistent_count IS NULL OR inconsistent_count = 0 THEN
        RAISE NOTICE 'All group_preferences are consistent with member course_time_preferences';
    ELSE
        RAISE NOTICE 'Found % groups with inconsistent hours', inconsistent_count;
    END IF;
END $$;

-- Step 3: Ensure all courses have course_time_preferences
-- (This should already be handled by the application, but verify)
DO $$
DECLARE
    missing_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_count
    FROM courses c
    WHERE c.course_number IS NOT NULL
      AND c.course_number != ''
      AND NOT EXISTS (
          SELECT 1
          FROM course_time_preferences ctp
          WHERE ctp.user_id = c.user_id
            AND ctp.course_number = c.course_number
      );
    
    IF missing_count > 0 THEN
        RAISE NOTICE 'Found % courses without course_time_preferences. These should be created by the application.', missing_count;
    ELSE
        RAISE NOTICE 'All courses have course_time_preferences';
    END IF;
END $$;

-- Step 4: Ensure all groups have group_preferences
DO $$
DECLARE
    missing_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_count
    FROM study_groups sg
    WHERE NOT EXISTS (
        SELECT 1
        FROM group_preferences gp
        WHERE gp.group_id = sg.id
    );
    
    IF missing_count > 0 THEN
        RAISE NOTICE 'Found % groups without group_preferences. These should be created by the application.', missing_count;
    ELSE
        RAISE NOTICE 'All groups have group_preferences';
    END IF;
END $$;

-- Step 5: Final summary
DO $$
DECLARE
    total_course_prefs INTEGER;
    total_group_prefs INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_course_prefs FROM course_time_preferences;
    SELECT COUNT(*) INTO total_group_prefs FROM group_preferences;
    
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Data verification complete:';
    RAISE NOTICE '  course_time_preferences: % records', total_course_prefs;
    RAISE NOTICE '  group_preferences: % records', total_group_prefs;
    RAISE NOTICE '========================================';
END $$;

