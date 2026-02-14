# Study Groups Setup - SQL Scripts for Supabase

## ⚠️ חשוב: הרצי את כל הסקריפט הזה בבת אחת!

הסדר חשוב מאוד - קודם יוצרים את כל הטבלאות, ואז את ה-policies.

## 1. הסקריפט המלא

לך ל-Supabase Dashboard > SQL Editor והרץ את הסקריפט המלא הזה:

```sql
-- ============================================
-- STEP 1: Create ALL Tables First
-- ============================================

-- 1.1. Create study_groups table
CREATE TABLE IF NOT EXISTS study_groups (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    course_id TEXT NOT NULL,
    course_name TEXT NOT NULL,
    group_name TEXT NOT NULL,
    description TEXT,
    created_by UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 1.2. Create group_members table
CREATE TABLE IF NOT EXISTS group_members (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    group_id UUID NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    invited_by UUID REFERENCES auth.users(id),
    invited_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    joined_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(group_id, user_id)
);

-- 1.3. Create group_invitations table
-- NOTE: group_id is nullable because invitations can be created before the group exists
CREATE TABLE IF NOT EXISTS group_invitations (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    group_id UUID REFERENCES study_groups(id) ON DELETE CASCADE,
    inviter_id UUID NOT NULL REFERENCES auth.users(id),
    invitee_email TEXT NOT NULL,
    invitee_user_id UUID REFERENCES auth.users(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected', 'expired')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    responded_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() + INTERVAL '30 days')
);

-- 1.3.1. Create pending_group_creations table (stores group metadata before group is created)
CREATE TABLE IF NOT EXISTS pending_group_creations (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    inviter_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL,
    course_name TEXT NOT NULL,
    group_name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(inviter_id, course_id)  -- One pending group per inviter per course
);

-- 1.4. Create group_messages table
CREATE TABLE IF NOT EXISTS group_messages (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    group_id UUID NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    is_agent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add is_agent column if it doesn't exist (for existing tables)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'group_messages' AND column_name = 'is_agent'
    ) THEN
        ALTER TABLE group_messages ADD COLUMN is_agent BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

-- 1.5. Create group_updates table
CREATE TABLE IF NOT EXISTS group_updates (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    group_id UUID NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
    update_text TEXT NOT NULL,
    update_type TEXT DEFAULT 'info' CHECK (update_type IN ('info', 'reminder', 'deadline', 'achievement')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 1.6. Create notifications table
CREATE TABLE IF NOT EXISTS notifications (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('group_invitation', 'group_message', 'group_update', 'system')),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    link TEXT,
    read BOOLEAN DEFAULT FALSE,
    email_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- STEP 2: Enable RLS on all tables
-- ============================================

ALTER TABLE study_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_updates ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;

-- ============================================
-- STEP 3: Create Indexes
-- ============================================

CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, read, created_at DESC);

-- ============================================
-- STEP 4: Create Helper Functions (to avoid recursion)
-- ============================================

-- Function to check if user is a member of a group (security definer to avoid recursion)
CREATE OR REPLACE FUNCTION is_group_member(group_id_param UUID, user_id_param UUID DEFAULT auth.uid())
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM group_members 
        WHERE group_id = group_id_param 
        AND user_id = user_id_param 
        AND status = 'approved'
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get user's group IDs (security definer to avoid recursion)
CREATE OR REPLACE FUNCTION get_user_group_ids(user_id_param UUID DEFAULT auth.uid())
RETURNS SETOF UUID AS $$
BEGIN
    RETURN QUERY
    SELECT group_id FROM group_members 
    WHERE user_id = user_id_param AND status = 'approved';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================
-- STEP 5: Create RLS Policies
-- ============================================

-- Policies for study_groups
DROP POLICY IF EXISTS "Users can view groups they are members of" ON study_groups;
CREATE POLICY "Users can view groups they are members of"
    ON study_groups FOR SELECT
    USING (
        created_by = auth.uid() OR
        id = ANY(SELECT get_user_group_ids())
    );

DROP POLICY IF EXISTS "Users can create groups" ON study_groups;
CREATE POLICY "Users can create groups"
    ON study_groups FOR INSERT
    WITH CHECK (created_by = auth.uid());

DROP POLICY IF EXISTS "Group creators can update their groups" ON study_groups;
CREATE POLICY "Group creators can update their groups"
    ON study_groups FOR UPDATE
    USING (created_by = auth.uid());

DROP POLICY IF EXISTS "Group creators can delete their groups" ON study_groups;
CREATE POLICY "Group creators can delete their groups"
    ON study_groups FOR DELETE
    USING (created_by = auth.uid());

-- Policies for group_members
DROP POLICY IF EXISTS "Users can view their own memberships" ON group_members;
CREATE POLICY "Users can view their own memberships"
    ON group_members FOR SELECT
    USING (
        user_id = auth.uid() OR
        EXISTS (
            SELECT 1 FROM study_groups 
            WHERE id = group_members.group_id 
            AND created_by = auth.uid()
        ) OR
        -- Allow users to see all members of groups they are members of
        EXISTS (
            SELECT 1 FROM group_members gm
            WHERE gm.group_id = group_members.group_id
            AND gm.user_id = auth.uid()
            AND gm.status = 'approved'
        )
    );

DROP POLICY IF EXISTS "Group creators can add members" ON group_members;
CREATE POLICY "Group creators can add members"
    ON group_members FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM study_groups 
            WHERE id = group_members.group_id 
            AND created_by = auth.uid()
        )
    );

-- Allow users to add themselves when accepting an invitation
DROP POLICY IF EXISTS "Users can add themselves when accepting invitation" ON group_members;
CREATE POLICY "Users can add themselves when accepting invitation"
    ON group_members FOR INSERT
    WITH CHECK (
        user_id = auth.uid() AND
        EXISTS (
            SELECT 1 FROM group_invitations 
            WHERE group_id = group_members.group_id 
            AND invitee_user_id = auth.uid()
            AND status = 'accepted'
        )
    );

DROP POLICY IF EXISTS "Users can update their own membership status" ON group_members;
CREATE POLICY "Users can update their own membership status"
    ON group_members FOR UPDATE
    USING (user_id = auth.uid());

DROP POLICY IF EXISTS "Group creators can update any membership" ON group_members;
CREATE POLICY "Group creators can update any membership"
    ON group_members FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM study_groups 
            WHERE id = group_members.group_id 
            AND created_by = auth.uid()
        )
    );

-- Policies for group_invitations
DROP POLICY IF EXISTS "Users can view invitations sent to them" ON group_invitations;
CREATE POLICY "Users can view invitations sent to them"
    ON group_invitations FOR SELECT
    USING (
        invitee_user_id = auth.uid() OR
        inviter_id = auth.uid() OR
        EXISTS (
            SELECT 1 FROM study_groups 
            WHERE id = group_invitations.group_id 
            AND created_by = auth.uid()
        )
    );

DROP POLICY IF EXISTS "Group creators can create invitations" ON group_invitations;
CREATE POLICY "Group creators can create invitations"
    ON group_invitations FOR INSERT
    WITH CHECK (
        inviter_id = auth.uid() AND
        EXISTS (
            SELECT 1 FROM study_groups 
            WHERE id = group_invitations.group_id 
            AND created_by = auth.uid()
        )
    );

DROP POLICY IF EXISTS "Invitees can update their invitations" ON group_invitations;
CREATE POLICY "Invitees can update their invitations"
    ON group_invitations FOR UPDATE
    USING (invitee_user_id = auth.uid());

-- Allow creating invitations with NULL group_id (before group is created)
DROP POLICY IF EXISTS "Users can create invitations with NULL group_id" ON group_invitations;
CREATE POLICY "Users can create invitations with NULL group_id"
    ON group_invitations FOR INSERT
    WITH CHECK (inviter_id = auth.uid());

-- Policies for pending_group_creations
-- Enable RLS (optional - if using service role, RLS can stay disabled)
-- ALTER TABLE pending_group_creations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view their own pending group creations" ON pending_group_creations;
CREATE POLICY "Users can view their own pending group creations"
    ON pending_group_creations FOR SELECT
    USING (inviter_id = auth.uid());

DROP POLICY IF EXISTS "Users can create their own pending group creations" ON pending_group_creations;
CREATE POLICY "Users can create their own pending group creations"
    ON pending_group_creations FOR INSERT
    WITH CHECK (inviter_id = auth.uid());

DROP POLICY IF EXISTS "Users can delete their own pending group creations" ON pending_group_creations;
CREATE POLICY "Users can delete their own pending group creations"
    ON pending_group_creations FOR DELETE
    USING (inviter_id = auth.uid());

-- Policies for group_messages
DROP POLICY IF EXISTS "Group members can view messages" ON group_messages;
CREATE POLICY "Group members can view messages"
    ON group_messages FOR SELECT
    USING (
        is_group_member(group_id) OR
        EXISTS (
            SELECT 1 FROM study_groups 
            WHERE id = group_messages.group_id 
            AND created_by = auth.uid()
        )
    );

DROP POLICY IF EXISTS "Group members can send messages" ON group_messages;
CREATE POLICY "Group members can send messages"
    ON group_messages FOR INSERT
    WITH CHECK (
        user_id = auth.uid() AND
        (
            is_group_member(group_id) OR
            EXISTS (
                SELECT 1 FROM study_groups 
                WHERE id = group_messages.group_id 
                AND created_by = auth.uid()
            )
        )
    );

-- Policies for group_updates
DROP POLICY IF EXISTS "Group members can view updates" ON group_updates;
CREATE POLICY "Group members can view updates"
    ON group_updates FOR SELECT
    USING (
        is_group_member(group_id) OR
        EXISTS (
            SELECT 1 FROM study_groups 
            WHERE id = group_updates.group_id 
            AND created_by = auth.uid()
        )
    );

-- Policies for notifications
DROP POLICY IF EXISTS "Users can view their own notifications" ON notifications;
CREATE POLICY "Users can view their own notifications"
    ON notifications FOR SELECT
    USING (user_id = auth.uid());

DROP POLICY IF EXISTS "Users can update their own notifications" ON notifications;
CREATE POLICY "Users can update their own notifications"
    ON notifications FOR UPDATE
    USING (user_id = auth.uid());

-- ============================================
-- STEP 6: Create Functions and Triggers
-- ============================================

-- Function to automatically add group creator as approved member
CREATE OR REPLACE FUNCTION auto_add_group_creator()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO group_members (group_id, user_id, status, joined_at)
    VALUES (NEW.id, NEW.created_by, 'approved', NOW())
    ON CONFLICT (group_id, user_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to call the function
DROP TRIGGER IF EXISTS on_study_group_created ON study_groups;
CREATE TRIGGER on_study_group_created
    AFTER INSERT ON study_groups
    FOR EACH ROW
    EXECUTE FUNCTION auto_add_group_creator();
```

