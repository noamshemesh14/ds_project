# 🚀 Setup Instructions for Academic Planner

## Environment Variables

Create a `.env` file in the project root with the following variables:

```env
# Supabase Configuration
SUPABASE_URL=your_supabase_url_here
SUPABASE_ANON_KEY=your_supabase_anon_key_here
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key_here

# Gemini API (for transcript parsing)
GEMINI_API_KEY=your_gemini_api_key_here

# OpenAI API (for LLM-based schedule refinement with GPT-4o mini)
# Get your API key from: https://platform.openai.com/api-keys
OPENAI_API_KEY=sk-proj-XXXXXXXXXXXXXXXXXXXXX

# JWT Secret (for authentication)
JWT_SECRET=your_jwt_secret_here

# Database (if using SQLite/PostgreSQL directly)
DATABASE_URL=sqlite:///./student_planner.db
```

## Installation Steps

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Database Setup
Run these SQL scripts in your Supabase SQL Editor:

1. **USER_PREFERENCES_SETUP.sql** - Adds study preferences columns to user_profiles
2. **STRICT_COURSE_ENFORCEMENT.sql** - Enforces foreign key constraints
3. **NOTIFICATIONS_AND_UPDATES_SETUP.sql** - Sets up notifications and group updates
4. **FIX_GROUP_MESSAGES.sql** - Fixes group messages table for system messages

### 3. Get OpenAI API Key
1. Go to https://platform.openai.com/api-keys
2. Sign up or log in
3. Create a new API key
4. Copy the key and add it to your `.env` file as `OPENAI_API_KEY`

### 4. Start the Server
```bash
py -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Features

### 🤖 LLM-Based Schedule Refinement
- Uses GPT-4o mini to optimize personal study block placement
- Considers user preferences, habits, and scheduling patterns
- Falls back to deterministic scheduling if LLM fails

### 📝 Study Preferences
- Users can enter their study preferences in natural language
- System uses these preferences to create optimal schedules
- Preferences are stored in `user_profiles` table:
  - `study_preferences_raw`: Raw text from user
  - `study_preferences_summary`: LLM-extracted structured data (future feature)

### 👥 Group Coordination
- Automatic group meeting scheduling
- System agent sends consolidated weekly updates to groups
- Notifications for plan changes

### 🔒 Hard Constraints
- Fixed time blocks (classes, work, etc.)
- User-blocked times
- Group meetings

### 🎯 Soft Constraints (via preferences)
- Preferred study hours
- Preferred days
- Session length preferences
- Break duration preferences

## Testing

1. Go to `/profile` page
2. Fill in your study preferences
3. Click "שמור העדפות"
4. Run weekly plan generation (manually or wait for scheduled run)
5. Check `/schedule` to see your personalized schedule

## Troubleshooting

### LLM Refinement Not Working
- Check that `OPENAI_API_KEY` is set in `.env`
- Check server logs for LLM-related errors
- System will fall back to deterministic scheduling if LLM fails

### Preferences Not Saving
- Check browser console for errors
- Verify user is logged in (auth token exists)
- Check server logs for API errors

### Schedule Not Generated
- Run SQL setup scripts
- Check hard constraints aren't blocking all time slots
- Verify courses exist in `course_catalog` table



