-- Notifications and Group Updates Table Setup
-- Run this in Supabase SQL Editor

-- 1) Notifications table
CREATE TABLE IF NOT EXISTS notifications (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    type TEXT NOT NULL, -- 'group_invitation', 'plan_ready', 'group_meeting'
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    link TEXT, -- Optional link to navigate to
    read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2) Group updates table (for feed)
CREATE TABLE IF NOT EXISTS group_updates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id UUID NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
    update_text TEXT NOT NULL,
    update_type TEXT DEFAULT 'info', -- 'info', 'alert', 'message'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3) Ensure group_messages has is_system column and sender_name
ALTER TABLE group_messages ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT FALSE;
ALTER TABLE group_messages ADD COLUMN IF NOT EXISTS sender_name TEXT;

-- RLS Policies
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_updates ENABLE ROW LEVEL SECURITY;

-- Notifications: users can view/update their own
DROP POLICY IF EXISTS "Users can view their own notifications" ON notifications;
CREATE POLICY "Users can view their own notifications"
    ON notifications FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update their own notifications" ON notifications;
CREATE POLICY "Users can update their own notifications"
    ON notifications FOR UPDATE
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete their own notifications" ON notifications;
CREATE POLICY "Users can delete their own notifications"
    ON notifications FOR DELETE
    USING (auth.uid() = user_id);

-- Group updates: members of the group can view
DROP POLICY IF EXISTS "Group members can view group updates" ON group_updates;
CREATE POLICY "Group members can view group updates"
    ON group_updates FOR SELECT
    USING (EXISTS (
        SELECT 1 FROM group_members
        WHERE group_members.group_id = group_updates.group_id
        AND group_members.user_id = auth.uid()
    ));

-- Allow service role/admin to insert
DROP POLICY IF EXISTS "Allow insertion of group updates" ON group_updates;
CREATE POLICY "Allow insertion of group updates"
    ON group_updates FOR INSERT
    WITH CHECK (true);







