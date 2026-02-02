# הוראות מיגרציה - מעבר מ-Ratios ל-Hours

## שלב 1: הרצת SQL ב-Supabase

1. פתח את Supabase Dashboard
2. לך ל-SQL Editor
3. העתק והרץ את התוכן של `MIGRATE_TO_HOURS_INSTEAD_OF_RATIOS.sql`

זה יוסיף את השדות:
- `personal_hours_per_week` (INTEGER)
- `group_hours_per_week` (INTEGER)

ויעדכן את הנתונים הקיימים.

## שלב 2: הרצת סקריפט Python לעדכון נתונים

לאחר שהרצת את ה-SQL, הרץ:

```bash
py run_full_migration.py
```

זה יעדכן את כל הרשומות הקיימות.

## שלב 3: אימות

בדוק ב-Supabase שהנתונים עודכנו נכון.

## שלב 4: (אופציונלי) מחיקת שדות ישנים

לאחר אימות, תוכל למחוק את השדות הישנים:

```sql
ALTER TABLE course_time_preferences DROP COLUMN IF EXISTS personal_ratio;
ALTER TABLE course_time_preferences DROP COLUMN IF EXISTS group_ratio;
```

