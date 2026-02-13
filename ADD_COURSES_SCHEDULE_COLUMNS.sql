-- Add lecture/tutorial schedule columns to courses table so profile-edited hours persist.
-- Run this in Supabase SQL Editor if you get errors when saving courses from profile.
ALTER TABLE courses ADD COLUMN IF NOT EXISTS lecture_day text;
ALTER TABLE courses ADD COLUMN IF NOT EXISTS lecture_time text;
ALTER TABLE courses ADD COLUMN IF NOT EXISTS tutorial_day text;
ALTER TABLE courses ADD COLUMN IF NOT EXISTS tutorial_time text;
