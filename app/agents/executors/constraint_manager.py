"""
Constraint Manager Executor
Adds constraints (permanent or one-time) to user's schedule
"""
import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from app.supabase_client import supabase, supabase_admin
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def _time_to_minutes(time_str: str) -> int:
    """Convert time string (HH:MM) to minutes since midnight"""
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


def _get_week_start(date_str: Optional[str] = None) -> str:
    """Get week start date (Sunday) for a given date or today"""
    if date_str:
        try:
            # Normalize date format
            date_normalized = date_str.replace("/", "-")
            
            # Try different date formats
            date_obj = None
            date_formats = [
                "%Y-%m-%d",      # 2026-02-14
                "%d-%m-%Y",      # 14-02-2026
                "%d-%m-%y",      # 14-02-26
            ]
            
            for fmt in date_formats:
                try:
                    date_obj = datetime.strptime(date_normalized, fmt)
                    break
                except ValueError:
                    continue
            
            if date_obj is None:
                date_obj = datetime.now()
        except:
            date_obj = datetime.now()
    else:
        date_obj = datetime.now()
    
    # Find Sunday of this week
    days_since_sunday = (date_obj.weekday() + 1) % 7
    sunday = date_obj - timedelta(days=days_since_sunday)
    return sunday.strftime("%Y-%m-%d")


