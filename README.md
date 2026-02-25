# Academic Planner (SemesterOS) – Multi-Agent System

AI-powered academic planning system with a **multi-agent architecture**: natural-language prompts are routed by a **supervisor** (using a **smart LLM**) to one of **12 executors**, plus a **system agent** (Weekly Planner) that generates and distributes weekly plans for all users.

---

## Project Overview

- **User flow:** User sends a natural-language prompt (e.g. "Show my schedule for 15/02/2026", "Add constraint: training Monday 18:00–20:00") → **Supervisor** receives it → uses **LLM** to choose one executor and extract parameters → **exactly one executor** runs and returns a response.
- **Smart LLM:** The supervisor uses an LLM (OpenAI or LLMod) for **intelligent routing** and **parameter extraction** from free text. If the LLM is unavailable, it falls back to **pattern matching** (keywords in English/Hebrew).
- **Distribution:** A separate **Weekly Planner** (global/system agent) runs on a schedule or via API: it generates weekly study plans for **all users**, places **group blocks** with the LLM, refines **personal blocks** with the LLM, and **synchronizes** group blocks across all group members so everyone sees the same schedule.
- **RAG:** Informational and procedural questions (e.g. about Technion courses, regulations, academic advice) are handled by the **RAG Chat** executor: retrieval over academy docs (Pinecone + embeddings) plus an LLM to generate answers.

**Interfaces:** Terminal/API (`/api/execute`), optional web UI (schedule view, notifications, manual drag-and-drop). See [README_MANUAL_EDITING.md](README_MANUAL_EDITING.md) for manual schedule editing and group approval.

### Deployed application

The system runs at the following URL. **Use this base URL for all API calls and for the web UI** (do not assume localhost unless you are running the server locally):

**Base URL:** `https://ds-project-499p.onrender.com`

---

## Architecture: Agents and Executors

### Supervisor (single agent)

| Module   | Role |
|----------|------|
| **supervisor** | Routes each user prompt to the correct executor and extracts parameters. Uses **LLM** for routing and parameter extraction; **fallback pattern matching** when LLM is unavailable. Produces a "reasoning" explanation for the chosen executor. |

**Connection:** All user requests go to the supervisor first; the supervisor invokes **exactly one** of the 12 executors per request. Executors do not call each other.

---

### Executors (12 agents)

Each executor handles one family of actions. Names below match API step logs and code.

