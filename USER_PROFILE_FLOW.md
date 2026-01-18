# User Profile Flow - זרימת יצירת ועדכון פרופיל משתמש

## סקירה כללית

המערכת יוצרת פרופיל מינימלי אחרי אימות, ומרחיבה אותו כשהמשתמש מעלה גליון ציונים.

## התהליך המלא

### 1. אימות (Authentication) → פרופיל מינימלי

**מתי:** אחרי הרשמה, אישור אימייל, או התחברות

**מה נוצר ב-`user_profiles`:**
```json
{
    "id": "user-uuid",
    "email": "user@example.com",
    "name": "User Name"  // אם קיים
}
```

**איפה זה קורה:**

#### א. אחרי הרשמה (`/api/auth/signup`)
```python
# ds_project/app/main.py - שורה 623-640
if is_new_user:
    # Create minimal user profile
    profile_data = {
        "id": response.user.id,
        "email": response.user.email,
        "name": request.name
    }
    client.table("user_profiles").insert(profile_data).execute()
```

#### ב. אחרי אישור אימייל (`/auth/confirm`)
```python
# ds_project/app/main.py - שורה 224-231
if access_token and token_type == "email":
    # Decode token, get user_id and email
    profile_data = {
        "id": user_id,
        "email": user_email,
        "name": payload.get('user_metadata', {}).get('name')
    }
    client.table("user_profiles").insert(profile_data).execute()
```

#### ג. אחרי התחברות (`/api/auth/signin`)
```python
# ds_project/app/main.py - שורה 699-715
if response.user:
    # Ensure user profile exists
    profile_data = {
        "id": user_id,
        "email": user_email,
        "name": response.user.user_metadata.get('name')
    }
    client.table("user_profiles").insert(profile_data).execute()
```

### 2. העלאת גליון ציונים → עדכון פרופיל

**מתי:** כשהמשתמש מעלה גליון ציונים ולוחץ "שמור"

**מה קורה:**

1. המשתמש מעלה קובץ דרך `/api/upload-transcript`
2. הקובץ מפורש ומחזיר `TranscriptData`
3. המשתמש לוחץ "שמור" → קורא ל-`/api/save-user`
4. `save_user` **מעדכן** את הפרופיל הקיים עם כל הנתונים

**הקוד (`/api/save-user`):**

```python
# ds_project/app/main.py - שורה 285-343

# 1. בודק אם פרופיל קיים
existing_profile = client.table("user_profiles").select("id").eq("id", user_id).execute()
is_update = len(existing_profile.data) > 0

# 2. מכין את כל הנתונים
profile_data = {
    "id": user_id,
    "email": current_user.get('email'),  # שמירה גם בעדכון
    "name": user_data.name,
    "id_number": user_data.id_number,
    "faculty": user_data.faculty,
    "study_track": user_data.study_track,
    "cumulative_average": user_data.cumulative_average,
    "success_rate": user_data.success_rate,
    "current_semester": user_data.current_semester,
    "current_year": user_data.current_year
}

# 3. מעדכן את הפרופיל הקיים
if is_update:
    client.table("user_profiles").update(profile_data).eq("id", user_id).execute()
else:
    # אם לא קיים (לא אמור לקרות, אבל למקרה)
    client.table("user_profiles").insert(profile_data).execute()
```

**מה מתעדכן:**
- ✅ כל השדות הקיימים מתעדכנים
- ✅ שדות חדשים מתווספים
- ✅ `email` נשמר גם בעדכון (למקרה שלא היה)

## דוגמה: תהליך מלא

### שלב 1: הרשמה
```
משתמש נרשם → פרופיל מינימלי נוצר:
{
    "id": "abc-123",
    "email": "user@example.com",
    "name": "John Doe"
}
```

### שלב 2: אישור אימייל
```
משתמש מאשר אימייל → הפרופיל כבר קיים (לא נוצר מחדש)
```

### שלב 3: העלאת גליון ציונים
```
משתמש מעלה גליון → לוחץ "שמור" → הפרופיל מתעדכן:
{
    "id": "abc-123",
    "email": "user@example.com",
    "name": "John Doe",
    "id_number": "123456789",
    "faculty": "מדעי המחשב",
    "study_track": "תוכנה",
    "cumulative_average": 85.5,
    "success_rate": 95.0,
    "current_semester": "2024A",
    "current_year": 2
}
```

## איפה לראות את הנתונים?

### ב-Supabase Dashboard:

1. **Table Editor** > `user_profiles`
   - תראה את כל המשתמשים
   - אחרי אימות: רק `id`, `email`, `name`
   - אחרי העלאת גליון: כל השדות מלאים

2. **Authentication** > **Users**
   - תראה את המשתמשים ב-`auth.users`
   - זה נפרד מ-`user_profiles`

## בדיקה: איך לדעת שהכל עובד?

### 1. בדוק אחרי הרשמה:
```sql
SELECT id, email, name, created_at 
FROM user_profiles 
WHERE email = 'user@example.com';
```

**צריך לראות:**
- `id` - UUID
- `email` - כתובת אימייל
- `name` - שם (אם הוזן)
- `created_at` - תאריך יצירה

### 2. בדוק אחרי העלאת גליון:
```sql
SELECT * 
FROM user_profiles 
WHERE email = 'user@example.com';
```

**צריך לראות:**
- כל השדות מלאים
- `updated_at` - תאריך עדכון אחרון

### 3. בדוק את הלוגים:

**אחרי אימות:**
```
✅ Created minimal user profile for user@example.com
```

**אחרי העלאת גליון:**
```
💾 Saving user data for user_id: abc-123
   Profile exists: True
   Updating existing profile for user abc-123
   Update result: 1 rows updated
✅ Successfully saved user data for abc-123
```

## בעיות נפוצות

### 1. "foreign key constraint" כשמנסים ליצור אילוץ

**סיבה:** הפרופיל המינימלי לא נוצר אחרי אימות

**פתרון:** 
- בדוק שהאימות עבר בהצלחה
- בדוק את הלוגים - צריך לראות "Created minimal user profile"
- אם לא - הפרופיל ייווצר אוטומטית ב-`create_constraint`

### 2. הפרופיל לא מתעדכן אחרי העלאת גליון

**סיבה:** `save_user` לא נקרא או נכשל

**פתרון:**
- בדוק את הלוגים - צריך לראות "Updating existing profile"
- בדוק שהמשתמש מחובר (יש token)
- בדוק שהנתונים נשלחים נכון

### 3. הפרופיל נוצר פעמיים

**סיבה:** המשתמש נרשם/התחבר כמה פעמים

**פתרון:** 
- הקוד בודק אם הפרופיל קיים לפני יצירה
- אם קיים - לא יוצר מחדש
- זה בסדר - לא יקרה duplicate

## סיכום

**התהליך:**
1. ✅ אימות → פרופיל מינימלי (`id`, `email`, `name`)
2. ✅ העלאת גליון → עדכון פרופיל עם כל הנתונים
3. ✅ המשתמש יכול להשתמש בכל הפיצ'רים מיד אחרי אימות

**הכל אוטומטי - המשתמש לא צריך לעשות כלום חוץ מלהתחבר ולהעלות גליון!**

