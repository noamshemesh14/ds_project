# 🖱️ Manual Schedule Editing & Group Approval System

## 📝 Overview

This system allows users to:
1. **Drag and drop personal study blocks** to reschedule them instantly
2. **Request changes to group meetings** with a democratic approval process
3. **Approve or reject** group change requests from notifications

---

## 🎯 Features

### 1. Personal Block Editing (Instant)
- **What**: Move your personal study blocks by dragging them
- **How**: Drag a blue block (👤 Personal) to a new time slot
- **Result**: Block moves immediately, no approval needed
- **Why**: You control your own study time

### 2. Group Meeting Changes (Approval Required)
- **What**: Propose new times for group meetings
- **How**: Drag a purple block (👥 Group) to a new time slot
- **Result**: Change request created, sent to all members
- **Why**: Group decisions require consensus

### 3. Approval Workflow (Democratic)
- **What**: All group members vote on proposed changes
- **How**: Click ✅ Approve or ❌ Reject in notifications
- **Result**: 
  - **All approve** → Change applied automatically
  - **Any reject** → Request cancelled, original time kept
- **Why**: Fair and transparent group coordination

---

## 🖼️ Visual Guide

### Personal Block (Blue)
```
┌────────────────────────────┐
│ 👤 מבוא למדעי המחשב        │  ← Drag this
│ אישי                       │
└────────────────────────────┘
     ↓ (drag & drop)
┌────────────────────────────┐
│ [New Time Slot]            │  ← Drop here
│ (available)                │
└────────────────────────────┘
     ↓
✅ Moved instantly!
```

### Group Block (Purple)
```
┌────────────────────────────┐
│ 👥 מבני נתונים - קבוצה     │  ← Drag this
│ קבוצתי                     │
└────────────────────────────┘
     ↓ (drag & drop)
┌────────────────────────────┐
│ [New Time Slot]            │  ← Drop here
│ (available)                │
└────────────────────────────┘
     ↓
┌─────────────────────────────────────────┐
│ 🔄 בקשת שינוי מפגש קבוצתי               │
│                                         │
│ ⚠️ דורש אישור מכל חברי הקבוצה          │
│                                         │
│ זמן נוכחי: רביעי 13:00                  │
│           →                              │
│ זמן מוצע: חמישי 15:00                   │
│                                         │
│ סיבת השינוי: ___________                │
│                                         │
│ [📤 שלח בקשה] [ביטול]                   │
└─────────────────────────────────────────┘
```

---

## 🔔 Notification Examples

### Change Request Notification
```
┌──────────────────────────────────────────────┐
│ ⚠️ בקשת שינוי מפגש: מבני נתונים - קבוצה     │
│                                              │
│ יוסי כהן מבקש לשנות מפגש מ-רביעי 13:00      │
│ ל-חמישי 15:00. נדרשת אישור מכל החברים.      │
│                                              │
│ לפני 5 דקות                                  │
│                                              │
│ ┌──────────────┐  ┌──────────────┐          │
│ │  ✅ אשר      │  │  ❌ דחה      │          │
│ └──────────────┘  └──────────────┘          │
└──────────────────────────────────────────────┘
```

### Approval Notification
```
┌──────────────────────────────────────────────┐
│ ✅ שינוי מפגש אושר: מבני נתונים - קבוצה      │
│                                              │
│ כל חברי הקבוצה אישרו את השינוי.             │
│ המפגש עודכן לחמישי 15:00.                   │
│                                              │
│ לפני דקה                                     │
└──────────────────────────────────────────────┘
```

### Rejection Notification
```
┌──────────────────────────────────────────────┐
│ ❌ שינוי מפגש נדחה: מבני נתונים - קבוצה      │
│                                              │
│ שרה לוי דחה את הבקשה לשנות את מועד המפגש.   │
│ הזמן המקורי נשמר: רביעי 13:00              │
│                                              │
│ לפני 2 דקות                                  │
└──────────────────────────────────────────────┘
```

