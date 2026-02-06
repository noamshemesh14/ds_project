"""
Block Resizer Executor
Resizes study blocks (changes duration)
"""
import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime
from app.supabase_client import supabase, supabase_admin
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def _time_to_minutes(time_str: str) -> int:
    """Convert time string (HH:MM or HH:MM:SS) to minutes since midnight"""
    if not time_str:
        return 0
    parts = time_str.split(":")
    if len(parts) < 2:
        return 0
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        return hours * 60 + minutes
    except:
        return 0


def _minutes_to_time(minutes: int) -> str:
    """Convert minutes since midnight to time string (HH:MM)"""
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"


class BlockResizer:
    def __init__(self):
        self.module_name = "block_resizer"

    async def execute(
        self,
        user_id: str,
        block_id: Optional[str] = None,
        course_name: Optional[str] = None,
        course_number: Optional[str] = None,
        day_of_week: Optional[int] = None,
        start_time: Optional[str] = None,
        new_duration: Optional[int] = None,
        week_start: Optional[str] = None,
        user_prompt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Resize a study block (change duration).
        
        For personal blocks: Updates directly and updates course_time_preferences.personal_hours_per_week
        For group blocks: Creates a change request (requires approval) and updates course_time_preferences.group_hours_per_week after approval
        """
        try:
            client = supabase_admin if supabase_admin else supabase
            if not client:
                raise HTTPException(status_code=500, detail="Supabase client not configured")
            
            if not new_duration or new_duration < 1:
                raise HTTPException(status_code=400, detail="new_duration is required and must be at least 1 hour")
            
            # Normalize week_start format
            if week_start:
                if "/" in week_start:
                    week_start = week_start.replace("/", "-")
            
            # Find the block
            block = None
            if block_id:
                logger.info(f"🔄 Looking up block by ID: {block_id}")
                block_result = client.table("weekly_plan_blocks").select("*").eq("id", block_id).eq("user_id", user_id).limit(1).execute()
                if block_result.data:
                    block = block_result.data[0]
            else:
                # Find block by course + day + time + week
                if not (course_name or course_number) or day_of_week is None or not start_time:
                    raise HTTPException(
                        status_code=400,
                        detail="Either block_id is required, or course_name/course_number + day_of_week + start_time + week_start are required"
                    )
                
                # Determine which week to search in
                if not week_start:
                    # Use current week (Sunday of current week)
                    from datetime import datetime, timedelta
                    today = datetime.now()
                    days_since_sunday = (today.weekday() + 1) % 7
                    week_start_date = today - timedelta(days=days_since_sunday)
                    week_start = week_start_date.strftime("%Y-%m-%d")
                    logger.info(f"📅 No week specified, using current week: {week_start}")
                
                # Get plan for the specified week
                plan_result = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", week_start).limit(1).execute()
                if not plan_result.data:
                    raise HTTPException(status_code=404, detail=f"No schedule found for week starting {week_start}")
                
                plan_id = plan_result.data[0]["id"]
                
                # Search for block
                query = client.table("weekly_plan_blocks").select("*").eq("plan_id", plan_id).eq("user_id", user_id).eq("day_of_week", day_of_week).eq("start_time", start_time)
                
                if course_number:
                    query = query.eq("course_number", course_number)
                elif course_name:
                    query = query.eq("course_name", course_name)
                
                block_result = query.limit(1).execute()
                if not block_result.data:
                    raise HTTPException(status_code=404, detail=f"Block not found for course '{course_name or course_number}' on day {day_of_week} at {start_time}")
                
                block = block_result.data[0]
            
            if not block:
                raise HTTPException(status_code=404, detail="Block not found")
            
            logger.info(f"✅ Found block: {block.get('course_name')} ({block.get('course_number')}) on day {block.get('day_of_week')} at {block.get('start_time')}")
            
            # Check if user owns this block
            if block["user_id"] != user_id:
                raise HTTPException(status_code=403, detail="Not authorized to resize this block")
            
            work_type = block.get("work_type", "personal")
            course_number = block.get("course_number")
            course_name = block.get("course_name", "")
            original_day = block.get("day_of_week")
            original_start = block.get("start_time")
            original_end = block.get("end_time")
            
            # Calculate original duration
            original_start_minutes = _time_to_minutes(original_start)
            original_end_minutes = _time_to_minutes(original_end) if original_end else original_start_minutes + 60
            original_duration = (original_end_minutes - original_start_minutes) // 60
            
            # Get week_start from the block's plan
            if not week_start:
                plan_result = client.table("weekly_plans").select("week_start").eq("id", block["plan_id"]).limit(1).execute()
                week_start = plan_result.data[0]["week_start"] if plan_result.data else None
            
            # Check if it's a group block
            if work_type == "group":
                # For group blocks, create a change request instead of resizing directly
                logger.info(f"📋 Block is a group block - creating resize change request")
                
                # Find the group_id
                group_plan_blocks_result = client.table("group_plan_blocks").select("group_id").eq("week_start", week_start).eq("course_number", course_number).eq("day_of_week", original_day).eq("start_time", original_start).limit(1).execute()
                
                if not group_plan_blocks_result.data:
                    # Fallback: try to find by course_number and user's groups
                    group_members_result = client.table("group_members").select("group_id").eq("user_id", user_id).eq("status", "approved").execute()
                    user_group_ids = [gm["group_id"] for gm in (group_members_result.data or [])]
                    
                    group_id = None
                    for gid in user_group_ids:
                        group_result = client.table("study_groups").select("course_id, course_number").eq("id", gid).limit(1).execute()
                        if group_result.data:
                            group_course = group_result.data[0].get("course_number") or group_result.data[0].get("course_id")
                            if str(group_course) == str(course_number):
                                group_id = gid
                                break
                    
                    if not group_id:
                        raise HTTPException(status_code=404, detail="Group not found for this block")
                else:
                    group_id = group_plan_blocks_result.data[0]["group_id"]
                
                # Extract reason from user_prompt if available
                hours_explanation = ""
                if user_prompt:
                    hours_explanation = user_prompt
                
                # Create group change request
                request_data = {
                    "group_id": group_id,
                    "week_start": week_start,
                    "request_type": "resize",
                    "original_day_of_week": original_day,
                    "original_start_time": original_start,
                    "original_end_time": original_end,
                    "original_duration_hours": original_duration,
                    "proposed_day_of_week": original_day,  # Keep same day for resize
                    "proposed_start_time": original_start,  # Keep same start time for resize
                    "proposed_duration_hours": new_duration,
                    "requested_by": user_id,
                    "hours_explanation": hours_explanation,
                    "status": "pending"
                }
                
                request_result = client.table("group_meeting_change_requests").insert(request_data).execute()
                if not request_result.data:
                    raise HTTPException(status_code=500, detail="Failed to create change request")
                
                change_request = request_result.data[0]
                request_id = change_request["id"]
                
                # Get all group members (except requester)
                members_result = client.table("group_members").select("user_id").eq("group_id", group_id).eq("status", "approved").execute()
                member_ids = [m["user_id"] for m in (members_result.data or []) if m["user_id"] != user_id]
                
                # Send notifications to all other members
                for member_id in member_ids:
                    try:
                        client.table("notifications").insert({
                            "user_id": member_id,
                            "type": "group_change_request",
                            "title": f"בקשה לשינוי משך מפגש",
                            "message": f"בקשה להגדיל/להקטין את משך המפגש מ-{original_duration} שעות ל-{new_duration} שעות",
                            "link": f"/schedule?change_request={request_id}",
                            "read": False
                        }).execute()
                    except Exception as notif_err:
                        logger.error(f"Failed to notify member {member_id}: {notif_err}")
                
                logger.info(f"✅ Created group resize change request {request_id} for group {group_id}")
                
                return {
                    "status": "success",
                    "message": f"Change request created. Waiting for approval from all members.",
                    "request_id": request_id,
                    "members_to_approve": len(member_ids),
                    "has_conflicts": False,
                    "conflicts": []
                }
            
            # It's a personal block - resize it directly
            logger.info(f"📦 Resizing personal block: {original_duration}h -> {new_duration}h")
            
            plan_id = block["plan_id"]
            time_slots = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
            
            # Find all consecutive blocks for the same course and work_type starting from original_start
            all_blocks_for_resize = client.table("weekly_plan_blocks").select("id, start_time, end_time").eq("plan_id", plan_id).eq("course_number", course_number).eq("work_type", work_type).eq("day_of_week", original_day).order("start_time").execute()
            
            # Find the starting block and all consecutive blocks
            consecutive_blocks = []
            starting_block = None
            for b in (all_blocks_for_resize.data or []):
                if b.get("start_time") == original_start:
                    starting_block = b
                    consecutive_blocks.append(b)
                    break
            
            if starting_block:
                current_end_time = starting_block.get("end_time")
                for b in (all_blocks_for_resize.data or []):
                    if b["id"] == starting_block["id"]:
                        continue
                    block_start = b.get("start_time")
                    if block_start == current_end_time:
                        consecutive_blocks.append(b)
                        current_end_time = b.get("end_time")
                    elif _time_to_minutes(block_start) > _time_to_minutes(current_end_time):
                        break
            
            # Calculate the current duration (number of consecutive blocks)
            current_duration = len(consecutive_blocks) if consecutive_blocks else 1
            duration_diff = new_duration - current_duration
            
            logger.info(f"📊 Current duration: {current_duration}h, New duration: {new_duration}h, Difference: {duration_diff}h")
            
            # Check for conflicts if increasing duration
            if duration_diff > 0:
                # Calculate new end time
                start_idx = time_slots.index(original_start) if original_start in time_slots else 0
                new_end_idx = start_idx + new_duration
                new_end_time = time_slots[new_end_idx] if new_end_idx < len(time_slots) else "21:00"
                
                new_start_minutes = _time_to_minutes(original_start)
                new_end_minutes = _time_to_minutes(new_end_time)
                
                # Check conflicts with constraints
                conflict_reasons = []
                
                # Check weekly constraints
                if week_start:
                    weekly_constraints = client.table("weekly_constraints").select("*").eq("user_id", user_id).eq("week_start", week_start).execute()
                    for constraint in (weekly_constraints.data or []):
                        if not constraint.get("is_hard", True):
                            continue
                        days_array = constraint.get("days", [])
                        if isinstance(days_array, str):
                            try:
                                days_array = json.loads(days_array)
                            except:
                                days_array = []
                        if original_day in days_array:
                            c_start = _time_to_minutes(constraint.get("start_time", "00:00"))
                            c_end = _time_to_minutes(constraint.get("end_time", "00:00"))
                            if new_start_minutes < c_end and new_end_minutes > c_start:
                                conflict_reasons.append(f"Weekly hard constraint: {constraint.get('title', 'Constraint')} ({constraint.get('start_time')}-{constraint.get('end_time')})")
                
                # Check permanent constraints
                permanent_constraints = client.table("constraints").select("*").eq("user_id", user_id).execute()
                for constraint in (permanent_constraints.data or []):
                    if not constraint.get("is_hard", True):
                        continue
                    days_array = constraint.get("days", [])
                    if isinstance(days_array, str):
                        try:
                            days_array = json.loads(days_array)
                        except:
                            days_array = []
                    if original_day in days_array:
                        c_start = _time_to_minutes(constraint.get("start_time", "00:00"))
                        c_end = _time_to_minutes(constraint.get("end_time", "00:00"))
                        if new_start_minutes < c_end and new_end_minutes > c_start:
                            conflict_reasons.append(f"Permanent hard constraint: {constraint.get('title', 'Constraint')} ({constraint.get('start_time')}-{constraint.get('end_time')})")
                
                # Check conflicts with other blocks (different courses)
                all_blocks = client.table("weekly_plan_blocks").select("id, course_name, start_time, end_time").eq("plan_id", plan_id).eq("day_of_week", original_day).execute()
                for existing_block in (all_blocks.data or []):
                    # Skip blocks we're resizing (same course)
                    if existing_block.get("course_number") == course_number and existing_block.get("work_type") == work_type:
                        continue
                    block_start_minutes = _time_to_minutes(existing_block.get("start_time", "00:00"))
                    block_end_minutes = _time_to_minutes(existing_block.get("end_time", "00:00"))
                    if new_start_minutes < block_end_minutes and new_end_minutes > block_start_minutes:
                        conflict_reasons.append(f"Existing block: {existing_block.get('course_name', 'Course')} ({existing_block.get('start_time')}-{existing_block.get('end_time')})")
                
                if conflict_reasons:
                    conflict_message = "Cannot resize block - conflicts detected:\n" + "\n".join(conflict_reasons)
                    raise HTTPException(status_code=400, detail=conflict_message)
            
            # Delete old blocks
            if consecutive_blocks:
                for b in consecutive_blocks:
                    client.table("weekly_plan_blocks").delete().eq("id", b["id"]).execute()
                logger.info(f"✅ Deleted {len(consecutive_blocks)} old blocks")
            
            # Create new blocks
            start_idx = time_slots.index(original_start) if original_start in time_slots else 0
            new_blocks = []
            for i in range(new_duration):
                if start_idx + i < len(time_slots):
                    new_time = time_slots[start_idx + i]
                    new_end = time_slots[start_idx + i + 1] if (start_idx + i + 1) < len(time_slots) else "21:00"
                    new_blocks.append({
                        "plan_id": plan_id,
                        "user_id": user_id,
                        "course_number": course_number,
                        "course_name": course_name,
                        "work_type": work_type,
                        "day_of_week": original_day,
                        "start_time": new_time,
                        "end_time": new_end,
                        "source": "manual"
                    })
            
            if new_blocks:
                insert_result = client.table("weekly_plan_blocks").insert(new_blocks).execute()
                logger.info(f"✅ Created {len(new_blocks)} new blocks")
            
            # Update course_time_preferences.personal_hours_per_week
            try:
                # Get current preferences
                pref_result = client.table("course_time_preferences").select("personal_hours_per_week").eq("user_id", user_id).eq("course_number", course_number).limit(1).execute()
                
                if pref_result.data:
                    current_personal_hours = pref_result.data[0].get("personal_hours_per_week", 0)
                    # Apply weighted average: 80% existing, 20% new
                    new_personal_hours = int(0.8 * current_personal_hours + 0.2 * new_duration)
                    
                    client.table("course_time_preferences").update({
                        "personal_hours_per_week": new_personal_hours
                    }).eq("user_id", user_id).eq("course_number", course_number).execute()
                    
                    logger.info(f"✅ Updated course_time_preferences: personal_hours={current_personal_hours}h -> {new_personal_hours}h (weighted average)")
                else:
                    # Create new entry
                    # Get course credit_points to calculate default
                    course_result = client.table("courses").select("credit_points").eq("user_id", user_id).eq("course_number", course_number).limit(1).execute()
                    credit_points = course_result.data[0].get("credit_points") if course_result.data else 3
                    total_hours = credit_points * 3
                    default_group_hours = max(1, int(total_hours * 0.5))
                    
                    client.table("course_time_preferences").insert({
                        "user_id": user_id,
                        "course_number": course_number,
                        "personal_hours_per_week": new_duration,
                        "group_hours_per_week": default_group_hours
                    }).execute()
                    
                    logger.info(f"✅ Created course_time_preferences: personal_hours={new_duration}h")
            except Exception as pref_err:
                logger.warning(f"⚠️ Failed to update course_time_preferences: {pref_err}")
            
            return {
                "status": "success",
                "message": f"Block resized successfully from {current_duration}h to {new_duration}h",
                "original_duration": current_duration,
                "new_duration": new_duration
            }
            
        except HTTPException as http_exc:
            logger.error(f"❌ HTTPException in block_resizer: {http_exc.detail}")
            raise
        except Exception as e:
            logger.error(f"❌ Error resizing block: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            error_detail = str(e) if str(e) else "Unknown error occurred"
            raise HTTPException(status_code=500, detail=f"Error resizing block: {error_detail}")

    def get_step_log(
        self,
        prompt: Dict[str, Any],
        response: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "module": self.module_name,
            "prompt": prompt,
            "response": response
        }
