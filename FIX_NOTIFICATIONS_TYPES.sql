-- Fix notifications.type check constraint to allow all app notification types
-- Run in Supabase SQL Editor

ALTER TABLE notifications
DROP CONSTRAINT IF EXISTS notifications_type_check;

ALTER TABLE notifications
ADD CONSTRAINT notifications_type_check
CHECK (
    type IN (
        'group_invitation',
        'plan_ready',
        'group_meeting',
        'group_change_request',
        'group_change_approved',
        'group_change_rejected'
    )
);

-- Optional: verify existing types
-- SELECT DISTINCT type FROM notifications;

