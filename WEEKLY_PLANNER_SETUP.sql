-- Weekly Planner Setup (Supabase)
-- Creates tables for weekly constraints, weekly plans, plan blocks,
-- group plan blocks, and course time preferences.

-- 1) Weekly constraints (disposable, per week)
CREATE TABLE IF NOT EXISTS weekly_constraints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    week_start DATE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    days TEXT NOT NULL, -- JSON array or comma-separated list
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    is_hard BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2) Weekly plan header
CREATE TABLE IF NOT EXISTS weekly_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    week_start DATE NOT NULL,
    source TEXT DEFAULT 'auto',
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3) Weekly plan blocks (individual schedule items)
CREATE TABLE IF NOT EXISTS weekly_plan_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES weekly_plans(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    course_number TEXT NOT NULL,
    course_name TEXT NOT NULL,
    work_type TEXT NOT NULL CHECK (work_type IN ('personal', 'group')),
    day_of_week INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6),
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    is_locked BOOLEAN DEFAULT FALSE,
    source TEXT DEFAULT 'auto',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 4) Group plan blocks (synced across members)
CREATE TABLE IF NOT EXISTS group_plan_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id UUID NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
    week_start DATE NOT NULL,
    course_number TEXT NOT NULL,
    day_of_week INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6),
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    created_by UUID NOT NULL REFERENCES user_profiles(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 5) Course time preferences (personal vs group ratio)
CREATE TABLE IF NOT EXISTS course_time_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    course_number TEXT NOT NULL,
    personal_ratio FLOAT DEFAULT 0.5,
    group_ratio FLOAT DEFAULT 0.5,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, course_number)
);

-- RLS
ALTER TABLE weekly_constraints ENABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_plan_blocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_plan_blocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_time_preferences ENABLE ROW LEVEL SECURITY;

-- Policies: users can access their own records
CREATE POLICY "Users can view their weekly constraints"
    ON weekly_constraints FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their weekly constraints"
    ON weekly_constraints FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their weekly constraints"
    ON weekly_constraints FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their weekly constraints"
    ON weekly_constraints FOR DELETE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can view their weekly plans"
    ON weekly_plans FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their weekly plans"
    ON weekly_plans FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their weekly plans"
    ON weekly_plans FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their weekly plans"
    ON weekly_plans FOR DELETE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can view their weekly plan blocks"
    ON weekly_plan_blocks FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their weekly plan blocks"
    ON weekly_plan_blocks FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their weekly plan blocks"
    ON weekly_plan_blocks FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their weekly plan blocks"
    ON weekly_plan_blocks FOR DELETE
    USING (auth.uid() = user_id);

-- Group plan blocks: allow members to view; only admins insert/update
CREATE POLICY "Group members can view group plan blocks"
    ON group_plan_blocks FOR SELECT
    USING (true);

CREATE POLICY "Authenticated users can insert group plan blocks"
    ON group_plan_blocks FOR INSERT
    WITH CHECK (auth.uid() IS NOT NULL);

CREATE POLICY "Authenticated users can update group plan blocks"
    ON group_plan_blocks FOR UPDATE
    USING (auth.uid() IS NOT NULL);

CREATE POLICY "Users can view course time preferences"
    ON course_time_preferences FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert course time preferences"
    ON course_time_preferences FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update course time preferences"
    ON course_time_preferences FOR UPDATE
    USING (auth.uid() = user_id);

