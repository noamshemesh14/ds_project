# איפה המשתמשים נשמרים?

## חשוב להבין:

**המשתמשים נשמרים ב-Supabase, לא לוקלית!** אבל יש שני מקומות שונים:

## 1. משתמשים שנרשמו (Authentication) - `auth.users`

כשאתה נרשם, המשתמש נשמר ב-**`auth.users`** ב-Supabase (זו טבלה מובנית).

### איפה לראות אותם:

1. **לך ל-Supabase Dashboard:**
   - https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk

2. **פתח Authentication > Users:**
   - בתפריט השמאלי: **Authentication** > **Users**
   - או ישירות: https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk/auth/users

3. **תראה את כל המשתמשים שנרשמו:**
   - אימייל
   - תאריך הרשמה
   - סטטוס אישור אימייל
   - UUID (מזהה ייחודי)

**זו הטבלה שצריכה להכיל את כל המשתמשים שנרשמו!**

## 2. פרופילי משתמשים (User Profiles) - `user_profiles`

הטבלה `user_profiles` נשמרת רק כשאתה:
1. **מתחבר** (לא רק נרשם)
2. **שומר נתונים** (מעלה גליון ציונים ולוחץ "שמור")

### איפה לראות אותם:

1. **לך ל-Table Editor:**
   - https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk/editor

2. **בחר את הטבלה `user_profiles`**

3. **תראה רק משתמשים ששמרו נתונים**

## למה הטבלה `user_profiles` ריקה?

**זה נורמלי!** הטבלה `user_profiles` תהיה ריקה עד שמישהו:
1. נרשם
2. מתחבר
3. מעלה גליון ציונים או מזין נתונים
4. לוחץ על "שמור"

רק אז הנתונים נשמרים ב-`user_profiles` ו-`courses`.

## איך לבדוק שהכל עובד:

### שלב 1: בדוק אם המשתמש נרשם
1. לך ל: **Authentication > Users**
2. חפש את האימייל שלך
3. אם אתה רואה אותו - ההרשמה עבדה! ✅

### שלב 2: בדוק אם המשתמש יכול להתחבר
1. לך ל: `http://localhost:8000/login`
2. נסה להתחבר
3. אם זה עובד - הכל תקין! ✅

### שלב 3: שמור נתונים
1. אחרי התחברות, לך ל: `/semester` או `/transcript`
2. העלה גליון ציונים
3. לחץ "שמור"
4. עכשיו לך ל-Table Editor > `user_profiles` - תראה את הנתונים! ✅

## בדיקה מהירה - האם Supabase עובד?

### בדוק את ה-Logs:

1. **פתח את הקונסול של השרת** (איפה שהרצת `py run_server.py`)
2. **נסה להירשם שוב**
3. **תראה הודעות כמו:**
   ```
   Signup attempt for your@email.com: user_id=xxx, confirmed=False, has_session=False
   ```

אם אתה רואה את זה - ההרשמה עובדת!

### בדוק את Supabase Logs:

1. **לך ל-Supabase Dashboard > Logs:**
   - https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk/logs

2. **בחר "Auth Logs"**
3. **תראה את כל פעולות ההרשמה וההתחברות**

## בעיות נפוצות:

### 1. "הטבלה ריקה" - אבל אתה מסתכל על `user_profiles`
**פתרון:** לך ל-**Authentication > Users** במקום!

### 2. "לא מקבל אימייל"
**פתרון:** ראה את `EMAIL_SETUP.md` - כנראה צריך להגדיר או להשבית Email Confirmation

### 3. "המשתמש לא יכול להתחבר"
**פתרון:** 
- בדוק אם האימייל אושר (ב-Authentication > Users)
- אם לא, השבת Email Confirmation או אשר ידנית

## סיכום:

- ✅ **הרשמה** → נשמר ב-`auth.users` (Authentication > Users)
- ✅ **התחברות** → משתמש ב-`auth.users`
- ✅ **שמירת נתונים** → נשמר ב-`user_profiles` ו-`courses` (Table Editor)

**הכל נשמר ב-Supabase, לא לוקלית!**


