-- =====================================================
-- FULL SCHEDULE SYSTEM SETUP
-- =====================================================
-- This script creates all tables needed for:
-- 1. Group meeting change requests & approvals
-- 2. Group preferences (study preferences per group)
-- 3. Block resize functionality
-- 4. User preference learning (schedule_change_notes)
-- =====================================================

-- =====================================================
-- PART 0: USER PROFILE COLUMNS FOR LEARNING
-- =====================================================

-- Add columns for user preference learning
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS study_preferences_raw TEXT;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS study_preferences_summary JSONB;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS schedule_change_notes JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN user_profiles.study_preferences_raw IS 'Free-text user preferences for studying';
COMMENT ON COLUMN user_profiles.study_preferences_summary IS 'LLM-summarized structured preferences based on raw + change notes';
COMMENT ON COLUMN user_profiles.schedule_change_notes IS 'Array of notes from manual schedule changes (learning data)';

-- =====================================================
-- PART 1: GROUP MEETING CHANGE REQUESTS
-- =====================================================

-- Drop existing tables if they exist (for clean setup)
DROP TABLE IF EXISTS group_change_approvals CASCADE;
DROP TABLE IF EXISTS group_meeting_change_requests CASCADE;

-- 1. Create group_meeting_change_requests table
CREATE TABLE group_meeting_change_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id UUID NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
    week_start DATE NOT NULL,
    
    -- Request type: 'move' (change time), 'resize' (change duration)
    request_type VARCHAR(20) NOT NULL DEFAULT 'move' CHECK (request_type IN ('move', 'resize')),
    
    -- Original time
    original_day_of_week INTEGER,
    original_start_time TIME,
    original_end_time TIME,
    original_duration_hours INTEGER DEFAULT 1,
    
    -- Proposed new time/duration
    proposed_day_of_week INTEGER CHECK (proposed_day_of_week >= 0 AND proposed_day_of_week <= 6),
    proposed_start_time TIME,
    proposed_end_time TIME,
    proposed_duration_hours INTEGER,
    
    -- Request details
    requested_by UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    reason TEXT,                              -- Why they want the change
    hours_explanation TEXT,                   -- Explanation about needing more/less hours
    
    -- Status: 'pending', 'approved', 'rejected'
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE
);

-- 2. Create group_change_approvals table
CREATE TABLE group_change_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES group_meeting_change_requests(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- true = approved, false = rejected
    approved BOOLEAN NOT NULL,
    response_note TEXT,                       -- Optional note from approver
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    responded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure one response per user per request
    UNIQUE(request_id, user_id)
);

-- =====================================================
-- PART 2: GROUP PREFERENCES
-- =====================================================

-- 3. Create group_preferences table
CREATE TABLE IF NOT EXISTS group_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id UUID NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
    
    -- Raw preference text (from all members' inputs combined)
    preferences_raw TEXT,
    
    -- LLM summary of group preferences (JSON)
    preferences_summary JSONB,
    
    -- Preferred meeting hours
    preferred_hours_per_week INTEGER DEFAULT 4,
    
    -- Notes about why hours changed
    hours_change_history JSONB DEFAULT '[]'::jsonb,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- One preferences record per group
    UNIQUE(group_id)
);

-- =====================================================
-- PART 3: INDEXES
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_change_requests_group_id ON group_meeting_change_requests(group_id);
CREATE INDEX IF NOT EXISTS idx_change_requests_status ON group_meeting_change_requests(status);
CREATE INDEX IF NOT EXISTS idx_change_requests_week ON group_meeting_change_requests(week_start);
CREATE INDEX IF NOT EXISTS idx_change_approvals_request ON group_change_approvals(request_id);
CREATE INDEX IF NOT EXISTS idx_change_approvals_user ON group_change_approvals(user_id);
CREATE INDEX IF NOT EXISTS idx_group_preferences_group ON group_preferences(group_id);

-- =====================================================
-- PART 4: COMMENTS
-- =====================================================

COMMENT ON TABLE group_meeting_change_requests IS 'Tracks requests to change group meeting times/durations - requires unanimous approval';
COMMENT ON TABLE group_change_approvals IS 'Tracks individual member approvals/rejections for change requests';
COMMENT ON TABLE group_preferences IS 'Stores study preferences for each group, updated when all members approve changes';
COMMENT ON COLUMN group_meeting_change_requests.request_type IS 'move = change time, resize = change duration';
COMMENT ON COLUMN group_meeting_change_requests.hours_explanation IS 'User explanation of why they need more/less hours';
COMMENT ON COLUMN group_preferences.hours_change_history IS 'JSON array of {date, old_hours, new_hours, reason, approved_by}';

