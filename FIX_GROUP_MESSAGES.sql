-- Fix group_messages table to support system messages from agent
-- Run this in Supabase SQL Editor

-- Add is_system column (replaces is_agent for consistency)
ALTER TABLE group_messages ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT FALSE;

-- Add sender_name column for system messages
ALTER TABLE group_messages ADD COLUMN IF NOT EXISTS sender_name TEXT;

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_group_messages_is_system ON group_messages(is_system);

-- Enable RLS if not already enabled
ALTER TABLE group_messages ENABLE ROW LEVEL SECURITY;

-- Policy: Allow viewing messages for group members
DROP POLICY IF EXISTS "Group members can view messages" ON group_messages;
CREATE POLICY "Group members can view messages"
    ON group_messages FOR SELECT
    USING (EXISTS (
        SELECT 1 FROM group_members
        WHERE group_members.group_id = group_messages.group_id
        AND group_members.user_id = auth.uid()
        AND group_members.status = 'approved'
    ));

-- Policy: Allow members to insert their own messages
DROP POLICY IF EXISTS "Group members can send messages" ON group_messages;
CREATE POLICY "Group members can send messages"
    ON group_messages FOR INSERT
    WITH CHECK (
        auth.uid() = user_id
        AND EXISTS (
            SELECT 1 FROM group_members
            WHERE group_members.group_id = group_messages.group_id
            AND group_members.user_id = auth.uid()
            AND group_members.status = 'approved'
        )
    );

-- Policy: Allow service role to insert system messages (agent messages)
DROP POLICY IF EXISTS "Allow service role to insert system messages" ON group_messages;
CREATE POLICY "Allow service role to insert system messages"
    ON group_messages FOR INSERT
    WITH CHECK (true);




