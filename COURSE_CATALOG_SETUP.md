# Course Catalog (קטלוג קורסים) Setup

## יצירת טבלת קטלוג קורסים ב-Supabase

טבלה זו תכיל את כל הקורסים האפשריים במערכת, ללא קשר למשתמשים.

הרץ את ה-SQL הזה ב-Supabase SQL Editor:

```sql
-- Create course_catalog table (כל הקורסים האפשריים במערכת)
CREATE TABLE IF NOT EXISTS course_catalog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_name TEXT NOT NULL,
    course_number TEXT UNIQUE NOT NULL,  -- מספר קורס ייחודי
    credit_points FLOAT,
    faculty TEXT,  -- פקולטה
    department TEXT,  -- מחלקה
    description TEXT,  -- תיאור הקורס
    prerequisites TEXT,  -- קדם-דרישות
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security (כולם יכולים לראות, רק אדמינים יכולים לערוך)
ALTER TABLE course_catalog ENABLE ROW LEVEL SECURITY;

-- RLS Policies - כולם יכולים לראות את הקטלוג
CREATE POLICY "Anyone can view course catalog"
    ON course_catalog FOR SELECT
    USING (true);

-- רק משתמשים מחוברים יכולים להוסיף קורסים (או אפשר להסיר אם רוצים רק אדמינים)
CREATE POLICY "Authenticated users can insert courses"
    ON course_catalog FOR INSERT
    WITH CHECK (auth.uid() IS NOT NULL);

-- רק משתמשים מחוברים יכולים לעדכן
CREATE POLICY "Authenticated users can update courses"
    ON course_catalog FOR UPDATE
    USING (auth.uid() IS NOT NULL);

-- רק משתמשים מחוברים יכולים למחוק
CREATE POLICY "Authenticated users can delete courses"
    ON course_catalog FOR DELETE
    USING (auth.uid() IS NOT NULL);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_course_catalog_course_number ON course_catalog(course_number);
CREATE INDEX IF NOT EXISTS idx_course_catalog_course_name ON course_catalog(course_name);
```

## עדכון טבלת assignments

עכשיו צריך לעדכן את טבלת `assignments` כך שהיא תהיה מקושרת ל-`course_catalog` במקום ל-`courses`:

```sql
-- Drop the old foreign key constraint
ALTER TABLE assignments DROP CONSTRAINT IF EXISTS assignments_course_id_fkey;

-- Add new column (temporarily nullable for migration)
ALTER TABLE assignments 
    DROP COLUMN IF EXISTS course_id,
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

-- Recreate the index
DROP INDEX IF EXISTS idx_assignments_course_id;
CREATE INDEX IF NOT EXISTS idx_assignments_course_catalog_id ON assignments(course_catalog_id);
```

## הוספת קורסים לדוגמה לקטלוג

**חשוב: הרץ את זה כדי שהקורסים יופיעו בדף "הקורסים שלי"!**

```sql
-- הוספת קורסים לדוגמה (אותם קורסים שהיו hardcoded)
INSERT INTO course_catalog (course_name, course_number, credit_points, faculty, department) VALUES
('מבוא למדעי המחשב', '10401', 4, 'מדעי המחשב', 'מדעי המחשב'),
('מבני נתונים', '10402', 5, 'מדעי המחשב', 'מדעי המחשב'),
('אלגוריתמים', '10403', 5, 'מדעי המחשב', 'מדעי המחשב'),
('מסדי נתונים', '10404', 4, 'מדעי המחשב', 'מדעי המחשב'),
('תכנות מונחה עצמים', '10405', 4, 'מדעי המחשב', 'מדעי המחשב'),
('רשתות מחשבים', '10406', 3, 'מדעי המחשב', 'מדעי המחשב'),
('מערכות הפעלה', '10407', 4, 'מדעי המחשב', 'מדעי המחשב'),
('אבטחת מידע', '10408', 3, 'מדעי המחשב', 'מדעי המחשב'),
('בינה מלאכותית', '10409', 4, 'מדעי המחשב', 'מדעי המחשב'),
('תכנות אינטרנט', '10410', 4, 'מדעי המחשב', 'מדעי המחשב')
ON CONFLICT (course_number) DO NOTHING;
```

**הערה:** הסמסטר של כל קורס יילקח מטבלת `courses` של המשתמש (אם יש לו קורסים שם). אם אין, הסמסטר יהיה null והמשתמש יוכל לבחור אותו.

## הערות

- `course_catalog` - טבלה כללית עם כל הקורסים האפשריים
- `assignments.course_catalog_id` - קישור לקורס מהקטלוג
- `assignments.user_id` - קישור למשתמש (כל משתמש יכול ליצור מטלות לכל קורס)
- `course_number` - מספר קורס ייחודי (UNIQUE) - זה המזהה העיקרי

