-- =====================================================
-- MIGRATE course_time_preferences FROM INTEGER TO DECIMAL
-- =====================================================
-- This script changes personal_hours_per_week and group_hours_per_week
-- from INTEGER to DECIMAL(5,2) to allow fractional hours for weighted averages
-- When planning, values are rounded to nearest integer
-- =====================================================

-- Step 1: Change column types to DECIMAL
ALTER TABLE course_time_preferences 
    ALTER COLUMN personal_hours_per_week TYPE DECIMAL(5,2) USING personal_hours_per_week::DECIMAL(5,2),
    ALTER COLUMN group_hours_per_week TYPE DECIMAL(5,2) USING group_hours_per_week::DECIMAL(5,2);

-- Step 2: Update default values to DECIMAL
ALTER TABLE course_time_preferences 
    ALTER COLUMN personal_hours_per_week SET DEFAULT 5.0,
    ALTER COLUMN group_hours_per_week SET DEFAULT 4.0;

-- Step 3: Add comment for documentation
COMMENT ON COLUMN course_time_preferences.personal_hours_per_week IS 'Personal study hours per week (DECIMAL to allow weighted averages). Rounded to integer when planning.';
COMMENT ON COLUMN course_time_preferences.group_hours_per_week IS 'Group study hours per week (DECIMAL to allow weighted averages). Rounded to integer when planning.';

-- Done! Run this in Supabase SQL Editor