| Module (exact) | Title | Actions / Goal |
|----------------|-------|----------------|
| **schedule_retriever** | Schedule Retriever | Returns the user's weekly schedule (semester, personal, group blocks, constraints) for a given week. Optional: `date` (YYYY-MM-DD). |
| **rag_chat** | RAG Chat | Answers academic/informational questions using **retrieval** over academy docs (Pinecone + embedding API) and an **LLM** to generate answers. Default for chat/informational queries. |
| **group_manager** | Group Manager | Creates study groups and invites members by email (course-based). Params: `course_number`, `group_name`, `invite_emails`; optional `course_name`, `description`. |
| **notification_retriever** | Notification Retriever | Returns the user's unread notifications. No parameters. |
| **notification_cleaner** | Notification Cleaner | Marks notifications as read or deletes them. Optional: `notification_id`. |
| **request_handler** | Request Handler | Approves or rejects **group invitations** and **group change requests** (move/resize). Params: `action` (accept/approve or reject/decline); optional `request_id`, `group_name`, `course_number`, `date`, `day_of_week`, `time_of_day`, etc. For change requests, all group members must approve; one rejection cancels. |
| **preference_updater** | Preference Updater | Updates user study preferences from natural language; persists raw text and LLM-generated summary. Params: `preferences_text` or `user_prompt`. |
| **block_mover** | Block Mover | Moves a study block to another day/time. Personal blocks: move immediately. Group blocks: creates a **change request** (requires all members' approval). Can trigger preference extraction from the prompt. Params: `block_id` or `course_name`/`course_number` + `original_day` + `original_start_time`, `new_day`, `new_start_time`, `week_start`, optional `user_prompt`. |
| **block_resizer** | Block Resizer | Changes block **duration** (and optionally start time). Personal: updates directly; group: may create a change request. Params: `block_id` or course + `day_of_week` + `start_time`, `new_duration`, `week_start`, optional `new_start_time`, `work_type`. |
| **block_creator** | Block Creator | **Creates new** study blocks (personal or group) and adds them to the weekly plan. Params: `course_name`/`course_number`, `day_of_week`, `start_time`; optional `duration`, `work_type`, `week_start`. |
| **constraint_manager** | Constraint Manager | Adds or deletes constraints (permanent or one-time), e.g. "Training Monday 18:00–20:00", "Meeting Wednesday 10:00–11:00". Add: `title`, `start_time`, `end_time`, `days`/`day_of_week`, optional `is_permanent`, `date`/`week_start`. Delete: `action="delete"`, `title` or `constraint_id`. |
| **courses_retriever** | Courses Retriever | Returns the list of courses the user is taking this semester. No parameters. |

---

### System agent: Weekly Planner (distribution)

| Component | Role |
|-----------|------|
| **Weekly Planner** (Global Scheduler Agent) | **Not** invoked by the supervisor. Triggered by: `POST /api/system/weekly-plan/generate?week_start=YYYY-MM-DD`, `POST /api/weekly-plan/generate`, or a scheduled job. **Goal:** Generate and maintain weekly study plans for **all users** (or a single user). Cleans existing plans for the target week, then builds new plans from courses, constraints, and group memberships. **Uses LLM heavily:** (1) `_plan_group_blocks_with_llm` to place group study blocks in common free slots; (2) `_refine_schedule_with_llm` to place and refine personal (and group) blocks. **Distribution:** Synchronizes `group_plan_blocks` and `weekly_plan_blocks` across all group members so everyone sees the same group blocks. |

---

## Smart LLM, RAG, and Distribution

### Smart LLM (routing and parameters)

- **Where:** Supervisor uses `LLMClient.route_task(user_prompt)` to get `executor_name` and `executor_params`.
- **How:** A detailed **system prompt** lists all 12 executors, their goals, required/optional parameters, and extraction rules (dates, days, times, course numbers, Hebrew/English). The LLM returns JSON: `executor_name`, `executor_params`, `reasoning`.
- **Fallback:** If the LLM is unavailable (no API key, network error, parse error), the supervisor uses `_fallback_pattern_matching(user_prompt)` (keywords for schedule, notifications, move, resize, constraints, etc.); default for unrecognized prompts is **rag_chat**.
- **Config:** `LLM_API_KEY` or `LLMOD_API_KEY`, `LLM_BASE_URL` / `LLMOD_BASE_URL`, `LLM_MODEL` / `LLMOD_MODEL` in `.env`.

### RAG (academic Q&A)

- **Executor:** `rag_chat`. Used for any informational/procedural question that does not require a specific action (add course, move block, etc.).
- **Pipeline:** Query → **embedding** (OpenAI-compatible API, e.g. LLMod) → **Pinecone** retrieval (TOP_K chunks, MIN_SCORE threshold) → **LLM** to generate an answer from retrieved context. Optional `user_context` and `ui_context` can be passed for personalized answers.
- **Data:** Academy docs (catalogs, attachments, course descriptions, optional CSV) in `rag_data/` and `rag_data_additional/`; chunked and embedded via `app.rag.embed_and_upsert`. Config: `app.rag.config` (RAG_DATA_DIR, PINECONE_INDEX_NAME, TOP_K, EMBEDDING_BASE_URL, etc.).

### Distribution (weekly plans)

- **Scope:** Weekly Planner can run for **all users** (e.g. `POST /api/system/weekly-plan/generate?week_start=...`) or for a **single user** (e.g. `POST /api/weekly-plan/generate?user_id=...`).
- **Steps:** (1) Clean up existing weekly plans and blocks for the target week. (2) For each user: load courses, constraints, group memberships; place **group blocks** with the LLM (common free time across members); place **personal blocks** and refine with the LLM. (3) **Sync:** Create/update `weekly_plan_blocks` for **every member** of each group so the same group block appears in each member’s plan.
- **Result:** Every user gets a consistent weekly plan; group meetings are aligned across members and respect preferences where possible.

---

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

### 3. Run the Server (local development only)

To run the app locally (e.g. for development):

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Or use the provided scripts:
- Windows CMD: `run_uvicorn.bat`
- PowerShell: `run_uvicorn.ps1`

**For normal use**, use the **deployed application** at **https://ds-project-499p.onrender.com** — all API examples in this README use that base URL.

## Features

- **User Authentication**: Login with username/password to get access token
- **Course Management**: Add courses from catalog to your course list
- **Schedule Retrieval**: View weekly schedule for any date
- **Courses Display**: View all courses you're taking this semester
- **Notifications**: View and clear unread notifications
- **Block Management**: Move study blocks (personal or group)
- **Group Management**: Create study groups and manage invitations
- **Request Handling**: Approve or reject group change requests

## API Usage Examples

The examples below use the **super user** (no authentication token). To act as a specific user, log in first and pass the token in the `Authorization: Bearer <token>` header.

### 1. Login (optional – for acting as a specific user)

**Windows CMD:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/auth/login" -H "Content-Type: application/json" -d "{\"username\":\"your_email@example.com\",\"password\":\"your_password\"}"
```

**PowerShell:**
```powershell
curl -X POST "https://ds-project-499p.onrender.com/api/auth/login" -H "Content-Type: application/json" -d '{\"username\":\"your_email@example.com\",\"password\":\"your_password\"}'
```

**Save token to variable (Windows CMD):**
```cmd
for /f "tokens=*" %i in ('curl -X POST "https://ds-project-499p.onrender.com/api/auth/login" -H "Content-Type: application/json" -d "{\"username\":\"your_email@example.com\",\"password\":\"your_password\"}"') do set TOKEN=%i
```

**Save token to variable (PowerShell):**
```powershell
$TOKEN = (curl -X POST "https://ds-project-499p.onrender.com/api/auth/login" -H "Content-Type: application/json" -d '{\"username\":\"your_email@example.com\",\"password\":\"your_password\"}' | ConvertFrom-Json).access_token
```

### 2. View Weekly Schedule

**Get schedule for specific week:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"show me my schedule for the week starting 2026/02/22\"}"
```

**Get current week schedule:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"show my schedule\"}"
```

**Alternative date formats:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"schedule for 2026-02-22\"}"
```

### 3. View Courses

**Get all courses for this semester:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"show me my courses\"}"
```

**Alternative prompts:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"what courses am I taking\"}"
```

**Hebrew prompts:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"מה הקורסים שלי\"}"
```

### 4. View Notifications

**Get all unread notifications:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"show notifications\"}"
```

**Alternative prompts:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"what are my notifications\"}"
```

### 5. Clear Notifications

**Mark all notifications as read:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"clear notifications\"}"
```

**Alternative prompts:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"mark all notifications as read\"}"
```

### 6. Move Study Block

**Move personal block:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"move block abc-123-def to day 2 at 14:00\"}"
```

**Move block with preference explanation (will be saved for learning):**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"move block abc-123-def to day 3 at 16:00 because I prefer to study in the afternoon\"}"
```

**Move group block (creates change request):**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"move group block xyz-789-abc to day 4 at 15:00\"}"
```

**Note:** Group blocks require approval from all group members. The system will create a change request and notify all members.

### 7. Create Study Group

```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"create study group for course 104043 named Algorithms Study Group and invite user1@example.com user2@example.com\"}"
```

### 8. Approve/Reject Requests

**Approve a request:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"approve request req-123-456\"}"
```

**Reject a request:**
```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/execute" -H "Content-Type: application/json" -d "{\"prompt\":\"reject request req-123-456\"}"
```

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
curl -X POST "https://ds-project-499p.onrender.com/api/system/weekly-plan/generate?week_start=2025-02-22"
```

**With optional API key** (if `SYSTEM_API_KEY` is set in `.env`):

```cmd
curl -X POST "https://ds-project-499p.onrender.com/api/system/weekly-plan/generate?week_start=2025-02-22&api_key=your_system_api_key"
```

**PowerShell:**
```powershell
curl -X POST "https://ds-project-499p.onrender.com/api/system/weekly-plan/generate?week_start=2025-04-12"
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

## Documentation

- **Agent architecture (for diagrams):** See `docs/agent_architecture_for_diagram.txt` for exact module names and connections (supervisor, 12 executors, Weekly Planner).
- **Manual schedule editing and group approval:** See [README_MANUAL_EDITING.md](README_MANUAL_EDITING.md) for drag-and-drop, change requests, and approval workflow.

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