---

## 🎮 Step-by-Step Usage

### Scenario A: Moving Personal Study Time

**Goal**: You want to move "מבוא למדעי המחשב" from Sunday 09:00 to Monday 14:00

1. Go to `http://localhost:8000/schedule`
2. Find the blue block "👤 מבוא למדעי המחשב" on Sunday at 09:00
3. Click and hold on the block
4. Drag it to Monday 14:00 slot
5. Release the mouse button
6. See alert: "✅ הבלוק הועבר בהצלחה!"
7. Schedule updates immediately
8. ✅ Done! Your study time is moved.

### Scenario B: Proposing Group Meeting Change

**Goal**: Change "מבני נתונים - קבוצה" from Wednesday 13:00 to Thursday 15:00

1. Go to `http://localhost:8000/schedule`
2. Find the purple block "👥 מבני נתונים - קבוצה" on Wednesday at 13:00
3. Click and hold on the block
4. Drag it to Thursday 15:00 slot
5. Release the mouse button
6. Modal opens: "🔄 בקשת שינוי מפגש קבוצתי"
7. See warning: "⚠️ דורש אישור מכל חברי הקבוצה"
8. (Optional) Enter reason: "יש לי מבחן ביום רביעי"
9. Click "📤 שלח בקשה"
10. See alert: "✅ בקשת השינוי נשלחה! ממתינים לאישור מ-3 חברי קבוצה."
11. ✅ Request sent! Wait for approvals.

### Scenario C: Approving/Rejecting as Group Member

**Context**: You receive notification that someone wants to change the meeting time

**Option 1: Approve**
1. Click notifications bell (🔔)
2. See notification: "⚠️ בקשת שינוי מפגש: מבני נתונים - קבוצה"
3. Read details: "יוסי כהן מבקש לשנות מפגש מ-רביעי 13:00 ל-חמישי 15:00"
4. Click "✅ אשר"
5. See alert: "Your approval recorded. Waiting for other members."
6. Wait for others to vote

**If you're the last to approve:**
- See alert: "All members approved! Change has been applied."
- Schedule updates automatically
- Everyone receives "✅ שינוי מפגש אושר" notification

**Option 2: Reject**
1. Click notifications bell (🔔)
2. See notification: "⚠️ בקשת שינוי מפגש: מבני נתונים - קבוצה"
3. Read details: "יוסי כהן מבקש לשנות מפגש..."
4. Click "❌ דחה"
5. Confirm: "האם אתה בטוח שברצונך לדחות את הבקשה?"
6. Click OK
7. See alert: "Change request rejected."
8. Everyone receives "❌ שינוי מפגש נדחה" notification
9. Original time preserved

---

## 🔒 Rules & Constraints

### What CAN Be Moved:
- ✅ Personal study blocks (blue, 👤)
- ✅ Group meeting blocks (purple, 👥) - with approval

