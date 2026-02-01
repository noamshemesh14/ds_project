-- Check what's in course_id of groups vs course_number of courses
-- Run this in Supabase SQL Editor

-- 1. Check all groups and their course_id
SELECT 
    id,
    group_name,
    course_id,
    course_name,
    created_by
FROM study_groups
ORDER BY created_at DESC;

-- 2. Check all courses and their course_number
SELECT 
    id,
    course_name,
    course_number,
    semester,
    year
FROM courses
WHERE user_id = '56a2597d-62fc-49b3-9f98-1b852941b5ef'  -- Replace with your user_id
ORDER BY course_number;

-- 3. Check if there's a match between groups and courses
SELECT 
    g.id as group_id,
    g.group_name,
    g.course_id as group_course_id,
    g.course_name as group_course_name,
    c.id as course_id,
    c.course_name,
    c.course_number,
    CASE 
        WHEN g.course_id = c.course_number THEN 'MATCH by course_number'
        WHEN g.course_id = c.id::text THEN 'MATCH by course.id'
        WHEN g.course_name = c.course_name THEN 'MATCH by course_name (WRONG!)'
        ELSE 'NO MATCH'
    END as match_status
FROM study_groups g
CROSS JOIN courses c
WHERE c.user_id = '56a2597d-62fc-49b3-9f98-1b852941b5ef'  -- Replace with your user_id
ORDER BY g.group_name, c.course_name;



