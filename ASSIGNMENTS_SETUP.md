# Assignments (מטלות) Setup

## ⚠️ חשוב: קודם כל צריך ליצור את טבלת course_catalog

**לפני יצירת טבלת assignments, צריך ליצור את טבלת `course_catalog`!**

ראה את הקובץ `COURSE_CATALOG_SETUP.md` להוראות מפורטות.

## יצירת טבלת מטלות ב-Supabase

הרץ את ה-SQL הזה ב-Supabase SQL Editor (אחרי שיצרת את `course_catalog`):

```sql
-- Create assignments table
CREATE TABLE IF NOT EXISTS assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_catalog_id UUID NOT NULL REFERENCES course_catalog(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    due_date DATE NOT NULL,
    is_completed BOOLEAN DEFAULT FALSE,
    priority TEXT DEFAULT 'medium', -- 'low', 'medium', 'high'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security (כולם יכולים לראות ולערוך)
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_assignments_course_catalog_id ON assignments(course_catalog_id);
CREATE INDEX IF NOT EXISTS idx_assignments_due_date ON assignments(due_date);

-- RLS Policies - כולם יכולים לראות ולערוך מטלות
CREATE POLICY "Anyone can view assignments"
    ON assignments FOR SELECT
    USING (true);

CREATE POLICY "Anyone can insert assignments"
    ON assignments FOR INSERT
    WITH CHECK (true);

CREATE POLICY "Anyone can update assignments"
    ON assignments FOR UPDATE
    USING (true);

CREATE POLICY "Anyone can delete assignments"
    ON assignments FOR DELETE
    USING (true);
```

## הערות

- `course_catalog_id` - קשור לקורס מטבלת `course_catalog` (חובה)
- **אין `user_id`** - המטלות לא קשורות למשתמש ספציפי, הן משותפות לכולם
- `due_date` - תאריך דד-ליין (DATE type)
- `priority` - עדיפות המטלה ('low', 'medium', 'high')
- `is_completed` - האם המטלה הושלמה

## עדכון מטבלה קיימת

אם כבר יצרת את טבלת `assignments` עם `user_id` או `course_id`, הרץ את זה לעדכון:

```sql
-- קודם כל: Drop old RLS policies (חייב למחוק לפני שממחקים את העמודה)
DROP POLICY IF EXISTS "Users can view their own assignments" ON assignments;
DROP POLICY IF EXISTS "Users can insert their own assignments" ON assignments;
DROP POLICY IF EXISTS "Users can update their own assignments" ON assignments;
DROP POLICY IF EXISTS "Users can delete their own assignments" ON assignments;

-- עכשיו אפשר למחוק את ה-foreign key constraints
ALTER TABLE assignments DROP CONSTRAINT IF EXISTS assignments_course_id_fkey;
ALTER TABLE assignments DROP CONSTRAINT IF EXISTS assignments_user_id_fkey;

-- Add new column with NOT NULL constraint (if not exists)
ALTER TABLE assignments 
    ADD COLUMN IF NOT EXISTS course_catalog_id UUID;

-- Migrate data if needed (optional - only if you have existing assignments)
-- UPDATE assignments SET course_catalog_id = (SELECT id FROM course_catalog WHERE course_number = ...) WHERE course_catalog_id IS NULL;

-- After migration, add NOT NULL constraint and foreign key
ALTER TABLE assignments 
    ALTER COLUMN course_catalog_id SET NOT NULL,
    ADD CONSTRAINT assignments_course_catalog_id_fkey 
        FOREIGN KEY (course_catalog_id) 
        REFERENCES course_catalog(id) 
        ON DELETE CASCADE;

-- Drop old columns (only after migration)
-- ALTER TABLE assignments DROP COLUMN IF EXISTS course_id;
ALTER TABLE assignments DROP COLUMN IF EXISTS user_id;

-- Drop old indexes
DROP INDEX IF EXISTS idx_assignments_course_id;
DROP INDEX IF EXISTS idx_assignments_user_id;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_assignments_course_catalog_id ON assignments(course_catalog_id);
CREATE INDEX IF NOT EXISTS idx_assignments_due_date ON assignments(due_date);

-- Add new RLS policies (כולם יכולים לראות ולערוך)
CREATE POLICY "Anyone can view assignments"
    ON assignments FOR SELECT
    USING (true);

CREATE POLICY "Anyone can insert assignments"
    ON assignments FOR INSERT
    WITH CHECK (true);

CREATE POLICY "Anyone can update assignments"
    ON assignments FOR UPDATE
    USING (true);

CREATE POLICY "Anyone can delete assignments"
    ON assignments FOR DELETE
    USING (true);
```
