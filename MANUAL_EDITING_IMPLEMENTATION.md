# Manual Schedule Editing & Group Change Requests - Implementation Plan

## Features to Implement

### 1. Manual Drag-and-Drop Editing (Section 3.1)
- ✅ Drag and resize personal study blocks
- ✅ Immediate visual feedback
- ✅ Save changes to database
- ❌ Do NOT log as preference signals (per user request)

### 2. Group Meeting Change Requests (Section 3.2)
- ✅ Cannot move group meetings unilaterally
- ✅ Clicking group meeting opens change request dialog
- ✅ Notifications sent to all group members
- ✅ Approval/rejection workflow
- ✅ Unanimous approval required
- ✅ Auto-revert if rejected

### 3. Database Tables Needed

```sql
-- Group meeting change requests table
CREATE TABLE IF NOT EXISTS group_meeting_change_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id UUID REFERENCES study_groups(id) ON DELETE CASCADE,
    original_block_id UUID, -- Reference to group_plan_blocks
    proposed_day_of_week INTEGER,
    proposed_start_time TEXT,
    proposed_end_time TEXT,
    requested_by UUID REFERENCES auth.users(id),
    status TEXT DEFAULT 'pending', -- pending, approved, rejected
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP DEFAULT (NOW() + INTERVAL '48 hours')
);

-- Approvals table
CREATE TABLE IF NOT EXISTS group_change_approvals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id UUID REFERENCES group_meeting_change_requests(id) ON DELETE CASCADE,
    user_id UUID REFERENCES auth.users(id),
    approved BOOLEAN,
    responded_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(request_id, user_id)
);
```

### 4. API Endpoints Needed

```
POST /api/schedule/block/move
  - Move personal block (immediate)
  - For group blocks: create change request

POST /api/schedule/group-change-request/create
  - Create group meeting change request

GET /api/schedule/group-change-requests
  - Get pending requests for user

POST /api/schedule/group-change-request/{id}/approve
  - Approve a change request

POST /api/schedule/group-change-request/{id}/reject
  - Reject a change request
```

### 5. UI Changes

**schedule.html**:
- Add draggable attribute to personal blocks
- Add click handler to group blocks (opens change request modal)
- Add change request modal/dialog
- Add approval notifications

**Notification System**:
- Show group change requests in notifications widget
- Allow approve/reject from notifications

---

## Implementation Status

This document outlines what NEEDS to be done. 
Implementing NOW...

