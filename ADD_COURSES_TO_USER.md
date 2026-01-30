# הוספת קורסים לטבלת courses של המשתמש

**ראה גם:** `ADD_SPECIFIC_COURSES.md` להוספת קורסים ספציפיים

## הוספת קורסים למשתמש ספציפי

הרץ את ה-SQL הזה ב-Supabase SQL Editor כדי להוסיף קורסים לטבלת `courses` של המשתמש:

```sql
-- הוספת קורסים למשתמש ספציפי (החלף את YOUR_USER_ID ב-UUID של המשתמש)
-- כדי למצוא את ה-user_id שלך, הרץ: SELECT id FROM auth.users WHERE email = 'your@email.com';

-- הוספת קורסים למשתמש (רק אם לא קיימים כבר)
INSERT INTO courses (user_id, course_name, course_number, credit_points, semester, year)
SELECT 
    'YOUR_USER_ID'::uuid as user_id,
    cc.course_name,
    cc.course_number,
    cc.credit_points,
    CASE 
        WHEN cc.course_number IN ('10401', '10402') THEN 'חורף'
        WHEN cc.course_number IN ('10403', '10404') THEN 'אביב'
        WHEN cc.course_number IN ('10405', '10406') THEN 'קיץ'
        ELSE 'חורף'
    END as semester,
    EXTRACT(YEAR FROM NOW())::integer as year
FROM course_catalog cc
WHERE NOT EXISTS (
    SELECT 1 FROM courses c 
    WHERE c.user_id = 'YOUR_USER_ID'::uuid 
    AND c.course_number = cc.course_number
)
ON CONFLICT DO NOTHING;
```

## הוספת קורסים לכל המשתמשים

אם אתה רוצה להוסיף קורסים לכל המשתמשים שיש להם פרופיל:

```sql
-- הוספת קורסים לכל המשתמשים (רק אם לא קיימים כבר)
INSERT INTO courses (user_id, course_name, course_number, credit_points, semester, year)
SELECT 
    up.id as user_id,
    cc.course_name,
    cc.course_number,
    cc.credit_points,
    CASE 
        WHEN cc.course_number IN ('10401', '10402') THEN 'חורף'
        WHEN cc.course_number IN ('10403', '10404') THEN 'אביב'
        WHEN cc.course_number IN ('10405', '10406') THEN 'קיץ'
        ELSE 'חורף'
        END as semester,
    EXTRACT(YEAR FROM NOW())::integer as year
FROM course_catalog cc
CROSS JOIN user_profiles up
WHERE NOT EXISTS (
    SELECT 1 FROM courses c 
    WHERE c.user_id = up.id 
    AND c.course_number = cc.course_number
);
```

## הוספת קורסים למשתמש לפי מייל

אם אתה רוצה להוסיף קורסים למשתמש לפי המייל שלו:

```sql
-- החלף 'your@email.com' במייל שלך
WITH user_info AS (
    SELECT id FROM auth.users WHERE email = 'your@email.com'
)
INSERT INTO courses (user_id, course_name, course_number, credit_points, semester, year)
SELECT 
    ui.id as user_id,
    cc.course_name,
    cc.course_number,
    cc.credit_points,
    CASE 
        WHEN cc.course_number IN ('10401', '10402') THEN 'חורף'
        WHEN cc.course_number IN ('10403', '10404') THEN 'אביב'
        WHEN cc.course_number IN ('10405', '10406') THEN 'קיץ'
        ELSE 'חורף'
    END as semester,
    EXTRACT(YEAR FROM NOW())::integer as year
FROM course_catalog cc
CROSS JOIN user_info ui
WHERE NOT EXISTS (
    SELECT 1 FROM courses c 
    WHERE c.user_id = ui.id 
    AND c.course_number = cc.course_number
);
```

## הערות

- הקורסים יוספו רק אם הם לא קיימים כבר למשתמש (בדיקה לפי `course_number`)
- הסמסטר מוגדר לפי מספר הקורס:
  - `10401`, `10402` → חורף
  - `10403`, `10404` → אביב
  - `10405`, `10406` → קיץ
- השנה מוגדרת לשנה הנוכחית
- אתה יכול לשנות את הסמסטרים לפי הצורך

## בדיקה

לאחר הרצת ה-SQL, בדוק שהקורסים נוספו:

```sql
-- בדוק את הקורסים של משתמש ספציפי
SELECT c.*, u.email 
FROM courses c
JOIN user_profiles u ON c.user_id = u.id
WHERE u.email = 'your@email.com'
ORDER BY c.course_number;
```

