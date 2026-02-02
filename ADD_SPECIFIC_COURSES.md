# הוספת קורסים ספציפיים

## הוספת הקורסים ל-course_catalog

ראשית, הוסף את הקורסים לקטלוג:

```sql
-- הוספת הקורסים לקטלוג (אם לא קיימים)
INSERT INTO course_catalog (course_name, course_number, credit_points, faculty, department) VALUES
('מערכות נבונות אינטראקטיביות', '10411', 3, 'מדעי המחשב', 'מדעי המחשב'),
('מעבדה באיסוף וניהול נתונים', '10412', 2, 'מדעי המחשב', 'מדעי המחשב'),
('נושאים נבחרים בהנדסת נתונים', '10413', 3, 'מדעי המחשב', 'מדעי המחשב')
ON CONFLICT (course_number) DO NOTHING;
```

## הוספת הקורסים לטבלת courses של המשתמש

### אפשרות 1: לפי מייל

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
    'חורף' as semester,  -- שנה את זה לפי הצורך: 'חורף', 'אביב', 'קיץ'
    EXTRACT(YEAR FROM NOW())::integer as year
FROM course_catalog cc
CROSS JOIN user_info ui
WHERE cc.course_number IN ('10411', '10412', '10413')
AND NOT EXISTS (
    SELECT 1 FROM courses c 
    WHERE c.user_id = ui.id 
    AND c.course_number = cc.course_number
);
```

### אפשרות 2: לפי UUID

```sql
-- החלף 'YOUR_USER_ID' ב-UUID של המשתמש
INSERT INTO courses (user_id, course_name, course_number, credit_points, semester, year)
SELECT 
    'YOUR_USER_ID'::uuid as user_id,
    cc.course_name,
    cc.course_number,
    cc.credit_points,
    'חורף' as semester,  -- שנה את זה לפי הצורך
    EXTRACT(YEAR FROM NOW())::integer as year
FROM course_catalog cc
WHERE cc.course_number IN ('10411', '10412', '10413')
AND NOT EXISTS (
    SELECT 1 FROM courses c 
    WHERE c.user_id = 'YOUR_USER_ID'::uuid 
    AND c.course_number = cc.course_number
);
```

## שינוי פרטים

אם אתה רוצה לשנות:
- **מספר קורס**: שנה את `'10411'`, `'10412'`, `'10413'` לערכים אחרים
- **נקודות זכות**: שנה את `credit_points` ב-`course_catalog` או ב-`courses`
- **סמסטר**: שנה את `'חורף'` ל-`'אביב'` או `'קיץ'`
- **שנה**: שנה את `EXTRACT(YEAR FROM NOW())` לערך אחר

## בדיקה

לאחר הרצת ה-SQL, בדוק שהקורסים נוספו:

```sql
-- בדוק בקטלוג
SELECT * FROM course_catalog WHERE course_number IN ('10411', '10412', '10413');

-- בדוק בקורסים של המשתמש
SELECT c.*, u.email 
FROM courses c
JOIN user_profiles u ON c.user_id = u.id
WHERE c.course_number IN ('10411', '10412', '10413')
ORDER BY c.course_number;
```