## 2. איך להריץ

1. פתחי את Supabase Dashboard: https://supabase.com/dashboard/project/ncvchkyncwdeysqzkssk
2. לך ל-**SQL Editor** (בסיידבר השמאלי)
3. לחצי על **"New query"** (או פתחי query חדש)
4. **העתיקי את כל הסקריפט למעלה** (מ-STEP 1 עד STEP 5)
5. **הדביקי אותו ב-SQL Editor**
6. לחצי **"Run"** (או Ctrl+Enter)
7. המתיני שהסקריפט יסתיים - אמור להיות "Success"

## 3. אימות שהטבלאות נוצרו

לאחר הרצת הסקריפט, לך ל-**Table Editor** ובדקי שהטבלאות נוצרו:
- ✅ study_groups
- ✅ group_members
- ✅ group_invitations
- ✅ pending_group_creations (חדש!)
- ✅ group_messages
- ✅ group_updates
- ✅ notifications

## 3.1. Migration עבור נתונים קיימים

אם יש לך הזמנות ישנות עם `group_id = NULL` שנוצרו לפני שהטבלה `pending_group_creations` הייתה קיימת, הרץ את הסקריפט ב-`MIGRATION_pending_group_creations.sql`:

```sql
-- זה יוצר רשומות ב-pending_group_creations עבור הזמנות ישנות
-- שים לב: group_name יהיה ברירת מחדל כי אין לנו את השם המקורי
```

**הערה:** קבוצות שכבר נוצרו (יש להן `group_id` ב-`group_invitations`) לא צריכות migration - הן כבר ב-`study_groups` עם כל המידע.

## 4. פתרון בעיות

אם יש שגיאות:

1. **"relation does not exist"** - זה אומר שהטבלה לא נוצרה. בדקי ב-Table Editor אם הטבלאות קיימות
2. **"policy already exists"** - זה בסדר! הסקריפט כולל `DROP POLICY IF EXISTS` כדי למנוע שגיאות
3. **"trigger already exists"** - גם זה בסדר, הסקריפט כולל `DROP TRIGGER IF EXISTS`

אם עדיין יש בעיות:
- ודאי שהרצת את כל הסקריפט בבת אחת
- ודאי שהטבלאות נוצרו בסדר הנכון
- נסי למחוק את הטבלאות הישנות (אם יש) ולהריץ מחדש
