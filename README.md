# Academic Planner - Terminal Agent System

AI-powered academic planning system with terminal interface for managing courses, schedules, notifications, and study groups.

## Quick Start

### 1. Installation

```bash
pip install -r requirements.txt
```

### 2. Environment Setup

Create a `.env` file with:

```env
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
LLM_API_KEY=your_llmod_api_key
LLM_MODEL=RPRTHPB-gpt-5-mini
LLM_BASE_URL=https://api.llmod.ai/v1
```

### 3. Run the Server

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Or use the provided scripts:
- Windows CMD: `run_uvicorn.bat`
- PowerShell: `run_uvicorn.ps1`

## Features

- **User Authentication**: Login with username/password to get access token
- **Course Management**: Add courses from catalog to your course list
- **Schedule Retrieval**: View weekly schedule for any date
- **Notifications**: View and clear unread notifications
- **Block Management**: Move study blocks (personal or group)
- **Group Management**: Create study groups and manage invitations
- **Request Handling**: Approve or reject group change requests

## API Usage Examples

### 1. Login

**Windows CMD:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/auth/login" -H "Content-Type: application/json" -d "{\"username\":\"your_email@example.com\",\"password\":\"your_password\"}"
```

**PowerShell:**
```powershell
curl -X POST "http://127.0.0.1:8000/api/auth/login" -H "Content-Type: application/json" -d '{\"username\":\"your_email@example.com\",\"password\":\"your_password\"}'
```

**Save token to variable (Windows CMD):**
```cmd
for /f "tokens=*" %i in ('curl -X POST "http://127.0.0.1:8000/api/auth/login" -H "Content-Type: application/json" -d "{\"username\":\"your_email@example.com\",\"password\":\"your_password\"}"') do set TOKEN=%i
```

**Save token to variable (PowerShell):**
```powershell
$TOKEN = (curl -X POST "http://127.0.0.1:8000/api/auth/login" -H "Content-Type: application/json" -d '{\"username\":\"your_email@example.com\",\"password\":\"your_password\"}' | ConvertFrom-Json).access_token
```

### 2. Add Course

**Windows CMD:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"add course אלגוריתמים 1 - 104043\"}"
```

**PowerShell:**
```powershell
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{\"prompt\":\"add course אלגוריתמים 1 - 104043\"}'
```

**With course name validation:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"add course מסדי נתונים 104043\"}"
```

### 3. View Weekly Schedule

**Get schedule for specific week:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"show me my schedule for the week starting 2026/02/08\"}"
```

**Get current week schedule:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"show my schedule\"}"
```

**Alternative date formats:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"schedule for 2026-02-08\"}"
```

### 4. View Notifications

**Get all unread notifications:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"show notifications\"}"
```

**Alternative prompts:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"what are my notifications\"}"
```

### 5. Clear Notifications

**Mark all notifications as read:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"clear notifications\"}"
```

**Alternative prompts:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"mark all notifications as read\"}"
```

### 6. Move Study Block

**Move personal block:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"move block abc-123-def to day 2 at 14:00\"}"
```

**Move block with preference explanation (will be saved for learning):**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"move block abc-123-def to day 3 at 16:00 because I prefer to study in the afternoon\"}"
```

**Move group block (creates change request):**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"move group block xyz-789-abc to day 4 at 15:00\"}"
```

**Note:** Group blocks require approval from all group members. The system will create a change request and notify all members.

### 7. Create Study Group

```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"create study group for course 104043 named Algorithms Study Group and invite user1@example.com user2@example.com\"}"
```

### 8. Approve/Reject Requests

**Approve a request:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"approve request req-123-456\"}"
```

**Reject a request:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"prompt\":\"reject request req-123-456\"}"
```

### 9. Chat with TechnionAI (RAG Chat)

**Ask informational questions about Technion:**

**PowerShell (Recommended - works best):**
```powershell
$body = @{prompt="What are the prerequisites for the algorithms course?"} | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/execute" -Method POST -ContentType "application/json" -Body $body
```

**PowerShell with curl.exe:**
```powershell
$json = '{"prompt":"What are the prerequisites for the algorithms course?"}'
curl.exe -X POST http://127.0.0.1:8000/api/execute -H "Content-Type: application/json" -d $json
```

**Windows CMD:**
```cmd
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"What are the prerequisites for the algorithms course?\"}"
```

**More examples:**
```cmd
# Ask about academic procedures
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"How can I cancel a course?\"}"

# Ask about course information
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"What is the difference between course 104043 and course 104044?\"}"

# Ask about regulations
curl -X POST "http://127.0.0.1:8000/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"What are the rules for exam retakes (moed bet)?\"}"
```

**Note:** All chat queries go through the Supervisor, which intelligently routes informational questions to the RAG Chat executor. The system uses RAG (Retrieval-Augmented Generation) to answer questions based on official Technion documents and academic information.

## Response Format

All API responses follow this structure:

```json
{
  "status": "ok",
  "error": null,
  "response": "Task completed successfully",
  "steps": [
    {
      "module": "supervisor",
      "prompt": {
        "user_prompt": "add course 104043",
        "routing_type": "llm"
      },
      "response": {
        "executor": "course_manager",
        "params": {
          "course_number": "104043"
        }
      }
    },
    {
      "module": "course_manager",
      "prompt": {
        "user_prompt": "add course 104043",
        "course_number": "104043"
      },
      "response": {
        "status": "success",
        "message": "Course מסדי נתונים (104043) successfully added to your course list for חורף 2026"
      }
    }
  ]
}
```

## Error Handling

If an error occurs, the response will have:

```json
{
  "status": "error",
  "error": "Error message here",
  "response": null,
  "steps": [...]
}
```

## System Endpoints

### Weekly Plan Generation (System Function)

**Generate weekly plans for ALL users** (automated system function):

```cmd
curl -X POST "http://127.0.0.1:8000/api/system/weekly-plan/generate?week_start=2025-02-22"
```

**With optional API key** (if `SYSTEM_API_KEY` is set in `.env`):

```cmd
curl -X POST "http://127.0.0.1:8000/api/system/weekly-plan/generate?week_start=2025-02-22&api_key=your_system_api_key"
```

**PowerShell:**
```powershell
curl -X POST "http://127.0.0.1:8000/api/system/weekly-plan/generate?week_start=2025-02-22"
```

**Important:**
- This endpoint does NOT require user authentication - it's a system function
- `week_start` must be in format `YYYY-MM-DD` (e.g., "2025-02-22" for February 22, 2025)
- The system will:
  1. Clean up ALL old plans and blocks for this week (including orphaned blocks)
  2. Generate new plans for ALL users based on their current courses and preferences
  3. Use LLM to optimize schedule placement according to user preferences
  4. Insert the new plans into Supabase
- **Automatic execution**: Runs automatically every week for the next week (calculates next Sunday)
- **Manual execution**: You can call it manually anytime with any date for testing or to regenerate plans
- **LLM Integration**: If `LLM_API_KEY` is configured, the system will use LLM to create personalized schedules based on user preferences. If LLM fails, it falls back to deterministic planning (without preferences).

## Notes

- **Course Numbers**: Must be exact 3-6 digit numbers from the catalog (e.g., "104043", not "10404")
- **Semester & Year**: Automatically set to "חורף" (Winter) and 2026 when adding courses
- **Date Formats**: Supports both `YYYY-MM-DD` and `YYYY/MM/DD` formats
- **Week Start**: Weeks start on Sunday (day 0)
- **Group Blocks**: Moving group blocks creates a change request that requires approval from all members
- **Preferences Learning**: When you move blocks with explanations (e.g., "because I prefer..."), the system learns your preferences for future schedule generation

## Troubleshooting

### Authentication Errors
- Make sure you're using the correct token from login
- Token expires after a period - login again to get a new token

### Course Not Found
- Verify the course number exists in the catalog
- Course numbers must match exactly (case-sensitive)

### Block Move Conflicts
- Check for overlapping blocks or hard constraints
- Group blocks require all members' approval

### LLM Routing Issues
- Check that `LLM_API_KEY` is set correctly in `.env`
- Verify `LLM_BASE_URL` ends with `/v1`
- System will fall back to pattern matching if LLM is unavailable
