-- =====================================================
-- MIGRATE course_time_preferences FROM RATIOS TO HOURS
-- =====================================================
-- This script migrates from personal_ratio/group_ratio
-- to personal_hours_per_week/group_hours_per_week
-- =====================================================

-- Step 1: Add new columns (if they don't exist)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'course_time_preferences' 
        AND column_name = 'personal_hours_per_week'
    ) THEN
        ALTER TABLE course_time_preferences 
        ADD COLUMN personal_hours_per_week INTEGER;
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'course_time_preferences' 
        AND column_name = 'group_hours_per_week'
    ) THEN
        ALTER TABLE course_time_preferences 
        ADD COLUMN group_hours_per_week INTEGER;
    END IF;
END $$;

-- Step 2: Calculate hours from ratios for existing records
-- We need to get credit_points from courses table to calculate total hours
-- Then multiply by ratio to get hours
UPDATE course_time_preferences ctp
SET 
    personal_hours_per_week = COALESCE(
        (SELECT 
            CASE 
                WHEN ctp.personal_ratio IS NOT NULL AND c.credit_points IS NOT NULL 
                THEN GREATEST(1, ROUND((c.credit_points * 3) * ctp.personal_ratio))
                ELSE GREATEST(1, ROUND((3 * 3) * 0.5))  -- Default: 3 credits * 3 = 9 hours, 50% = 4.5 -> 5 hours
            END
         FROM courses c
         WHERE c.user_id = ctp.user_id 
           AND c.course_number = ctp.course_number
         LIMIT 1),
        GREATEST(1, ROUND((3 * 3) * 0.5))  -- Fallback default
    ),
    group_hours_per_week = COALESCE(
        (SELECT 
            CASE 
                WHEN ctp.group_ratio IS NOT NULL AND c.credit_points IS NOT NULL 
                THEN GREATEST(1, ROUND((c.credit_points * 3) * ctp.group_ratio))
                ELSE GREATEST(1, ROUND((3 * 3) * 0.5))  -- Default: 3 credits * 3 = 9 hours, 50% = 4.5 -> 4 hours
            END
         FROM courses c
         WHERE c.user_id = ctp.user_id 
           AND c.course_number = ctp.course_number
         LIMIT 1),
        GREATEST(1, ROUND((3 * 3) * 0.5))  -- Fallback default
    )
WHERE personal_hours_per_week IS NULL OR group_hours_per_week IS NULL;

-- Step 3: Set defaults for any remaining NULL values
UPDATE course_time_preferences
SET 
    personal_hours_per_week = COALESCE(personal_hours_per_week, 5),  -- Default ~50% of 9 hours
    group_hours_per_week = COALESCE(group_hours_per_week, 4)         -- Default ~50% of 9 hours
WHERE personal_hours_per_week IS NULL OR group_hours_per_week IS NULL;

-- Step 4: Make new columns NOT NULL (after setting defaults)
ALTER TABLE course_time_preferences 
ALTER COLUMN personal_hours_per_week SET NOT NULL,
ALTER COLUMN group_hours_per_week SET NOT NULL;

-- Step 5: Set default values for future inserts
ALTER TABLE course_time_preferences 
ALTER COLUMN personal_hours_per_week SET DEFAULT 5,
ALTER COLUMN group_hours_per_week SET DEFAULT 4;

-- Step 6: Drop old ratio columns (after migration is verified)
-- These columns are no longer used - we use hours instead
ALTER TABLE course_time_preferences DROP COLUMN IF EXISTS personal_ratio;
ALTER TABLE course_time_preferences DROP COLUMN IF EXISTS group_ratio;

-- Log migration results
DO $$
DECLARE
    updated_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO updated_count 
    FROM course_time_preferences 
    WHERE personal_hours_per_week IS NOT NULL AND group_hours_per_week IS NOT NULL;
    
    RAISE NOTICE 'Migration completed: % records updated with hours', updated_count;
END $$;

