-- Add is_agent column to group_messages table if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'group_messages' AND column_name = 'is_agent'
    ) THEN
        ALTER TABLE group_messages ADD COLUMN is_agent BOOLEAN DEFAULT FALSE;
        RAISE NOTICE 'Added is_agent column to group_messages table';
    ELSE
        RAISE NOTICE 'is_agent column already exists in group_messages table';
    END IF;
END $$;

