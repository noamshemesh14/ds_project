-- Simple fix: Update all groups to use course_number from matching course
-- Run this in Supabase SQL Editor

-- Replace 'YOUR_USER_ID' with your actual user_id from auth.users
-- To find your user_id: SELECT id, email FROM auth.users WHERE email = 'your@email.com';

-- Step 1: Show current state
SELECT 
    g.id as group_id,
    g.group_name,
    g.course_id as current_course_id,
    g.course_name,
    c.course_number as matching_course_number
FROM study_groups g
LEFT JOIN courses c ON (
    c.course_name = g.course_name 
    AND c.user_id = 'YOUR_USER_ID'::uuid
)
WHERE g.created_by = 'YOUR_USER_ID'::uuid
ORDER BY g.group_name;

-- Step 2: Update groups to use course_number
-- This will match groups to courses by course_name and update course_id to course_number
UPDATE study_groups g
SET course_id = c.course_number::text
FROM courses c
WHERE c.course_name = g.course_name 
  AND c.user_id = 'YOUR_USER_ID'::uuid
  AND c.course_number IS NOT NULL
  AND g.created_by = 'YOUR_USER_ID'::uuid;

-- Step 3: Verify the update
SELECT 
    g.id as group_id,
    g.group_name,
    g.course_id as group_course_id,
    g.course_name,
    c.course_number,
    CASE 
        WHEN g.course_id = c.course_number::text THEN '✅ MATCH'
        ELSE '❌ NO MATCH'
    END as match_status
FROM study_groups g
LEFT JOIN courses c ON (
    g.course_id = c.course_number::text
    AND c.user_id = 'YOUR_USER_ID'::uuid
)
WHERE g.created_by = 'YOUR_USER_ID'::uuid
ORDER BY g.group_name;