-- =====================================================
-- PART 5: RLS (Row Level Security)
-- =====================================================

ALTER TABLE group_meeting_change_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_change_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_preferences ENABLE ROW LEVEL SECURITY;

-- Policies for group_meeting_change_requests
DROP POLICY IF EXISTS "Users can view change requests for their groups" ON group_meeting_change_requests;
CREATE POLICY "Users can view change requests for their groups"
ON group_meeting_change_requests FOR SELECT
USING (
    EXISTS (
        SELECT 1 FROM group_members
        WHERE group_members.group_id = group_meeting_change_requests.group_id
        AND group_members.user_id = auth.uid()
        AND group_members.status = 'approved'
    )
);

DROP POLICY IF EXISTS "Users can create change requests for their groups" ON group_meeting_change_requests;
CREATE POLICY "Users can create change requests for their groups"
ON group_meeting_change_requests FOR INSERT
WITH CHECK (
    EXISTS (
        SELECT 1 FROM group_members
        WHERE group_members.group_id = group_meeting_change_requests.group_id
        AND group_members.user_id = auth.uid()
        AND group_members.status = 'approved'
    )
);

DROP POLICY IF EXISTS "Service role can update requests" ON group_meeting_change_requests;
CREATE POLICY "Service role can update requests"
ON group_meeting_change_requests FOR UPDATE
USING (true) WITH CHECK (true);

-- Policies for group_change_approvals
DROP POLICY IF EXISTS "Users can view approvals" ON group_change_approvals;
CREATE POLICY "Users can view approvals"
ON group_change_approvals FOR SELECT
USING (
    EXISTS (
        SELECT 1 FROM group_meeting_change_requests gcr
        JOIN group_members gm ON gm.group_id = gcr.group_id
        WHERE gcr.id = group_change_approvals.request_id
        AND gm.user_id = auth.uid()
        AND gm.status = 'approved'
    )
);

DROP POLICY IF EXISTS "Users can create own approvals" ON group_change_approvals;
CREATE POLICY "Users can create own approvals"
ON group_change_approvals FOR INSERT
WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "Service role can update approvals" ON group_change_approvals;
CREATE POLICY "Service role can update approvals"
ON group_change_approvals FOR UPDATE
USING (true) WITH CHECK (true);

-- Policies for group_preferences
DROP POLICY IF EXISTS "Users can view group preferences" ON group_preferences;
CREATE POLICY "Users can view group preferences"
ON group_preferences FOR SELECT
USING (
    EXISTS (
        SELECT 1 FROM group_members
        WHERE group_members.group_id = group_preferences.group_id
        AND group_members.user_id = auth.uid()
        AND group_members.status = 'approved'
    )
);

DROP POLICY IF EXISTS "Service role can manage group preferences" ON group_preferences;
CREATE POLICY "Service role can manage group preferences"
ON group_preferences FOR ALL
USING (true) WITH CHECK (true);

-- =====================================================
-- PART 6: PERMISSIONS
-- =====================================================

GRANT ALL ON group_meeting_change_requests TO authenticated;
GRANT ALL ON group_change_approvals TO authenticated;
GRANT ALL ON group_preferences TO authenticated;
GRANT ALL ON group_meeting_change_requests TO anon;
GRANT ALL ON group_change_approvals TO anon;
GRANT ALL ON group_preferences TO anon;

-- =====================================================
-- PART 7: Add hours_explanation to user_profiles if not exists
-- =====================================================

ALTER TABLE user_profiles
ADD COLUMN IF NOT EXISTS schedule_change_notes JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN user_profiles.schedule_change_notes IS 'JSON array of notes from user schedule changes, used to update preferences summary';

-- =====================================================
-- SETUP COMPLETE! ✅
-- =====================================================
-- Next steps:
-- 1. Run this script in Supabase SQL Editor
-- 2. Go to Settings → API → Reload Schema Cache
-- 3. Wait 30 seconds for cache refresh
-- 4. Test the features!
-- =====================================================

-- Verification queries:
SELECT 'group_meeting_change_requests created' AS status, COUNT(*) AS rows FROM group_meeting_change_requests;
SELECT 'group_change_approvals created' AS status, COUNT(*) AS rows FROM group_change_approvals;
SELECT 'group_preferences created' AS status, COUNT(*) AS rows FROM group_preferences;

