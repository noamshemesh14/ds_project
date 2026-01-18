# Assignments (מטלות) Setup

## יצירת טבלת מטלות ב-Supabase

הרץ את ה-SQL הזה ב-Supabase SQL Editor:

```sql
-- Create assignments table
CREATE TABLE IF NOT EXISTS assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    due_date DATE NOT NULL,
    is_completed BOOLEAN DEFAULT FALSE,
    priority TEXT DEFAULT 'medium', -- 'low', 'medium', 'high'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_assignments_course_id ON assignments(course_id);
CREATE INDEX IF NOT EXISTS idx_assignments_user_id ON assignments(user_id);
CREATE INDEX IF NOT EXISTS idx_assignments_due_date ON assignments(due_date);

-- RLS Policies
-- Users can view their own assignments
CREATE POLICY "Users can view their own assignments"
    ON assignments FOR SELECT
    USING (auth.uid() = user_id);

-- Users can insert their own assignments
CREATE POLICY "Users can insert their own assignments"
    ON assignments FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Users can update their own assignments
CREATE POLICY "Users can update their own assignments"
    ON assignments FOR UPDATE
    USING (auth.uid() = user_id);

-- Users can delete their own assignments
CREATE POLICY "Users can delete their own assignments"
    ON assignments FOR DELETE
    USING (auth.uid() = user_id);
```

## הערות

- `course_id` - קשור לקורס ספציפי
- `user_id` - קשור למשתמש (למקרה של קורסים משותפים)
- `due_date` - תאריך דד-ליין (DATE type)
- `priority` - עדיפות המטלה
- `is_completed` - האם המטלה הושלמה