### What CANNOT Be Moved:
- ❌ Hard constraint blocks (orange)
- ❌ Blocks that are currently being moved
- ❌ Past time slots (can't change history)

### Validation Checks:
- ✅ New slot must be available (not already occupied)
- ✅ New time must respect hard constraints
- ✅ Group changes require unanimous approval
- ✅ Cannot move to same location (no-op)

### Approval Requirements:
- **Personal blocks**: No approval needed (instant)
- **Group blocks**: Requires 100% approval from ALL active members
- **One rejection**: Entire request cancelled
- **Timeout**: Requests expire after 48 hours (auto-reject)

---

## 🎨 UI Indicators

### Drag States
| State | Visual | Description |
|-------|--------|-------------|
| **Idle** | Normal block | Block is ready to drag |
| **Hovering** | `cursor: grab` | Mouse over draggable block |
| **Dragging** | `opacity: 0.5`, `cursor: grabbing` | Block being dragged |
| **Drop Zone** | Blue dashed border, light blue background | Valid drop target |
| **Dropped** | `opacity: 1`, schedule updates | Block placed in new location |

### Block Types
| Type | Color | Icon | Draggable? | Approval? |
|------|-------|------|------------|-----------|
| **Personal** | Blue | 👤 | ✅ Yes | ❌ No |
| **Group** | Purple | 👥 | ✅ Yes | ✅ Yes |
| **Constraint** | Orange | 🚫 | ❌ No | N/A |

### Notification Types
| Type | Icon | Action Required? |
|------|------|------------------|
| **Change Request** | ⚠️ | ✅ Yes (Approve/Reject) |
| **Approved** | ✅ | ❌ No (Info only) |
| **Rejected** | ❌ | ❌ No (Info only) |
| **Weekly Schedule** | 📅 | ❌ No (Info only) |

---

## 🧪 Testing Guide

### Test 1: Personal Block Drag & Drop
```bash
# Setup
1. Go to /schedule
2. Ensure you have at least one blue block (personal study)

# Test
3. Hover over blue block → cursor should be "grab"
4. Click and drag → opacity should be 50%
5. Hover over empty slot → blue dashed border appears
6. Drop → alert "הבלוק הועבר בהצלחה!"
7. Schedule refreshes → block is in new location

# Success Criteria
✅ Block moves smoothly
✅ Visual feedback is clear
✅ Schedule updates immediately
✅ Backend logs: "User {id} moved personal block {block_id}"
```

### Test 2: Group Meeting Change Request
```bash
# Setup
1. Go to /schedule
2. Ensure you have at least one purple block (group meeting)
3. You should be in a group with at least 2 members

# Test
4. Drag purple block to new time
5. Drop → modal opens with warning
6. Enter reason: "Testing the system"
7. Click "שלח בקשה"
8. Check notifications for all group members

# Success Criteria
✅ Modal opens with correct info
✅ Request is created in database
✅ All members receive notification
✅ Backend logs: "Created group change request {request_id}"
```

### Test 3: Approval Workflow
```bash
# Setup (requires 2+ users in same group)
User A: Create change request (from Test 2)

# Test as User B
1. Log in as different user (group member)
2. Click notifications bell
3. See notification with Approve/Reject buttons
4. Click "אשר"
5. Check database: approval recorded

# Test as User C (last member)
6. Log in as third user (if applicable)
7. Click "אשר"
8. Check: All users' schedules should update automatically
9. Check: All members receive "אושר" notification

# Success Criteria
✅ Each approval is recorded
✅ Status updates after each vote
✅ Final approval triggers schedule update
✅ All members notified
```

### Test 4: Rejection Workflow
```bash
# Setup
User A: Create change request

# Test as User B
1. Log in as different user
2. Click notifications bell
3. Click "דחה"
4. Confirm rejection
5. Check: Request status = "rejected"
6. Check: All members receive "נדחה" notification
7. Check: Original time preserved

# Success Criteria
✅ Single rejection cancels request
✅ Status immediately becomes "rejected"
✅ All members notified
✅ Schedule unchanged
```

---

## 📊 Database Tables

### `group_meeting_change_requests`
```sql
id                     UUID PRIMARY KEY
group_id               UUID (FK → study_groups)
week_start             DATE
original_day_of_week   INTEGER (0-6)
original_start_time    TIME
proposed_day_of_week   INTEGER (0-6)
proposed_start_time    TIME
requested_by           UUID (FK → auth.users)
reason                 TEXT
status                 VARCHAR(20) -- 'pending', 'approved', 'rejected'
created_at             TIMESTAMP
resolved_at            TIMESTAMP
```

### `group_change_approvals`
```sql
id            UUID PRIMARY KEY
request_id    UUID (FK → group_meeting_change_requests)
user_id       UUID (FK → auth.users)
approved      BOOLEAN (true/false)
created_at    TIMESTAMP
responded_at  TIMESTAMP
```

---

## 🔧 API Endpoints

### Move Schedule Block
```http
POST /api/schedule/block/move
Authorization: Bearer {token}
Content-Type: application/json

{
  "block_id": "uuid",
  "new_day_of_week": 1,
  "new_start_time": "14:00"
}

Response 200:
{
  "message": "Block moved successfully",
  "block": { ...updated block... }
}

Response 400 (if group block):
{
  "error": "group_block",
  "message": "Group blocks require approval..."
}
```

### Create Change Request
```http
POST /api/schedule/group-change-request/create
Authorization: Bearer {token}
Content-Type: application/json

{
  "group_id": "uuid",
  "week_start": "2026-02-08",
  "original_day_of_week": 2,
  "original_start_time": "13:00",
  "proposed_day_of_week": 3,
  "proposed_start_time": "15:00",
  "reason": "יש לי מבחן"
}

Response 200:
{
  "message": "Change request created...",
  "request": { ...request object... },
  "members_to_approve": 3
}
```

### Approve Request
```http
POST /api/schedule/group-change-request/{request_id}/approve
Authorization: Bearer {token}

Response 200 (waiting):
{
  "message": "Your approval recorded. Waiting for others.",
  "status": "pending",
  "approved_count": 2,
  "total_members": 4
}

Response 200 (all approved):
{
  "message": "All members approved! Change has been applied.",
  "status": "approved"
}
```

### Reject Request
```http
POST /api/schedule/group-change-request/{request_id}/reject
Authorization: Bearer {token}

Response 200:
{
  "message": "Change request rejected.",
  "status": "rejected"
}
```

---

## 🐛 Troubleshooting

### Issue: Drag doesn't start
**Symptoms**: Click and drag, nothing happens
**Cause**: Block might not be start of multi-hour block
**Solution**: Only the first cell of a multi-hour block is draggable

### Issue: Drop doesn't work
**Symptoms**: Drop on cell, nothing happens
**Cause**: Cell might already be occupied or constrained
**Solution**: Drop on an available (white/light) cell

### Issue: Group modal doesn't open
**Symptoms**: Drag group block, no modal appears
**Cause**: JavaScript error or modal element missing
**Solution**: Check browser console for errors, hard refresh (Ctrl+Shift+R)

### Issue: Approve button doesn't work
**Symptoms**: Click approve, nothing happens
**Cause**: Request ID not extracted correctly
**Solution**: Check notification link format, ensure it contains `change_request=UUID`

### Issue: Change not applied after all approvals
**Symptoms**: All members approved, schedule unchanged
**Cause**: Database update failed or RLS policy blocking
**Solution**: Check server logs for errors, verify RLS policies in Supabase

---

## 🎯 Best Practices

### For Users
1. **Add reasons** when requesting group changes (helps others decide)
2. **Respond promptly** to change requests (they expire after 48h)
3. **Check constraints** before moving blocks (orange areas are blocked)
4. **Communicate** with your group outside the app for big changes

### For Developers
1. **Validate inputs** before sending to API
2. **Handle errors gracefully** (show user-friendly messages)
3. **Log all actions** for debugging
4. **Test with multiple users** (approval workflow requires it)

---

## 📈 Future Enhancements (Potential)

- [ ] Bulk move multiple blocks at once
- [ ] Copy/paste schedule blocks
- [ ] Suggest alternative times if drop fails
- [ ] Show approval status in real-time (who voted, who didn't)
- [ ] Allow requester to cancel pending requests
- [ ] Add expiration timer countdown in notifications
- [ ] Mobile touch support for drag-and-drop

---

## ✨ Summary

This system provides a **smooth, intuitive, and democratic** way to manage study schedules:

- **Personal blocks**: Instant flexibility
- **Group blocks**: Fair consensus process
- **Notifications**: Stay informed
- **Visual feedback**: Clear and intuitive

**Result**: Happy users, coordinated groups, optimized schedules! 🎉

---

**Last Updated**: February 1, 2026
**Version**: 1.0
**Status**: ✅ Production Ready