class ConstraintManager:
    def __init__(self):
        self.module_name = "constraint_manager"

    async def execute(
        self,
        user_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        days: Optional[List[int]] = None,
        day_of_week: Optional[int] = None,  # Single day (0-6)
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        is_permanent: Optional[bool] = None,  # True = permanent, False = one-time
        week_start: Optional[str] = None,  # For one-time constraints (week start date, Sunday)
        date: Optional[str] = None,  # Specific date (YYYY-MM-DD) - will be converted to week_start
        is_hard: Optional[bool] = True,
        user_prompt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Add a constraint (permanent or one-time) to user's schedule.
        
        Args:
            user_id: User ID
            title: Constraint title (e.g., "אימון", "עבודה")
            description: Optional description
            days: List of days (0-6, where 0=Sunday) - for multiple days
            day_of_week: Single day (0-6) - if provided, will be converted to days list
            start_time: Start time (HH:MM)
            end_time: End time (HH:MM)
            is_permanent: True for permanent constraint, False for one-time (default: False if not specified)
            week_start: Week start date (YYYY-MM-DD, Sunday) for one-time constraints
            date: Specific date (YYYY-MM-DD) - if provided, will be converted to week_start (Sunday of that week)
            is_hard: True for hard constraint, False for soft (default: True)
            user_prompt: User's natural language prompt (for extracting info if not provided)
        """
        try:
            client = supabase_admin if supabase_admin else supabase
            if not client:
                raise HTTPException(status_code=500, detail="Supabase client not configured")
            
            # Validate required fields
            if not title:
                raise HTTPException(status_code=400, detail="title is required")
            
            if not start_time or not end_time:
                raise HTTPException(status_code=400, detail="start_time and end_time are required")
            
            # Determine days
            # If date is provided but day_of_week is not, calculate day_of_week from date
            if date and day_of_week is None:
                try:
                    # Normalize date format (handle YYYY/MM/DD, YYYY-MM-DD, DD/MM/YY, etc.)
                    date_normalized = date.replace("/", "-")
                    
                    # Try different date formats
                    date_obj = None
                    date_formats = [
                        "%Y-%m-%d",      # 2026-02-14
                        "%d-%m-%Y",      # 14-02-2026
                        "%d-%m-%y",      # 14-02-26
                        "%Y/%m/%d",      # 2026/02/14 (already normalized to -)
                        "%d/%m/%Y",      # 14/02/2026 (already normalized to -)
                        "%d/%m/%y",      # 14/02/26 (already normalized to -)
                    ]
                    
                    for fmt in date_formats:
                        try:
                            date_obj = datetime.strptime(date_normalized, fmt)
                            break
                        except ValueError:
                            continue
                    
                    if date_obj is None:
                        raise ValueError(f"Could not parse date {date} with any known format")
                    
                    # weekday() returns 0=Monday, 6=Sunday, but we need 0=Sunday, 6=Saturday
                    # Convert: Monday=0 -> Sunday=6, Tuesday=1 -> Monday=0, etc.
                    day_of_week = (date_obj.weekday() + 1) % 7
                    logger.info(f"📅 Calculated day_of_week={day_of_week} from date {date} (parsed as {date_obj.strftime('%Y-%m-%d')})")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to calculate day_of_week from date {date}: {e}")
                    # Fall through to error
            
            if days:
                constraint_days = days
            elif day_of_week is not None:
                constraint_days = [day_of_week]
            else:
                raise HTTPException(status_code=400, detail="days or day_of_week is required (or provide date to calculate day_of_week)")
            
            # Validate days
            for day in constraint_days:
                if day < 0 or day > 6:
                    raise HTTPException(status_code=400, detail=f"Invalid day: {day}. Must be 0-6 (0=Sunday)")
            
            # Determine if permanent (default: False if not specified)
            if is_permanent is None:
                is_permanent = False  # Default to one-time
            
            # For one-time constraints, get week_start
            if not is_permanent:
                # If date is provided, convert it to week_start (Sunday of that week)
                if date:
                    # Normalize date format (YYYY/MM/DD -> YYYY-MM-DD)
                    if "/" in date:
                        date = date.replace("/", "-")
                    week_start = _get_week_start(date)
                    logger.info(f"📅 Converted specific date {date} to week_start: {week_start}")
                elif not week_start:
                    week_start = _get_week_start()
                    logger.info(f"📅 No week_start specified, using current week: {week_start}")
                else:
                    # Normalize week_start format (YYYY/MM/DD -> YYYY-MM-DD)
                    if "/" in week_start:
                        week_start = week_start.replace("/", "-")
                    logger.info(f"📅 Using specified week_start: {week_start}")
            
            # Check for conflicts with existing constraints
            conflict_reasons = []
            
            if is_permanent:
                # Check permanent constraints
                existing_permanent = client.table("constraints").select("*").eq("user_id", user_id).execute()
                for existing in (existing_permanent.data or []):
                    existing_days = []
                    if isinstance(existing.get("days"), str):
                        try:
                            existing_days = json.loads(existing["days"])
                        except:
                            existing_days = []
                    elif isinstance(existing.get("days"), list):
                        existing_days = existing["days"]
                    
                    # Check if days overlap
                    if any(day in existing_days for day in constraint_days):
                        # Check time overlap
                        existing_start = _time_to_minutes(existing.get("start_time", "00:00"))
                        existing_end = _time_to_minutes(existing.get("end_time", "00:00"))
                        new_start = _time_to_minutes(start_time)
                        new_end = _time_to_minutes(end_time)
                        
                        if new_start < existing_end and new_end > existing_start:
                            conflict_reasons.append(f"Existing permanent constraint: {existing.get('title', 'Constraint')} ({existing.get('start_time')}-{existing.get('end_time')})")
            else:
                # Check weekly constraints for the same week
                existing_weekly = client.table("weekly_constraints").select("*").eq("user_id", user_id).eq("week_start", week_start).execute()
                for existing in (existing_weekly.data or []):
                    existing_days = []
                    if isinstance(existing.get("days"), str):
                        try:
                            existing_days = json.loads(existing["days"])
                        except:
                            existing_days = []
                    elif isinstance(existing.get("days"), list):
                        existing_days = existing["days"]
                    
                    # Check if days overlap
                    if any(day in existing_days for day in constraint_days):
                        # Check time overlap
                        existing_start = _time_to_minutes(existing.get("start_time", "00:00"))
                        existing_end = _time_to_minutes(existing.get("end_time", "00:00"))
                        new_start = _time_to_minutes(start_time)
                        new_end = _time_to_minutes(end_time)
                        
                        if new_start < existing_end and new_end > existing_start:
                            conflict_reasons.append(f"Existing weekly constraint: {existing.get('title', 'Constraint')} ({existing.get('start_time')}-{existing.get('end_time')})")
            
            # Check for conflicts with existing schedule (weekly_plan_blocks)
            # This is the ONLY case where we allow both constraint and schedule to coexist (with warning)
            schedule_conflicts = []
            
            # Check blocks for the relevant week(s)
            if not is_permanent:
                # Check blocks for the specific week
                user_plan = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", week_start).limit(1).execute()
                if user_plan.data:
                    plan_id = user_plan.data[0]["id"]
                    existing_blocks = client.table("weekly_plan_blocks").select("*").eq("plan_id", plan_id).execute()
                    
                    for block in (existing_blocks.data or []):
                        if block.get("day_of_week") in constraint_days:
                            block_start = _time_to_minutes(block.get("start_time", "00:00"))
                            block_end = _time_to_minutes(block.get("end_time", "00:00"))
                            new_start = _time_to_minutes(start_time)
                            new_end = _time_to_minutes(end_time)
                            
                            if new_start < block_end and new_end > block_start:
                                schedule_conflicts.append(f"Existing schedule block: {block.get('course_name', 'Course')} ({block.get('start_time')}-{block.get('end_time')})")
            else:
                # For permanent constraints, check current week as example (will apply to all weeks)
                current_week = _get_week_start()
                user_plan = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", current_week).limit(1).execute()
                if user_plan.data:
                    plan_id = user_plan.data[0]["id"]
                    existing_blocks = client.table("weekly_plan_blocks").select("*").eq("plan_id", plan_id).execute()
                    
                    for block in (existing_blocks.data or []):
                        if block.get("day_of_week") in constraint_days:
                            block_start = _time_to_minutes(block.get("start_time", "00:00"))
                            block_end = _time_to_minutes(block.get("end_time", "00:00"))
                            new_start = _time_to_minutes(start_time)
                            new_end = _time_to_minutes(end_time)
                            
                            if new_start < block_end and new_end > block_start:
                                schedule_conflicts.append(f"Existing schedule block: {block.get('course_name', 'Course')} ({block.get('start_time')}-{block.get('end_time')})")
            
            # If there are constraint conflicts, reject
            if conflict_reasons:
                conflict_message = "Cannot add constraint - conflicts with existing constraints:\n" + "\n".join(conflict_reasons)
                raise HTTPException(status_code=400, detail=conflict_message)
            
            # If there are schedule conflicts, warn but allow (this is the only case where we allow both)
            warning_message = None
            if schedule_conflicts:
                warning_message = "⚠️ Warning: This constraint conflicts with existing schedule:\n" + "\n".join(schedule_conflicts) + "\n\nThe constraint will be added anyway, but you may need to adjust your schedule."
                logger.warning(f"⚠️ Constraint conflicts with schedule: {schedule_conflicts}")
            
            # Create the constraint
            days_str = json.dumps(constraint_days)
            
            if is_permanent:
                # Create permanent constraint
                constraint_dict = {
                    "user_id": user_id,
                    "title": title,
                    "description": description or "",
                    "days": days_str,
                    "start_time": start_time,
                    "end_time": end_time,
                    "is_hard": is_hard
                }
                
                response = client.table("constraints").insert(constraint_dict).execute()
                if not response.data:
                    raise HTTPException(status_code=500, detail="Failed to create constraint")
                
                logger.info(f"✅ Created permanent constraint: {title} on days {constraint_days} at {start_time}-{end_time}")
                
                return {
                    "status": "success",
                    "message": "Permanent constraint created successfully",
                    "constraint": response.data[0],
                    "warning": warning_message,
                    "has_schedule_conflicts": len(schedule_conflicts) > 0
                }
            else:
                # Create one-time constraint
                constraint_dict = {
                    "user_id": user_id,
                    "title": title,
                    "description": description or "",
                    "days": days_str,
                    "start_time": start_time,
                    "end_time": end_time,
                    "week_start": week_start,
                    "is_hard": is_hard
                }
                
                response = client.table("weekly_constraints").insert(constraint_dict).execute()
                if not response.data:
                    raise HTTPException(status_code=500, detail="Failed to create weekly constraint")
                
                logger.info(f"✅ Created one-time constraint: {title} on days {constraint_days} at {start_time}-{end_time} for week {week_start}")
                
                return {
                    "status": "success",
                    "message": "One-time constraint created successfully",
                    "constraint": response.data[0],
                    "warning": warning_message,
                    "has_schedule_conflicts": len(schedule_conflicts) > 0
                }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error creating constraint: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise HTTPException(status_code=500, detail=f"Error creating constraint: {str(e)}")

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

