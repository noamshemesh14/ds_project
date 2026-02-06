"""
Block Creator Executor
Creates new study blocks and adds them to the schedule
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
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


class BlockCreator:
    def __init__(self):
        self.module_name = "block_creator"

    async def execute(
        self,
        user_id: str,
        course_number: Optional[str] = None,
        course_name: Optional[str] = None,
        day_of_week: Optional[int] = None,
        start_time: Optional[str] = None,
        duration: Optional[int] = 1,
        work_type: Optional[str] = "personal",
        week_start: Optional[str] = None,
        user_prompt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a new study block and add it to the schedule.
        
        Validations:
        - Check for conflicts with existing blocks
        - Check for conflicts with hard constraints
        - Ensure the time slot is available
        """
        try:
            client = supabase_admin if supabase_admin else supabase
            if not client:
                raise HTTPException(status_code=500, detail="Supabase client not configured")
            
            if not course_number and not course_name:
                raise HTTPException(status_code=400, detail="course_number or course_name is required")
            
            if day_of_week is None:
                raise HTTPException(status_code=400, detail="day_of_week is required (0-6, where 0=Sunday)")
            
            if not start_time:
                raise HTTPException(status_code=400, detail="start_time is required (HH:MM format)")
            
            if duration is None or duration < 1:
                duration = 1
            
            if work_type not in ["personal", "group"]:
                work_type = "personal"
            
            logger.info(f"🆕 Creating new block: course={course_number or course_name}, day={day_of_week}, time={start_time}, duration={duration}h, type={work_type}")
            
            # Normalize week_start format
            if week_start:
                if "/" in week_start:
                    week_start = week_start.replace("/", "-")
            else:
                # Use current week (Sunday of current week)
                today = datetime.now()
                days_since_sunday = (today.weekday() + 1) % 7
                week_start_date = today - timedelta(days=days_since_sunday)
                week_start = week_start_date.strftime("%Y-%m-%d")
                logger.info(f"📅 No week specified, using current week: {week_start}")
            
            # Get or create plan for this week
            plan_result = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", week_start).limit(1).execute()
            if not plan_result.data:
                # Create new plan
                plan_result = client.table("weekly_plans").insert({
                    "user_id": user_id,
                    "week_start": week_start
                }).execute()
                if not plan_result.data:
                    raise HTTPException(status_code=500, detail="Failed to create weekly plan")
            
            plan_id = plan_result.data[0]["id"]
            
            # Get course name if not provided
            if not course_name:
                if course_number:
                    catalog_result = client.table("course_catalog").select("course_name").eq("course_number", course_number).limit(1).execute()
                    if catalog_result.data:
                        course_name = catalog_result.data[0].get("course_name", course_number)
                    else:
                        course_name = course_number
                else:
                    course_name = "Study Block"
            
            # Get course_number if not provided (try to find by course_name)
            if not course_number:
                catalog_result = client.table("course_catalog").select("course_number").ilike("course_name", f"%{course_name}%").limit(1).execute()
                if catalog_result.data:
                    course_number = catalog_result.data[0].get("course_number")
                else:
                    # Check user's courses
                    user_courses = client.table("courses").select("course_number").eq("user_id", user_id).ilike("course_name", f"%{course_name}%").limit(1).execute()
                    if user_courses.data:
                        course_number = user_courses.data[0].get("course_number")
            
            if not course_number:
                raise HTTPException(status_code=400, detail=f"Could not find course number for '{course_name}'. Please provide course_number.")
            
            # Normalize start_time format
            time_slots = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
            start_time_normalized = start_time
            if start_time not in time_slots:
                # Try to normalize (e.g., "8:00" -> "08:00")
                start_minutes = _time_to_minutes(start_time)
                # Find closest time slot
                closest_slot = None
                min_diff = float('inf')
                for slot in time_slots:
                    slot_minutes = _time_to_minutes(slot)
                    diff = abs(slot_minutes - start_minutes)
                    if diff < min_diff:
                        min_diff = diff
                        closest_slot = slot
                if closest_slot and min_diff <= 30:  # Within 30 minutes
                    start_time_normalized = closest_slot
                    logger.info(f"📝 Normalized start_time from {start_time} to {start_time_normalized}")
                else:
                    # Use the original time but validate it's in valid range
                    if start_minutes < _time_to_minutes("08:00") or start_minutes > _time_to_minutes("20:00"):
                        raise HTTPException(status_code=400, detail=f"Invalid start_time: {start_time}. Must be between 08:00 and 20:00")
            
            # Calculate end time
            start_idx = time_slots.index(start_time_normalized) if start_time_normalized in time_slots else None
            if start_idx is None:
                start_minutes = _time_to_minutes(start_time_normalized)
                end_minutes = start_minutes + (duration * 60)
                end_time = _minutes_to_time(end_minutes)
            else:
                end_idx = start_idx + duration
                if end_idx < len(time_slots):
                    end_time = time_slots[end_idx]
                else:
                    end_time = "21:00"
            
            # Check for conflicts
            conflict_reasons = []
            
            # Check 1: Weekly hard constraints
            weekly_constraints = client.table("weekly_constraints").select("*").eq("user_id", user_id).eq("week_start", week_start).execute()
            for constraint in (weekly_constraints.data or []):
                if not constraint.get("is_hard", True):
                    continue
                days_array = constraint.get("days", [])
                if isinstance(days_array, str):
                    try:
                        import json
                        days_array = json.loads(days_array)
                    except:
                        days_array = []
                if day_of_week in days_array:
                    c_start = _time_to_minutes(constraint.get("start_time", "00:00"))
                    c_end = _time_to_minutes(constraint.get("end_time", "00:00"))
                    block_start = _time_to_minutes(start_time_normalized)
                    block_end = _time_to_minutes(end_time)
                    if block_start < c_end and block_end > c_start:
                        conflict_reasons.append(f"Weekly hard constraint: {constraint.get('title', 'Constraint')} ({constraint.get('start_time')}-{constraint.get('end_time')})")
            
            # Check 2: Permanent hard constraints
            permanent_constraints = client.table("constraints").select("*").eq("user_id", user_id).execute()
            import json
            for constraint in (permanent_constraints.data or []):
                if not constraint.get("is_hard", True):
                    continue
                days_array = constraint.get("days", [])
                if isinstance(days_array, str):
                    try:
                        days_array = json.loads(days_array)
                    except:
                        days_array = []
                elif not isinstance(days_array, list):
                    days_array = []
                if day_of_week in days_array:
                    c_start = _time_to_minutes(constraint.get("start_time", "00:00"))
                    c_end = _time_to_minutes(constraint.get("end_time", "00:00"))
                    block_start = _time_to_minutes(start_time_normalized)
                    block_end = _time_to_minutes(end_time)
                    if block_start < c_end and block_end > c_start:
                        conflict_reasons.append(f"Permanent hard constraint: {constraint.get('title', 'Constraint')} ({constraint.get('start_time')}-{constraint.get('end_time')})")
            
            # Check 3: Existing blocks
            existing_blocks = client.table("weekly_plan_blocks").select("id, course_name, start_time, end_time").eq("plan_id", plan_id).eq("day_of_week", day_of_week).execute()
            block_start = _time_to_minutes(start_time_normalized)
            block_end = _time_to_minutes(end_time)
            for block in (existing_blocks.data or []):
                b_start = _time_to_minutes(block.get("start_time", "00:00"))
                b_end = _time_to_minutes(block.get("end_time", "00:00"))
                if block_start < b_end and block_end > b_start:
                    conflict_reasons.append(f"Existing block: {block.get('course_name', 'Course')} ({block.get('start_time')}-{block.get('end_time')})")
            
            # Check if it's a group block
            if work_type == "group":
                # For group blocks, create a change request instead of creating directly
                logger.info(f"📋 Creating group block - will create change request")
                
                # Find the group_id for this course
                group_members_result = client.table("group_members").select("group_id").eq("user_id", user_id).eq("status", "approved").execute()
                user_group_ids = [gm["group_id"] for gm in (group_members_result.data or [])]
                
                # Find group that matches this course
                group_id = None
                for gid in user_group_ids:
                    group_result = client.table("study_groups").select("course_id, course_number").eq("id", gid).limit(1).execute()
                    if group_result.data:
                        group_course = group_result.data[0].get("course_number") or group_result.data[0].get("course_id")
                        if str(group_course) == str(course_number):
                            group_id = gid
                            break
                
                if not group_id:
                    raise HTTPException(status_code=404, detail=f"Group not found for course {course_number}. You must be a member of a group for this course.")
                
                # Extract reason from user_prompt if available
                reason = ""
                if user_prompt:
                    reason = user_prompt
                
                # Calculate end_time for the proposed block
                if start_time_normalized in time_slots:
                    start_idx = time_slots.index(start_time_normalized)
                    end_idx = start_idx + duration
                    if end_idx < len(time_slots):
                        proposed_end_time = time_slots[end_idx]
                    else:
                        proposed_end_time = "21:00"
                else:
                    start_minutes = _time_to_minutes(start_time_normalized)
                    end_minutes = start_minutes + (duration * 60)
                    proposed_end_time = _minutes_to_time(end_minutes)
                
                # Check for conflicts before creating request
                if conflict_reasons:
                    conflict_message = "Cannot create change request - conflicts detected:\n" + "\n".join(conflict_reasons)
                    raise HTTPException(status_code=400, detail=conflict_message)
                
                # Create group change request (for adding a new block, there's no original)
                request_data = {
                    "group_id": group_id,
                    "week_start": week_start,
                    "request_type": "move",  # Using "move" type for adding new blocks
                    "original_day_of_week": None,  # No original block
                    "original_start_time": None,
                    "original_end_time": None,
                    "original_duration_hours": 0,
                    "proposed_day_of_week": day_of_week,
                    "proposed_start_time": start_time_normalized,
                    "proposed_end_time": proposed_end_time,
                    "proposed_duration_hours": duration,
                    "requested_by": user_id,
                    "reason": reason,
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
                
                # Get group name and requester name
                group_result = client.table("study_groups").select("group_name, course_name").eq("id", group_id).limit(1).execute()
                group_name = group_result.data[0].get("group_name", "Group") if group_result.data else "Group"
                
                requester_result = client.table("user_profiles").select("name").eq("id", user_id).limit(1).execute()
                requester_name = requester_result.data[0].get("name", "A member") if requester_result.data else "A member"
                
                # Day names for display
                day_names = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
                proposed_time_str = f"{day_names[day_of_week]} {start_time_normalized}-{proposed_end_time}"
                
                title = f"בקשת הוספת מפגש: {group_name}"
                message = f"{requester_name} מבקש להוסיף מפגש חדש ב-{proposed_time_str} ({duration} שעות). נדרש אישור מכל החברים."
                if reason:
                    message += f" סיבה: {reason}"
                
                # Send notifications to all members
                for member_id in member_ids:
                    try:
                        client.table("notifications").insert({
                            "user_id": member_id,
                            "type": "group_change_request",
                            "title": title,
                            "message": message,
                            "link": f"/schedule?change_request={request_id}",
                            "read": False
                        }).execute()
                    except Exception as notif_err:
                        logger.error(f"Failed to notify member {member_id}: {notif_err}")
                
                logger.info(f"✅ Created group change request {request_id} for group {group_id}")
                
                return {
                    "status": "success",
                    "message": f"Change request created for adding {duration}h group block. Waiting for approval from all members.",
                    "request_id": request_id,
                    "members_to_approve": len(member_ids),
                    "has_conflicts": False,
                    "conflicts": []
                }
            
            # It's a personal block - create it directly
            if conflict_reasons:
                conflict_message = "Cannot create block - conflicts detected:\n" + "\n".join(conflict_reasons)
                raise HTTPException(status_code=400, detail=conflict_message)
            
            # Create the blocks
            time_slots_for_block = []
            if start_time_normalized in time_slots:
                start_idx = time_slots.index(start_time_normalized)
                for i in range(duration):
                    if start_idx + i < len(time_slots):
                        time_slots_for_block.append(time_slots[start_idx + i])
            else:
                # Use the original time and calculate consecutive hours
                time_slots_for_block = [start_time_normalized]
                for i in range(1, duration):
                    next_minutes = _time_to_minutes(start_time_normalized) + (i * 60)
                    time_slots_for_block.append(_minutes_to_time(next_minutes))
            
            new_blocks = []
            for i, slot_time in enumerate(time_slots_for_block):
                if i + 1 < len(time_slots_for_block):
                    slot_end = time_slots_for_block[i + 1]
                elif slot_time in time_slots:
                    slot_idx = time_slots.index(slot_time)
                    if slot_idx + 1 < len(time_slots):
                        slot_end = time_slots[slot_idx + 1]
                    else:
                        slot_end = "21:00"
                else:
                    slot_end = _minutes_to_time(_time_to_minutes(slot_time) + 60)
                
                new_blocks.append({
                    "plan_id": plan_id,
                    "user_id": user_id,
                    "course_number": course_number,
                    "course_name": course_name,
                    "work_type": work_type,
                    "day_of_week": day_of_week,
                    "start_time": slot_time,
                    "end_time": slot_end,
                    "source": "manual"
                })
            
            if new_blocks:
                insert_result = client.table("weekly_plan_blocks").insert(new_blocks).execute()
                logger.info(f"✅ Created {len(new_blocks)} new block(s)")
            
            # Update course_time_preferences based on ALL blocks in the plan
            try:
                # Get all blocks for this course in the plan to calculate actual distribution
                all_course_blocks = client.table("weekly_plan_blocks").select("work_type").eq("plan_id", plan_id).eq("course_number", course_number).execute()
                
                new_personal_hours = float(sum(1 for b in (all_course_blocks.data or []) if b.get("work_type") == "personal"))
                new_group_hours = float(sum(1 for b in (all_course_blocks.data or []) if b.get("work_type") == "group"))
                
                # Get current preferences for weighted average (80% existing, 20% new)
                current_pref_result = client.table("course_time_preferences").select("personal_hours_per_week, group_hours_per_week").eq("user_id", user_id).eq("course_number", course_number).limit(1).execute()
                
                if current_pref_result.data and current_pref_result.data[0].get("personal_hours_per_week") is not None:
                    # Convert to float to handle decimal values
                    current_personal_hours = float(current_pref_result.data[0]["personal_hours_per_week"])
                    current_group_hours = float(current_pref_result.data[0].get("group_hours_per_week", 0))
                    
                    # Weighted average: 80% existing, 20% new (keep as decimal)
                    personal_hours = round(0.8 * current_personal_hours + 0.2 * new_personal_hours, 2)
                    group_hours = round(0.8 * current_group_hours + 0.2 * new_group_hours, 2)
                else:
                    # No existing preferences, use new values (as decimal)
                    personal_hours = new_personal_hours
                    group_hours = new_group_hours
                
                client.table("course_time_preferences").upsert({
                    "user_id": user_id,
                    "course_number": course_number,
                    "personal_hours_per_week": personal_hours,
                    "group_hours_per_week": group_hours
                }, on_conflict="user_id,course_number").execute()
                
                logger.info(f"✅ Updated course_time_preferences: personal={personal_hours}h (from {new_personal_hours}h in blocks), group={group_hours}h (from {new_group_hours}h in blocks)")
            except Exception as pref_err:
                logger.warning(f"⚠️ Failed to update course_time_preferences: {pref_err}")
            
            return {
                "status": "success",
                "message": f"Created {duration}h block for {course_name} on day {day_of_week} at {start_time_normalized}",
                "blocks_created": len(new_blocks),
                "course_number": course_number,
                "course_name": course_name,
                "day_of_week": day_of_week,
                "start_time": start_time_normalized,
                "end_time": end_time,
                "duration": duration,
                "work_type": work_type
            }
            
        except HTTPException as http_exc:
            logger.error(f"❌ HTTPException in block_creator: {http_exc.detail}")
            raise
        except Exception as e:
            logger.error(f"❌ Error creating block: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            error_detail = str(e) if str(e) else "Unknown error occurred"
            raise HTTPException(status_code=500, detail=f"Error creating block: {error_detail}")

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

