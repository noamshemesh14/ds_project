# Supabase Setup Instructions

## 1. Get Your Supabase Keys

1. Go to your Supabase dashboard: https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk
2. Go to Settings > API
3. Copy:
   - **Project URL**: `https://ncvchkyncwdeysqzkssk.supabase.co`
   - **anon public key**: (the `anon` `public` key)
   - **service_role key**: (optional, for backend operations - keep secret!)

## 2. Create `.env` file

Create a `.env` file in the `ds_project` directory:

```env
SUPABASE_URL=https://ncvchkyncwdeysqzkssk.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5jdmNoa3luY3dkZXlzcXprc3NrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjgzNjg2MzksImV4cCI6MjA4Mzk0NDYzOX0.vtCcTRawzWbdZ7bEIK4sA-F4upGwMAI1HQwu6syLgaM
GEMINI_API_KEY=AIzaSyBq5j_h0Sxep-AxIV0jyliAAv7seiYgx2o
```

**Important**: This is the **anon/public key** (publishable key) - the JWT token format (starts with `eyJ...`). This is the safe key for backend use. The service_role key is optional and should only be used if you need to bypass Row Level Security (RLS).

## 3. Configure Email Confirmation URL

**חשוב:** כדי שהדף שלנו יופיע כשמאשרים אימייל, צריך להגדיר את ה-confirm URL:

1. לך ל-Supabase Dashboard: https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk
2. לך ל-**Settings** > **Authentication** > **URL Configuration**
3. ב-**Site URL** הכנס: `http://localhost:8000` (או ה-URL של השרת שלך)
4. ב-**Redirect URLs** הוסף:
   - `http://localhost:8000/auth/confirm`
   - `http://localhost:8000/auth/confirm#access_token=*&type=email`
   - (אם יש לך domain, הוסף גם את ה-URLs שלו)

זה יגרום לכךשמשתמש מאשר אימייל, הוא יועבר לדף שלנו במקום ל-"CANNOT REACH THIS PAGE".

## 4. Install Dependencies

```bash
pip install -r requirements.txt
```

## 5. Create Database Tables in Supabase

### Step-by-Step Instructions:

1. **Open Supabase Dashboard:**
   - Go to: https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk
   - Make sure you're logged in

2. **Open SQL Editor:**
   - In the left sidebar, click on **"SQL Editor"** (it has an icon that looks like a database/terminal)
   - Or go directly to: https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk/sql/new

3. **Create a New Query:**
   - Click the **"New query"** button (top right)
   - You'll see a text editor where you can write SQL

4. **Copy and Paste the SQL:**
   - Copy the entire SQL script below (from `-- Create user_profiles table` to the end)
   - Paste it into the SQL Editor

5. **Run the SQL:**
   - Click the **"Run"** button (or press `Ctrl+Enter` / `Cmd+Enter`)
   - Wait for it to complete - you should see "Success. No rows returned" or similar message

6. **Verify Tables Were Created:**
   - Go to **"Table Editor"** in the left sidebar
   - You should see three tables: `user_profiles`, `courses`, and `constraints`

### SQL Script to Run:

```sql
-- Create user_profiles table (links to auth.users)
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT,  -- User email (for minimal profile creation)
    name TEXT,
    id_number TEXT,
    faculty TEXT,
    study_track TEXT,
    cumulative_average FLOAT,
    success_rate FLOAT,
    current_semester TEXT,
    current_year INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add email column if it doesn't exist (for existing tables)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'user_profiles' AND column_name = 'email'
    ) THEN
        ALTER TABLE user_profiles ADD COLUMN email TEXT;
    END IF;
END $$;

-- Create courses table
CREATE TABLE IF NOT EXISTS courses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    course_name TEXT NOT NULL,
    course_number TEXT,
    credit_points FLOAT,
    grade FLOAT,
    letter_grade TEXT,
    semester TEXT,
    year INTEGER,
    notes TEXT,
    is_passed BOOLEAN DEFAULT TRUE,
    retake_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE courses ENABLE ROW LEVEL SECURITY;

-- Create policies for user_profiles
CREATE POLICY "Users can view their own profile"
    ON user_profiles FOR SELECT
    USING (auth.uid() = id);

CREATE POLICY "Users can update their own profile"
    ON user_profiles FOR UPDATE
    USING (auth.uid() = id);

CREATE POLICY "Users can insert their own profile"
    ON user_profiles FOR INSERT
    WITH CHECK (auth.uid() = id);

-- Create policies for courses
CREATE POLICY "Users can view their own courses"
    ON courses FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own courses"
    ON courses FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own courses"
    ON courses FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own courses"
    ON courses FOR DELETE
    USING (auth.uid() = user_id);

-- Create constraints table
CREATE TABLE IF NOT EXISTS constraints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    days TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security for constraints
ALTER TABLE constraints ENABLE ROW LEVEL SECURITY;

-- Create policies for constraints
CREATE POLICY "Users can view their own constraints"
    ON constraints FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own constraints"
    ON constraints FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own constraints"
    ON constraints FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own constraints"
    ON constraints FOR DELETE
    USING (auth.uid() = user_id);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS courses_user_id_idx ON courses(user_id);
CREATE INDEX IF NOT EXISTS constraints_user_id_idx ON constraints(user_id);
```

### Alternative: Run Only the Constraints Table (if other tables already exist)

If you already have `user_profiles` and `courses` tables, you can run just this part:

```sql
-- Create constraints table
CREATE TABLE IF NOT EXISTS constraints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    days TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security for constraints
ALTER TABLE constraints ENABLE ROW LEVEL SECURITY;

-- Create policies for constraints
CREATE POLICY "Users can view their own constraints"
    ON constraints FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own constraints"
    ON constraints FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own constraints"
    ON constraints FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own constraints"
    ON constraints FOR DELETE
    USING (auth.uid() = user_id);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS constraints_user_id_idx ON constraints(user_id);
```

### Troubleshooting:

- **Error: "relation already exists"** - The table already exists, which is fine. The `IF NOT EXISTS` clause should prevent this, but if you see it, the table is already created.
- **Error: "permission denied"** - Make sure you're logged in as the project owner or have admin access.
- **Can't find SQL Editor** - Look in the left sidebar menu, it should be under "SQL Editor" or "Database" section.

## 6. View Your Data in Supabase

לצפייה בנתונים שנשמרו ב-Supabase, ראה את הקובץ: **`VIEW_DATA_IN_SUPABASE.md`**

הקובץ מכיל הוראות מפורטות על:
- איך לראות את הטבלאות (user_profiles, courses, constraints)
- איך לראות את המשתמשים ב-Authentication
- איך להריץ שאילתות SQL
- מה נמצא בכל טבלה

