-- =====================================================
-- SEMESTER SCHEDULE ITEMS SETUP
-- =====================================================
-- This script creates the semester_schedule_items table
-- for storing fixed lectures, tutorials, and other
-- semester-long schedule items.
-- =====================================================

CREATE TABLE IF NOT EXISTS semester_schedule_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    course_name TEXT NOT NULL,
    type TEXT NOT NULL, -- e.g., 'lecture', 'tutorial', 'lab', 'seminar', 'other'
    days TEXT NOT NULL, -- JSON array of integers (0-6 for Sunday-Saturday)
    start_time TEXT NOT NULL, -- HH:MM
    end_time TEXT NOT NULL,   -- HH:MM
    location TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security
ALTER TABLE semester_schedule_items ENABLE ROW LEVEL SECURITY;

-- RLS Policies
CREATE POLICY "Users can view their own semester schedule items"
    ON semester_schedule_items FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own semester schedule items"
    ON semester_schedule_items FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own semester schedule items"
    ON semester_schedule_items FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own semester schedule items"
    ON semester_schedule_items FOR DELETE
    USING (auth.uid() = user_id);

-- Index for faster queries
CREATE INDEX IF NOT EXISTS semester_schedule_items_user_id_idx 
    ON semester_schedule_items(user_id);

-- =====================================================
-- END OF SEMESTER SCHEDULE SETUP
-- =====================================================


