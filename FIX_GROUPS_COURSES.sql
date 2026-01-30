-- Fix groups to match courses by course_number
-- Run this in Supabase SQL Editor

-- 1. First, let's see what we have:
SELECT 
    g.id as group_id,
    g.group_name,
    g.course_id as group_course_id,
    g.course_name as group_course_name,
    c.id as course_id,
    c.course_name,
    c.course_number,
    CASE 
        WHEN g.course_id = c.course_number::text THEN '✅ MATCH'
        WHEN g.course_id = c.id::text THEN '⚠️ MATCH by UUID (WRONG)'
        WHEN g.course_name = c.course_name THEN '⚠️ MATCH by name (WRONG)'
        ELSE '❌ NO MATCH'
    END as match_status
FROM study_groups g
LEFT JOIN courses c ON (
    g.course_id = c.course_number::text 
    OR g.course_id = c.id::text
    OR g.course_name = c.course_name
)
WHERE g.created_by = '56a2597d-62fc-49b3-9f98-1b852941b5ef'  -- Replace with your user_id
ORDER BY g.group_name;

-- 2. Update groups to use course_number from matching course:
UPDATE study_groups g
SET course_id = c.course_number::text
FROM courses c
WHERE c.course_name = g.course_name 
  AND c.user_id = '56a2597d-62fc-49b3-9f98-1b852941b5ef'  -- Replace with your user_id
  AND g.course_id != c.course_number::text
  AND c.course_number IS NOT NULL;

-- 3. Also update groups that have UUID in course_id to use course_number:
UPDATE study_groups g
SET course_id = c.course_number::text
FROM courses c
WHERE g.course_id = c.id::text
  AND c.user_id = '56a2597d-62fc-49b3-9f98-1b852941b5ef'  -- Replace with your user_id
  AND g.course_id != c.course_number::text
  AND c.course_number IS NOT NULL;

-- 4. Verify the fix:
SELECT 
    g.id as group_id,
    g.group_name,
    g.course_id as group_course_id,
    g.course_name as group_course_name,
    c.course_number,
    CASE 
        WHEN g.course_id = c.course_number::text THEN '✅ MATCH'
        ELSE '❌ NO MATCH'
    END as match_status
FROM study_groups g
LEFT JOIN courses c ON g.course_id = c.course_number::text
WHERE g.created_by = '56a2597d-62fc-49b3-9f98-1b852941b5ef'  -- Replace with your user_id
ORDER BY g.group_name;


