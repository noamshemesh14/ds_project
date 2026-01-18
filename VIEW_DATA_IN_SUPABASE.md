# איך לראות את הנתונים ב-Supabase

## 1. גישה ל-Supabase Dashboard

1. לך ל: https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk
2. התחבר עם החשבון שלך

## 2. צפייה בטבלאות (Table Editor)

### שלבים:

1. **פתח Table Editor:**
   - בתפריט השמאלי לחץ על **"Table Editor"** (אייקון של טבלה)
   - או לך ישירות ל: https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk/editor

2. **בחר טבלה:**
   - תראה רשימה של כל הטבלאות:
     - `user_profiles` - פרופילי המשתמשים
     - `courses` - הקורסים של כל משתמש
     - `constraints` - האילוצים של כל משתמש

3. **צפה בנתונים:**
   - לחץ על שם הטבלה כדי לראות את כל השורות
   - תוכל לראות, לערוך, למחוק ולסנן נתונים

## 3. צפייה במשתמשים (Authentication)

### שלבים:

1. **פתח Authentication:**
   - בתפריט השמאלי לחץ על **"Authentication"** > **"Users"**
   - או לך ישירות ל: https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk/auth/users

2. **מה תראה:**
   - רשימת כל המשתמשים שנרשמו
   - אימייל, תאריך הרשמה, סטטוס אישור אימייל
   - אפשרות לערוך, למחוק, או לאשר אימייל ידנית

## 4. צפייה בנתונים עם SQL Editor

### שלבים:

1. **פתח SQL Editor:**
   - בתפריט השמאלי לחץ על **"SQL Editor"**
   - או לך ישירות ל: https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk/sql/new

2. **הרץ שאילתות:**

```sql
-- לראות את כל המשתמשים עם הפרופילים שלהם
SELECT 
    u.id,
    u.email,
    u.email_confirmed_at,
    p.name,
    p.id_number,
    p.faculty,
    p.study_track,
    p.cumulative_average
FROM auth.users u
LEFT JOIN user_profiles p ON u.id = p.id;

-- לראות את כל הקורסים של משתמש מסוים
SELECT 
    c.*,
    p.name as student_name,
    p.email
FROM courses c
JOIN user_profiles p ON c.user_id = p.id
WHERE p.email = 'your@email.com';

-- לראות את כל האילוצים
SELECT 
    c.*,
    p.name as student_name,
    p.email
FROM constraints c
JOIN user_profiles p ON c.user_id = p.id;

-- סטטיסטיקה - כמה קורסים לכל משתמש
SELECT 
    p.name,
    p.email,
    COUNT(c.id) as courses_count,
    SUM(c.credit_points) as total_credits
FROM user_profiles p
LEFT JOIN courses c ON p.id = c.user_id
GROUP BY p.id, p.name, p.email;
```

## 5. מה נמצא בכל טבלה?

### `user_profiles`
- `id` - מזהה המשתמש (UUID, קשור ל-auth.users)
- `name` - שם המשתמש
- `id_number` - תעודת זהות
- `faculty` - פקולטה
- `study_track` - מסלול לימודים
- `cumulative_average` - ממוצע מצטבר
- `success_rate` - אחוזי הצלחה
- `current_semester` - סמסטר נוכחי
- `current_year` - שנה נוכחית
- `created_at` - תאריך יצירה
- `updated_at` - תאריך עדכון אחרון

### `courses`
- `id` - מזהה הקורס (UUID)
- `user_id` - מזהה המשתמש (קשור ל-user_profiles)
- `course_name` - שם הקורס
- `course_number` - מספר קורס
- `credit_points` - נקודות זכות
- `grade` - ציון
- `letter_grade` - ציון אות
- `semester` - סמסטר
- `year` - שנה
- `notes` - הערות
- `is_passed` - האם עבר
- `retake_count` - מספר פעמים שנלמד מחדש
- `created_at` - תאריך יצירה
- `updated_at` - תאריך עדכון אחרון

### `constraints`
- `id` - מזהה האילוץ (UUID)
- `user_id` - מזהה המשתמש (קשור ל-user_profiles)
- `title` - שם האילוץ
- `description` - תיאור
- `days` - ימים בשבוע (מופרדים בפסיקים)
- `start_time` - שעת התחלה
- `end_time` - שעת סיום
- `created_at` - תאריך יצירה
- `updated_at` - תאריך עדכון אחרון

## 6. טיפים

- **סינון:** תוכל לסנן שורות לפי ערכים ספציפיים
- **עריכה:** לחץ על שורה כדי לערוך אותה
- **מחיקה:** לחץ על כפתור המחיקה (🗑️) כדי למחוק שורה
- **ייצוא:** תוכל לייצא נתונים ל-CSV או JSON

## 7. בדיקת Row Level Security (RLS)

אם אתה רוצה לבדוק שהנתונים מוגנים:
1. לך ל-**"Authentication"** > **"Policies"**
2. תראה את כל ה-Policies שהוגדרו
3. כל משתמש יכול לראות ולערוך רק את הנתונים שלו


