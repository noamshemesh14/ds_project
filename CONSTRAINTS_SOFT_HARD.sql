-- Add soft/hard support to permanent constraints
ALTER TABLE constraints
ADD COLUMN IF NOT EXISTS is_hard BOOLEAN DEFAULT TRUE;

-- Optional: update existing rows to default TRUE
UPDATE constraints SET is_hard = TRUE WHERE is_hard IS NULL;









