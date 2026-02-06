"""
Block Mover Executor
Moves study blocks to different times
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
    hour = int(parts[0])
    minute = int(parts[1])
    return hour * 60 + minute


def _minutes_to_time(minutes: int) -> str:
    """Convert minutes since midnight to time string (HH:MM)"""
    hour = minutes // 60
    minute = minutes % 60
    return f"{hour:02d}:{minute:02d}"


class BlockMover:
    """
    Moves study blocks
    """
    
    def __init__(self):
        self.module_name = "block_mover"
    
    async def execute(
        self,
        user_id: str,
        block_id: Optional[str] = None,
        course_name: Optional[str] = None,
        course_number: Optional[str] = None,
        original_day: Optional[int] = None,
        original_start_time: Optional[str] = None,
        original_end_time: Optional[str] = None,
        new_day: Optional[int] = None,
        new_start_time: Optional[str] = None,
        new_end_time: Optional[str] = None,
        user_prompt: Optional[str] = None,
        week_start: Optional[str] = None,
        specific_hours_only: Optional[bool] = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Move a study block
        
        Args:
            user_id: User ID
            block_id: Block ID to move (optional, can find by course + day + time)
            course_name: Course name to identify block (required if block_id not provided)
            course_number: Course number to identify block (alternative to course_name)
            original_day: Current day of week (0-6, required if block_id not provided)
            original_start_time: Current start time (HH:MM, required if block_id not provided)
            new_day: New day of week (0-6, 0=Sunday)
            new_start_time: New start time (HH:MM)
            new_end_time: New end time (HH:MM) - optional, will be calculated if not provided
            user_prompt: Original user prompt (for preference extraction)
            week_start: Week start date (YYYY-MM-DD, optional, will use current week if not provided)
            **kwargs: Additional parameters
        
        Returns:
            Dict with move result
        """
        try:
            client = supabase_admin if supabase_admin else supabase
            if not client:
                raise HTTPException(status_code=500, detail="Supabase client not configured")
            
            if not new_start_time:
                raise HTTPException(status_code=400, detail="new_start_time is required")
            
            # Normalize time format (e.g., "012:00" -> "12:00", "8:00" -> "08:00")
            if original_start_time:
                original_start_time = self._normalize_time(original_start_time)
            if new_start_time:
                new_start_time = self._normalize_time(new_start_time)
            if new_end_time:
                new_end_time = self._normalize_time(new_end_time)
            
            # If new_day is not provided, use the same day as original_day (moving time only)
            if new_day is None:
                if original_day is not None:
                    new_day = original_day
                    logger.info(f"📅 No new_day specified, using same day: {new_day}")
                else:
                    # We'll find original_day from the block
                    pass
            
            # Find the block - either by block_id or by course + day + time
            block = None
            
            if block_id:
                logger.info(f"🔄 Looking up block by ID: {block_id}")
                block_result = client.table("weekly_plan_blocks").select("*").eq("id", block_id).eq("user_id", user_id).limit(1).execute()
                if block_result.data:
                    block = block_result.data[0]
            else:
                # Find block by course name/number + day + time
                # Note: original_day and original_start_time are optional - if not provided, search across all days/times
                if not (course_name or course_number):
                    raise HTTPException(
                        status_code=400,
                        detail="Either block_id is required, or course_name/course_number is required"
                    )
                
                if original_start_time is None:
                    if original_day is None:
                        logger.info(f"🔍 Looking up block by course: {course_name or course_number} (day and time not specified, will search all days and times)")
                    else:
                        logger.info(f"🔍 Looking up block by course: {course_name or course_number}, day {original_day} (time not specified, will search all times on this day)")
                else:
                    if original_day is None:
                        logger.info(f"🔍 Looking up block by course: {course_name or course_number}, time {original_start_time} (day not specified, will search all days)")
                    else:
                        logger.info(f"🔍 Looking up block by course: {course_name or course_number}, day {original_day}, time {original_start_time}")
                
                # Determine which week to search in
                if not week_start:
                    # Use current week (Sunday of current week)
                    from datetime import datetime, timedelta
                    today = datetime.now()
                    days_since_sunday = (today.weekday() + 1) % 7
                    week_start_date = today - timedelta(days=days_since_sunday)
                    week_start = week_start_date.strftime("%Y-%m-%d")
                    logger.info(f"📅 No week specified, using current week: {week_start}")
                else:
                    # Normalize date format (YYYY/MM/DD -> YYYY-MM-DD)
                    if "/" in week_start:
                        week_start = week_start.replace("/", "-")
                    logger.info(f"📅 Using specified week: {week_start}")
                
                # Get plan for the specified week
                plan_result = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", week_start).limit(1).execute()
                if not plan_result.data:
                    # Try to find any plan for this user to see what weeks are available
                    all_plans = client.table("weekly_plans").select("week_start").eq("user_id", user_id).order("week_start", desc=True).limit(5).execute()
                    available_weeks = [p["week_start"] for p in (all_plans.data or [])]
                    error_msg = f"No schedule found for week starting {week_start}. Available weeks: {available_weeks if available_weeks else 'none'}"
                    logger.error(f"❌ {error_msg}")
                    raise HTTPException(status_code=404, detail=error_msg)
                
                plan_id = plan_result.data[0]["id"]
                logger.info(f"📅 Found plan {plan_id} for week {week_start}")
                
                # Search for block by course and time in this plan
                query = client.table("weekly_plan_blocks").select("*").eq("plan_id", plan_id).eq("user_id", user_id)
                
                # Add time filter only if original_start_time is provided
                if original_start_time is not None:
                    query = query.eq("start_time", original_start_time)
                
                # Add day filter only if original_day is provided
                if original_day is not None:
                    query = query.eq("day_of_week", original_day)
                
                if course_number:
                    query = query.eq("course_number", course_number)
                    logger.info(f"🔍 Searching by course_number: {course_number}")
                elif course_name:
                    query = query.eq("course_name", course_name)
                    logger.info(f"🔍 Searching by course_name: {course_name}")
                
                block_result = query.limit(1).execute()
                logger.info(f"🔍 Exact match query returned {len(block_result.data) if block_result.data else 0} blocks")
                
                if not block_result.data:
                    # Try fuzzy match on course name (partial match)
                    logger.info(f"🔍 Trying fuzzy match for course name: {course_name}")
                    fuzzy_query = client.table("weekly_plan_blocks").select("*").eq("plan_id", plan_id).eq("user_id", user_id)
                    if original_start_time is not None:
                        fuzzy_query = fuzzy_query.eq("start_time", original_start_time)
                    if original_day is not None:
                        fuzzy_query = fuzzy_query.eq("day_of_week", original_day)
                    all_blocks = fuzzy_query.execute()
                    day_info = f"day {original_day}" if original_day is not None else "any day"
                    time_info = f"at {original_start_time}" if original_start_time is not None else "at any time"
                    logger.info(f"🔍 Found {len(all_blocks.data) if all_blocks.data else 0} blocks on {day_info} {time_info}")
                    
                    if course_name and all_blocks.data:
                        for b in all_blocks.data:
                            block_course_name = b.get("course_name", "")
                            logger.info(f"🔍 Comparing '{course_name}' with '{block_course_name}'")
                            if course_name.lower() in block_course_name.lower() or block_course_name.lower() in course_name.lower():
                                block = b
                                logger.info(f"✅ Found fuzzy match: {block_course_name}")
                                break
                    
                    if not block:
                        # List available blocks for debugging
                        available_blocks = []
                        if all_blocks.data:
                            for b in all_blocks.data:
                                available_blocks.append({
                                    "course_name": b.get("course_name"),
                                    "course_number": b.get("course_number"),
                                    "day": b.get("day_of_week"),
                                    "time": b.get("start_time")
                                })
                        error_msg = f"Block not found for course '{course_name or course_number}' on day {original_day} at {original_start_time} in week {week_start}. Available blocks at this time: {available_blocks}"
                        logger.error(f"❌ {error_msg}")
                        raise HTTPException(status_code=404, detail=error_msg)
                else:
                    block = block_result.data[0]
                    logger.info(f"✅ Found exact match: {block.get('course_name')} ({block.get('course_number')})")
            
            logger.info(f"✅ Found block: {block.get('course_name')} ({block.get('course_number')}) on day {block.get('day_of_week')} at {block.get('start_time')}")
            
            # Check if user owns this block
            if block["user_id"] != user_id:
                raise HTTPException(status_code=403, detail="Not authorized to move this block")
            
            # If original_day was not provided, use the block's day
            if original_day is None:
                original_day = block.get("day_of_week")
                logger.info(f"📅 Using block's day as original_day: {original_day}")
            
            # If new_day is still None, use the same day as original_day (moving time only, not day)
            if new_day is None:
                new_day = original_day
                logger.info(f"📅 No new_day specified, using same day as original: {new_day}")
            
            # Get week_start from the block's plan (if not already provided)
            if not week_start:
                plan_result = client.table("weekly_plans").select("week_start").eq("id", block["plan_id"]).limit(1).execute()
                week_start = plan_result.data[0]["week_start"] if plan_result.data else None
            
            # Calculate new_end_time if not provided
            if not new_end_time:
                original_start_minutes = _time_to_minutes(block.get("start_time", "08:00"))
                original_end_minutes = _time_to_minutes(block.get("end_time", "09:00"))
                duration_minutes = original_end_minutes - original_start_minutes
                new_start_minutes = _time_to_minutes(new_start_time)
                new_end_time = _minutes_to_time(new_start_minutes + duration_minutes)
            
            work_type = block.get("work_type", "personal")
            course_number = block.get("course_number")
            course_name = block.get("course_name", "")
            
            # Get original block details (from the block we found)
            original_day = block.get("day_of_week")
            original_start = block.get("start_time")
            original_end = block.get("end_time")
            block_id_actual = block.get("id")
            
            # Check if it's a group block
            if work_type == "group":
                # For group blocks, create a change request instead of moving directly
                logger.info(f"📋 Block {block_id_actual} is a group block - creating change request")
                
                # Find the group_id for this block via group_plan_blocks
                # Group blocks are matched by course_number, day_of_week, start_time, and week_start
                
                group_plan_blocks_result = client.table("group_plan_blocks").select("group_id").eq("week_start", week_start).eq("course_number", course_number).eq("day_of_week", original_day).eq("start_time", original_start).limit(1).execute()
                
                if not group_plan_blocks_result.data:
                    # Fallback: try to find by course_number and user's groups
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
                        raise HTTPException(status_code=404, detail="Group not found for this block")
                else:
                    group_id = group_plan_blocks_result.data[0]["group_id"]
                
                # Get original block details
                original_day = block.get("day_of_week")
                original_start = block.get("start_time")
                original_end = block.get("end_time")
                original_duration = (_time_to_minutes(original_end) - _time_to_minutes(original_start)) // 60 if original_end else 1
                
                # Calculate proposed_duration from new_start_time and new_end_time
                # If new_end_time is provided, use it to calculate duration
                # Otherwise, use original_duration (moving same duration)
                if new_end_time:
                    new_start_minutes = _time_to_minutes(new_start_time)
                    new_end_minutes = _time_to_minutes(new_end_time)
                    proposed_duration = (new_end_minutes - new_start_minutes) // 60
                    logger.info(f"📊 Calculated proposed_duration from new time range: {new_start_time}-{new_end_time} = {proposed_duration} hours")
                else:
                    # If new_end_time not provided, use original_duration
                    proposed_duration = original_duration
                    logger.info(f"📊 No new_end_time provided, using original_duration: {proposed_duration} hours")
                
                # Extract reason from user_prompt if available
                reason = ""
                if user_prompt:
                    # Try to extract reason from prompt
                    reason = user_prompt
                
                # Create group change request
                request_data = {
                    "group_id": group_id,
                    "week_start": week_start,
                    "request_type": "move",
                    "original_day_of_week": original_day,
                    "original_start_time": original_start,
                    "original_end_time": original_end,
                    "original_duration_hours": original_duration,
                    "proposed_day_of_week": new_day,
                    "proposed_start_time": new_start_time,
                    "proposed_end_time": new_end_time,
                    "proposed_duration_hours": proposed_duration,
                    "requested_by": user_id,
                    "reason": reason,
                    "status": "pending"
                }
                
                # Check for conflicts before creating request
                # Calculate new_end_time for conflict checking
                if not new_end_time:
                    original_start_minutes = _time_to_minutes(original_start)
                    original_end_minutes = _time_to_minutes(original_end)
                    duration_minutes = original_end_minutes - original_start_minutes
                    new_start_minutes = _time_to_minutes(new_start_time)
                    new_end_time = _minutes_to_time(new_start_minutes + duration_minutes)
                
                conflict_reasons = self._check_conflicts(client, user_id, week_start, new_day, new_start_time, new_end_time, block_id_actual, course_number)
                
                # If there are real conflicts (not same course), reject the request
                if conflict_reasons:
                    conflict_message = "Cannot create change request - conflicts detected:\n" + "\n".join(conflict_reasons)
                    raise HTTPException(status_code=400, detail=conflict_message)
                
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
                original_time_str = f"{day_names[original_day]} {original_start}" if original_day is not None else "קיים"
                proposed_time_str = f"{day_names[new_day]} {new_start_time}"
                
                title = f"בקשת שינוי מפגש: {group_name}"
                message = f"{requester_name} מבקש לשנות מפגש מ-{original_time_str} ל-{proposed_time_str}. נדרש אישור מכל החברים."
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
                    "message": "Change request created. Waiting for approval from all members.",
                    "request_id": request_id,
                    "members_to_approve": len(member_ids),
                    "has_conflicts": False,
                    "conflicts": []
                }
            
            # It's a personal block - move it directly after checking conflicts
            logger.info(f"📦 Moving personal block {block_id_actual}")
            
            # Check if user specified specific hours to move (only if original_end_time is provided and different from block's end_time)
            move_specific_hours = False
            if original_end_time and original_end_time != original_end:
                # User specified a specific time range
                move_specific_hours = True
                logger.info(f"📦 User specified specific hours: {original_start} to {original_end_time}")
            
            # Find all consecutive blocks for the same course and work_type
            # Get all blocks for this plan/course/day/work_type to find consecutive ones
            all_blocks_for_move = client.table("weekly_plan_blocks").select("id, start_time, end_time").eq("plan_id", block["plan_id"]).eq("course_number", course_number).eq("work_type", work_type).eq("day_of_week", original_day).order("start_time").execute()
            
            consecutive_blocks = []
            
            if move_specific_hours:
                # User specified specific hours - only move blocks within that range
                logger.info(f"📦 Moving only specific hours: {original_start} to {original_end_time}")
                original_start_minutes = _time_to_minutes(original_start)
                original_end_minutes = _time_to_minutes(original_end_time)
                
                for b in (all_blocks_for_move.data or []):
                    block_start_minutes = _time_to_minutes(b.get("start_time", "00:00"))
                    block_end_minutes = _time_to_minutes(b.get("end_time", "00:00"))
                    
                    # Check if this block overlaps with the specified range
                    if block_start_minutes < original_end_minutes and block_end_minutes > original_start_minutes:
                        consecutive_blocks.append(b)
            else:
                # Default behavior: move all consecutive blocks starting from the found block
                starting_block = None
                for b in (all_blocks_for_move.data or []):
                    if b.get("start_time") == original_start:
                        starting_block = b
                        consecutive_blocks.append(b)
                        break
                
                if starting_block:
                    current_end_time = starting_block.get("end_time")
                    for b in (all_blocks_for_move.data or []):
                        if b["id"] == starting_block["id"]:
                            continue
                        block_start = b.get("start_time")
                        if block_start == current_end_time:
                            consecutive_blocks.append(b)
                            current_end_time = b.get("end_time")
                        elif _time_to_minutes(block_start) > _time_to_minutes(current_end_time):
                            break
            
            blocks_to_move_ids = [b["id"] for b in consecutive_blocks] if consecutive_blocks else [block_id_actual]
            num_hours_to_move = len(consecutive_blocks) if consecutive_blocks else 1
            
            logger.info(f"📦 Found {num_hours_to_move} consecutive block(s) to move: {blocks_to_move_ids}")
            
            # Calculate the total duration of all consecutive blocks
            if consecutive_blocks:
                first_block_start = _time_to_minutes(consecutive_blocks[0].get("start_time", "08:00"))
                last_block_end = _time_to_minutes(consecutive_blocks[-1].get("end_time", "09:00"))
                total_duration_minutes = last_block_end - first_block_start
            else:
                original_start_minutes = _time_to_minutes(block.get("start_time", "08:00"))
                original_end_minutes = _time_to_minutes(block.get("end_time", "09:00"))
                total_duration_minutes = original_end_minutes - original_start_minutes
            
            # Calculate new_end_time based on total duration
            new_start_minutes = _time_to_minutes(new_start_time)
            new_end_time = _minutes_to_time(new_start_minutes + total_duration_minutes)
            
            # Check conflicts for all blocks that will be moved
            conflict_reasons = self._check_conflicts(client, user_id, week_start, new_day, new_start_time, new_end_time, block_id_actual, course_number)
            
            if conflict_reasons:
                conflict_message = "Cannot move block - conflicts detected:\n" + "\n".join(conflict_reasons)
                raise HTTPException(status_code=400, detail=conflict_message)
            
            # Update all consecutive blocks
            # Calculate time slots for the new location
            time_slots = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
            
            # Find the closest time slot to new_start_time
            if new_start_time in time_slots:
                new_start_idx = time_slots.index(new_start_time)
            else:
                new_start_minutes = _time_to_minutes(new_start_time)
                closest_idx = 0
                min_diff = abs(_time_to_minutes(time_slots[0]) - new_start_minutes)
                for i, slot in enumerate(time_slots):
                    diff = abs(_time_to_minutes(slot) - new_start_minutes)
                    if diff < min_diff:
                        min_diff = diff
                        closest_idx = i
                new_start_idx = closest_idx
                new_start_time = time_slots[new_start_idx]  # Normalize to time slot
            
            # Update all consecutive blocks
            for i, block_id_to_move in enumerate(blocks_to_move_ids):
                if new_start_idx + i < len(time_slots):
                    new_time = time_slots[new_start_idx + i]
                    new_end = time_slots[new_start_idx + i + 1] if (new_start_idx + i + 1) < len(time_slots) else "21:00"
                    
                    update_result = client.table("weekly_plan_blocks").update({
                        "day_of_week": new_day,
                        "start_time": new_time,
                        "end_time": new_end,
                        "source": "manual"
                    }).eq("id", block_id_to_move).execute()
                    
                    if not update_result.data:
                        logger.warning(f"⚠️ Failed to update block {block_id_to_move}")
            
            logger.info(f"✅ Successfully moved {num_hours_to_move} consecutive block(s) to day {new_day}, {new_start_time}-{new_end_time}")
            
            # Extract preferences from user_prompt if available
            preferences_updated = False
            if user_prompt:
                try:
                    preferences_updated = await self._extract_and_update_preferences(
                        client, user_id, user_prompt, block, new_day, new_start_time
                    )
                except Exception as pref_err:
                    logger.warning(f"Failed to extract preferences: {pref_err}")
            
            return {
                "status": "success",
                "message": f"Block moved successfully to {new_start_time} on day {new_day}",
                "block_id": block_id_actual,
                "new_day": new_day,
                "new_start_time": new_start_time,
                "new_end_time": new_end_time,
                "preferences_updated": preferences_updated
            }
            
        except HTTPException as http_exc:
            # Re-raise HTTPException as-is
            logger.error(f"❌ HTTPException in block_mover: {http_exc.detail}")
            raise
        except Exception as e:
            logger.error(f"❌ Error moving block: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Make sure we always raise an HTTPException with a detail message
            error_detail = str(e) if str(e) else "Unknown error occurred"
            raise HTTPException(status_code=500, detail=f"Error moving block: {error_detail}")
    
    def _check_conflicts(
        self,
        client,
        user_id: str,
        week_start: Optional[str],
        new_day: int,
        new_start_time: str,
        new_end_time: str,
        block_id: Optional[str] = None,
        course_number: Optional[str] = None
    ) -> list:
        """Check for conflicts with constraints and other blocks
        
        Args:
            course_number: Course number of the block being moved. Blocks of the same course are ignored (not considered conflicts).
        """
        conflict_reasons = []
        
        new_start_minutes = _time_to_minutes(new_start_time)
        new_end_minutes = _time_to_minutes(new_end_time)
        
        # Check 1: Weekly constraints
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
                
                if new_day in days_array:
                    c_start = _time_to_minutes(constraint.get("start_time", "00:00"))
                    c_end = _time_to_minutes(constraint.get("end_time", "00:00"))
                    
                    if new_start_minutes < c_end and new_end_minutes > c_start:
                        conflict_reasons.append(f"Weekly hard constraint: {constraint.get('title', 'Constraint')} ({constraint.get('start_time')}-{constraint.get('end_time')})")
        
        # Check 2: Permanent constraints
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
            elif not isinstance(days_array, list):
                days_array = []
            
            if new_day in days_array:
                c_start = _time_to_minutes(constraint.get("start_time", "00:00"))
                c_end = _time_to_minutes(constraint.get("end_time", "00:00"))
                
                if new_start_minutes < c_end and new_end_minutes > c_start:
                    conflict_reasons.append(f"Permanent hard constraint: {constraint.get('title', 'Constraint')} ({constraint.get('start_time')}-{constraint.get('end_time')})")
        
        # Check 3: Existing blocks (other courses)
        if week_start:
            user_plan = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", week_start).limit(1).execute()
            if user_plan.data:
                user_plan_id = user_plan.data[0]["id"]
                existing_blocks = client.table("weekly_plan_blocks").select("id, course_name, course_number, start_time, end_time").eq("plan_id", user_plan_id).eq("day_of_week", new_day).execute()
                
                for existing_block in (existing_blocks.data or []):
                    # Skip the block we're moving
                    if block_id and existing_block.get("id") == block_id:
                        continue
                    
                    # Skip blocks of the same course (same course blocks don't conflict when moving)
                    # This handles the case where we're moving a block and there's another block of the same course at the new location
                    existing_course_number = existing_block.get("course_number")
                    if course_number and existing_course_number and str(existing_course_number) == str(course_number):
                        logger.info(f"🔍 Skipping conflict check for same course block: {existing_course_number}")
                        continue
                    
                    e_start = _time_to_minutes(existing_block.get("start_time", "00:00"))
                    e_end = _time_to_minutes(existing_block.get("end_time", "00:00"))
                    
                    if new_start_minutes < e_end and new_end_minutes > e_start:
                        conflict_reasons.append(f"Existing block: {existing_block.get('course_name', 'Course')} ({existing_block.get('start_time')}-{existing_block.get('end_time')})")
        
        return conflict_reasons
    
    async def _extract_and_update_preferences(
        self,
        client,
        user_id: str,
        user_prompt: str,
        block: dict,
        new_day: int,
        new_start_time: str
    ) -> bool:
        """Extract user preferences from prompt and update schedule_change_notes"""
        try:
            # Get current notes
            profile = client.table("user_profiles").select("schedule_change_notes").eq("id", user_id).limit(1).execute()
            current_notes = profile.data[0].get("schedule_change_notes", []) if profile.data else []
            
            if not isinstance(current_notes, list):
                current_notes = []
            
            # Add new note
            day_names = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
            new_note = {
                "date": datetime.now().isoformat(),
                "course": block.get("course_number", "?"),
                "change": f"moved from day {block.get('day_of_week')} {block.get('start_time')} to day {new_day} ({day_names[new_day]}) {new_start_time}",
                "explanation": user_prompt
            }
            current_notes.append(new_note)
            
            # Save notes
            client.table("user_profiles").update({
                "schedule_change_notes": current_notes
            }).eq("id", user_id).execute()
            
            logger.info(f"✅ Updated schedule_change_notes for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error updating preferences: {e}")
            return False
    
    def _normalize_time(self, time_str: str) -> str:
        """Normalize time format: '012:00' -> '12:00', '8:00' -> '08:00'"""
        if not time_str:
            return time_str
        
        # Remove leading zeros from hour part
        parts = time_str.split(":")
        if len(parts) >= 2:
            hour = parts[0].lstrip("0") or "0"  # Handle "00" case
            minute = parts[1]
            # Pad hour to 2 digits
            hour = hour.zfill(2)
            return f"{hour}:{minute}"
        return time_str
    
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
