-- Strict Course Number Enforcement & Foreign Keys
-- This script ensures all course-related tables use course_number as a foreign key to course_catalog.

-- 1) Ensure course_catalog has a unique constraint on course_number (it should already have it)
-- ALTER TABLE course_catalog ADD CONSTRAINT course_catalog_course_number_key UNIQUE (course_number);

-- 2) Update 'courses' table (User's registered courses)
-- First, ensure course_number is not null and clean up orphans if any
-- (Ideally, we would delete courses not in catalog, but we'll let the user decide)
ALTER TABLE courses
    ADD CONSTRAINT courses_course_number_fkey 
    FOREIGN KEY (course_number) 
    REFERENCES course_catalog(course_number) 
    ON DELETE CASCADE;

-- 3) Update 'weekly_plan_blocks'
ALTER TABLE weekly_plan_blocks
    ADD CONSTRAINT weekly_plan_blocks_course_number_fkey 
    FOREIGN KEY (course_number) 
    REFERENCES course_catalog(course_number) 
    ON DELETE CASCADE;

-- 4) Update 'group_plan_blocks'
ALTER TABLE group_plan_blocks
    ADD CONSTRAINT group_plan_blocks_course_number_fkey 
    FOREIGN KEY (course_number) 
    REFERENCES course_catalog(course_number) 
    ON DELETE CASCADE;

-- 5) Update 'course_time_preferences'
ALTER TABLE course_time_preferences
    ADD CONSTRAINT course_time_preferences_course_number_fkey 
    FOREIGN KEY (course_number) 
    REFERENCES course_catalog(course_number) 
    ON DELETE CASCADE;

-- 6) Update 'study_groups'
-- Migration: if course_id is currently a UUID (pointing to course_catalog.id), change it to course_number
-- This ensures hermeticity by using the same human-readable ID everywhere.

-- First, ensure all course_id values that are UUIDs are converted to course_number
UPDATE study_groups sg
SET course_id = c.course_number
FROM course_catalog c
WHERE sg.course_id::text = c.id::text;

ALTER TABLE study_groups
    ADD CONSTRAINT study_groups_course_id_fkey 
    FOREIGN KEY (course_id) 
    REFERENCES course_catalog(course_number) 
    ON DELETE CASCADE;

-- 7) Update 'assignments'
-- If it uses course_catalog_id (UUID), that's also hermetic, but let's add course_number link if needed.
-- For now, the user wants consistent course numbers.
ALTER TABLE assignments
    ADD COLUMN IF NOT EXISTS course_number TEXT;

-- Update course_number from course_catalog_id
UPDATE assignments a
SET course_number = c.course_number
FROM course_catalog c
WHERE a.course_catalog_id = c.id
AND a.course_number IS NULL;

ALTER TABLE assignments
    ADD CONSTRAINT assignments_course_number_fkey 
    FOREIGN KEY (course_number) 
    REFERENCES course_catalog(course_number) 
    ON DELETE CASCADE;

