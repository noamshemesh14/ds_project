-- =====================================================
-- USER PREFERENCES SETUP
-- =====================================================
-- Adds study preference columns to user_profiles table
-- for LLM-based schedule refinement

-- 1. Add raw user preferences column (what user writes about themselves)
ALTER TABLE user_profiles 
ADD COLUMN IF NOT EXISTS study_preferences_raw TEXT;

-- 2. Add LLM-extracted structured preferences (JSON format, hidden from user)
ALTER TABLE user_profiles 
ADD COLUMN IF NOT EXISTS study_preferences_summary JSONB;

-- 3. Add comment for documentation
COMMENT ON COLUMN user_profiles.study_preferences_raw IS 'Free-text user input about study preferences, habits, and scheduling preferences';
COMMENT ON COLUMN user_profiles.study_preferences_summary IS 'LLM-extracted structured preferences (JSON): preferred_hours, preferred_days, session_length, break_duration, intensity, per_course_notes';

-- Example structure for study_preferences_summary:
-- {
--   "preferred_hours": ["09:00-12:00", "14:00-17:00"],
--   "preferred_days": ["Sunday", "Monday", "Tuesday", "Wednesday"],
--   "session_length_minutes": 60,
--   "break_duration_minutes": 15,
--   "intensity": "spread",  // or "concentrated"
--   "per_course_preferences": {
--     "10401": {
--       "notes": "Prefer morning study",
--       "min_session_length": 90
--     }
--   },
--   "additional_notes": "Works best in mornings, needs breaks every hour"
-- }

-- Done! Run this in Supabase SQL Editor

