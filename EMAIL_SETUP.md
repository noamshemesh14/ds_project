# הגדרת אימיילים ב-Supabase

## הבעיה: לא מקבלים הודעות אימייל

אם לא מקבלים הודעות אימייל לאישור, יש כמה אפשרויות:

## אפשרות 1: השתמש ב-Supabase Email Templates (מומלץ לפיתוח)

### שלבים:

1. **לך ל-Supabase Dashboard:**
   - https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk

2. **פתח Authentication > Email Templates:**
   - בתפריט השמאלי: **Authentication** > **Email Templates**
   - או: https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk/auth/templates

3. **בדוק את ה-Template של "Confirm signup":**
   - תראה את התבנית של הודעת האימייל
   - הקישור לאישור צריך להיות: `{{ .ConfirmationURL }}`

4. **הגדר Redirect URL:**
   - לך ל-**Settings** > **Authentication** > **URL Configuration**
   - ב-**Redirect URLs** הוסף:
     - `http://localhost:8000/auth/confirm`
     - `http://localhost:8000/auth/confirm#access_token=*&type=email`

## אפשרות 2: השבת Email Confirmation (רק לפיתוח!)

**אזהרה:** זה רק לפיתוח! לא מומלץ לפרודקשן.

1. **לך ל-Settings > Authentication:**
   - https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk/auth/providers

2. **כבה "Enable email confirmations":**
   - בטל את הסימון ב-**"Enable email confirmations"**
   - שמור

**זה יגרום לכך שמשתמשים יוכלו להתחבר מיד בלי לאשר אימייל.**

## אפשרות 3: הגדר SMTP מותאם אישית (לפרודקשן)

אם אתה רוצה להשתמש ב-SMTP שלך (Gmail, SendGrid, וכו'):

1. **לך ל-Settings > Auth > SMTP Settings:**
   - https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk/auth/providers

2. **הזן את פרטי ה-SMTP:**
   - Host, Port, Username, Password
   - Sender email

3. **שמור**

## אפשרות 4: בדוק את תיבת הדואר

1. **בדוק את תיקיית הספאם** - לפעמים האימיילים מגיעים לשם
2. **בדוק את כל התיבות** - Gmail, Outlook, וכו'
3. **חכה כמה דקות** - לפעמים יש עיכוב

## אפשרות 5: אישור ידני ב-Supabase Dashboard

אם אתה רוצה לאשר משתמש ידנית:

1. **לך ל-Authentication > Users:**
   - https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk/auth/users

2. **מצא את המשתמש:**
   - לחפש לפי אימייל

3. **לחץ על המשתמש:**
   - תראה את הפרטים שלו

4. **לחץ על "Confirm email"** או "Resend confirmation email"

## בדיקה: האם Email Confirmation מופעל?

1. **לך ל-Settings > Authentication:**
   - https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk/auth/providers

2. **בדוק את "Enable email confirmations":**
   - אם זה מסומן - אימיילים אמורים להישלח
   - אם זה לא מסומן - משתמשים יכולים להתחבר מיד

## למה הנתונים ריקים?

הנתונים ב-`user_profiles` ו-`courses` נשמרים רק כשאתה:
1. **מתחבר** (לא רק נרשם)
2. **מעלה גליון ציונים** או **מזין נתונים ידנית**
3. **לוחץ על "שמור"**

**הרשמה בלבד לא שומרת נתונים!** זה רק יוצר משתמש ב-`auth.users`.

## איפה לראות משתמשים שנרשמו?

1. **לך ל-Authentication > Users:**
   - https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk/auth/users

2. **תראה את כל המשתמשים:**
   - אימייל
   - תאריך הרשמה
   - סטטוס אישור אימייל (`email_confirmed_at`)
   - אם `email_confirmed_at` הוא `null` - האימייל לא אושר

## המלצה לפיתוח:

**השבת Email Confirmation** (אפשרות 2) כדי לפתח מהר יותר, ואז הפעל אותו בפרודקשן.


