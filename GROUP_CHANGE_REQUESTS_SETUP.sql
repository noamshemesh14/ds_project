-- =====================================================
-- GROUP CHANGE REQUEST & APPROVAL SYSTEM SETUP
-- =====================================================
-- This creates tables for managing group meeting change requests
-- and tracking member approvals.
-- =====================================================

-- 1. Create group_meeting_change_requests table
CREATE TABLE IF NOT EXISTS group_meeting_change_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id UUID NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
    week_start DATE NOT NULL,
    
    -- Original time (if exists)
    original_day_of_week INTEGER,
    original_start_time TIME,
    original_end_time TIME,
    
    -- Proposed new time
    proposed_day_of_week INTEGER NOT NULL CHECK (proposed_day_of_week >= 0 AND proposed_day_of_week <= 6),
    proposed_start_time TIME NOT NULL,
    proposed_end_time TIME NOT NULL,
    
    -- Request details
    requested_by UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    reason TEXT,
    
    -- Status: 'pending', 'approved', 'rejected'
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE
);

-- 2. Create group_change_approvals table
CREATE TABLE IF NOT EXISTS group_change_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES group_meeting_change_requests(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- true = approved, false = rejected
    approved BOOLEAN NOT NULL,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    responded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure one response per user per request
    UNIQUE(request_id, user_id)
);

-- 3. Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_change_requests_group_id ON group_meeting_change_requests(group_id);
CREATE INDEX IF NOT EXISTS idx_change_requests_status ON group_meeting_change_requests(status);
CREATE INDEX IF NOT EXISTS idx_change_requests_week ON group_meeting_change_requests(week_start);
CREATE INDEX IF NOT EXISTS idx_change_approvals_request ON group_change_approvals(request_id);
CREATE INDEX IF NOT EXISTS idx_change_approvals_user ON group_change_approvals(user_id);

-- 4. Comments for documentation
COMMENT ON TABLE group_meeting_change_requests IS 'Tracks requests to change group meeting times - requires unanimous approval';
COMMENT ON TABLE group_change_approvals IS 'Tracks individual member approvals/rejections for change requests';
COMMENT ON COLUMN group_meeting_change_requests.status IS 'pending | approved | rejected';
COMMENT ON COLUMN group_change_approvals.approved IS 'true = approved, false = rejected';

-- 5. Enable RLS (Row Level Security)
ALTER TABLE group_meeting_change_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_change_approvals ENABLE ROW LEVEL SECURITY;

-- 6. RLS Policies for group_meeting_change_requests

-- Users can view requests for groups they're in
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

-- Users can create change requests for groups they're in
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

-- System can update request status (for API)
DROP POLICY IF EXISTS "Service role can update requests" ON group_meeting_change_requests;
CREATE POLICY "Service role can update requests"
ON group_meeting_change_requests FOR UPDATE
USING (true)
WITH CHECK (true);

-- 7. RLS Policies for group_change_approvals

-- Users can view approvals for requests they can see
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

-- Users can create their own approvals
DROP POLICY IF EXISTS "Users can create own approvals" ON group_change_approvals;
CREATE POLICY "Users can create own approvals"
ON group_change_approvals FOR INSERT
WITH CHECK (user_id = auth.uid());

-- System can update approvals (for API)
DROP POLICY IF EXISTS "Service role can update approvals" ON group_change_approvals;
CREATE POLICY "Service role can update approvals"
ON group_change_approvals FOR UPDATE
USING (true)
WITH CHECK (true);

-- 8. Grant permissions
GRANT ALL ON group_meeting_change_requests TO authenticated;
GRANT ALL ON group_change_approvals TO authenticated;
GRANT ALL ON group_meeting_change_requests TO anon;
GRANT ALL ON group_change_approvals TO anon;

-- =====================================================
-- SETUP COMPLETE! ✅
-- =====================================================
-- Next steps:
-- 1. Run this script in Supabase SQL Editor
-- 2. Go to Settings → API → Reload Schema Cache
-- 3. Wait 30 seconds for cache refresh
-- 4. Test the group change request feature!
-- =====================================================

-- Verification queries (run these to check):
-- SELECT * FROM group_meeting_change_requests;
-- SELECT * FROM group_change_approvals;
-- SELECT COUNT(*) FROM group_meeting_change_requests; -- Should return 0 initially
