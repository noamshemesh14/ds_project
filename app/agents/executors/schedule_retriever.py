"""
Schedule Retriever Executor
Retrieves and formats weekly schedules (blocks + constraints)
"""
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from app.supabase_client import supabase, supabase_admin
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Day names in Hebrew
DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
DAY_NAMES_HEBREW = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]


class ScheduleRetriever:
    """
    Retrieves weekly schedule for user
    """
    
    def __init__(self):
        self.module_name = "schedule_retriever"
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string in various formats (YYYY-MM-DD or YYYY/MM/DD)"""
        # Try YYYY-MM-DD first
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            pass
        
        # Try YYYY/MM/DD
        try:
            return datetime.strptime(date_str, "%Y/%m/%d")
        except ValueError:
            pass
        
        # Try other common formats
        try:
            return datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            pass
        
        raise ValueError(f"Invalid date format: {date_str}. Expected YYYY-MM-DD or YYYY/MM/DD")
    
    def _time_to_minutes(self, time_str: str) -> int:
        """Convert time string (HH:MM) to minutes since midnight"""
        try:
            # Handle HH:MM:SS or HH:MM
            parts = time_str.split(":")
            hours = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 else 0
            return hours * 60 + minutes
        except:
            return 0
    
    def _merge_consecutive_blocks(self, blocks: List[Dict]) -> List[Dict]:
        """
        Merge consecutive blocks on the same day, same course, and same work_type into single blocks
        Also removes duplicate blocks (identical day, course, work_type, start_time, end_time)
        Example: 13:00-14:00, 14:00-15:00, 15:00-16:00 (same course, same work_type) -> 13:00-16:00
        Only merges if all blocks have the same course_number AND same work_type
        """
        if not blocks:
            return []
        
        # First, remove exact duplicates (same day, course, work_type, start_time, end_time)
        seen_blocks = set()
        unique_blocks = []
        for block in blocks:
            # Create a unique key for the block
            block_key = (
                block.get("day_of_week", 0),
                block.get("course_number", ""),
                block.get("work_type", "personal"),
                block.get("start_time", "00:00"),
                block.get("end_time", "00:00")
            )
            if block_key not in seen_blocks:
                seen_blocks.add(block_key)
                unique_blocks.append(block)
        
        logger.info(f"📋 Removed duplicates: {len(blocks)} -> {len(unique_blocks)} unique blocks")
        
        # Group blocks by day_of_week, course_number, and work_type
        grouped = {}
        for block in unique_blocks:
            day = block.get("day_of_week", 0)
            course_num = block.get("course_number", "")
            work_type = block.get("work_type", "personal")
            key = (day, course_num, work_type)
            
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(block)
        
        merged_blocks = []
        
        for (day, course_num, work_type), day_blocks in grouped.items():
            # Sort by start_time
            day_blocks.sort(key=lambda b: self._time_to_minutes(b.get("start_time", "00:00")))
            
            # Merge consecutive blocks (only if same course and same work_type)
            # Keep the first block's ID when merging
            current_block = None
            for block in day_blocks:
                if current_block is None:
                    current_block = block.copy()
                    # Preserve block_id for UI interactions (use "id" field from database)
                    if "id" not in current_block:
                        # Try to get from block_id if it exists
                        current_block["id"] = block.get("block_id") or block.get("id")
                else:
                    # Check if this block is consecutive to current_block
                    current_end = self._time_to_minutes(current_block.get("end_time", "00:00"))
                    block_start = self._time_to_minutes(block.get("start_time", "00:00"))
                    
                    # Only merge if consecutive AND same course AND same work_type
                    if (block_start == current_end and 
                        current_block.get("course_number") == block.get("course_number") and
                        current_block.get("work_type") == block.get("work_type")):
                        # Merge: extend end_time (keep first block's ID)
                        current_block["end_time"] = block.get("end_time")
                        # Keep the first block's ID when merging
                    else:
                        # Not consecutive or different course/work_type, save current and start new
                        merged_blocks.append(current_block)
                        current_block = block.copy()
                        # Preserve block_id
                        if "id" not in current_block:
                            current_block["id"] = block.get("block_id") or block.get("id")
            
            if current_block:
                merged_blocks.append(current_block)
        
        # Sort merged blocks chronologically by day_of_week and start_time
        merged_blocks.sort(key=lambda b: (b.get("day_of_week", 0), self._time_to_minutes(b.get("start_time", "00:00"))))
        
        return merged_blocks
    
    def _constraints_to_display_items(
        self, client, user_id: str, week_start_str: str
    ) -> List[Dict]:
        """Fetch permanent and weekly constraints and convert to block-like items for display."""
        items = []
        # Permanent constraints (apply to every week)
        try:
            perm_res = client.table("constraints").select("title, days, start_time, end_time").eq("user_id", user_id).execute()
            for c in (perm_res.data or []):
                days_raw = c.get("days")
                if isinstance(days_raw, str):
                    try:
                        days_list = json.loads(days_raw)
                    except Exception:
                        days_list = []
                else:
                    days_list = list(days_raw) if days_raw else []
                start_t = (c.get("start_time") or "").strip()
                end_t = (c.get("end_time") or "").strip()
                title = (c.get("title") or "Constraint").strip()
                for d in days_list:
                    try:
                        day_int = int(d) if d is not None else None
                        if day_int is not None and 0 <= day_int <= 6 and start_t and end_t:
                            items.append({
                                "day_of_week": day_int,
                                "start_time": start_t,
                                "end_time": end_t,
                                "course_name": title,
                                "work_type": "constraint",
                            })
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            logger.warning(f"Could not load permanent constraints: {e}")
        # Weekly constraints for this week
        try:
            weekly_res = client.table("weekly_constraints").select("title, days, start_time, end_time").eq("user_id", user_id).eq("week_start", week_start_str).execute()
            for c in (weekly_res.data or []):
                days_raw = c.get("days")
                if isinstance(days_raw, str):
                    try:
                        days_list = json.loads(days_raw)
                    except Exception:
                        days_list = []
                else:
                    days_list = list(days_raw) if days_raw else []
                start_t = (c.get("start_time") or "").strip()
                end_t = (c.get("end_time") or "").strip()
                title = (c.get("title") or "Constraint").strip()
                for d in days_list:
                    try:
                        day_int = int(d) if d is not None else None
                        if day_int is not None and 0 <= day_int <= 6 and start_t and end_t:
                            items.append({
                                "day_of_week": day_int,
                                "start_time": start_t,
                                "end_time": end_t,
                                "course_name": title,
                                "work_type": "constraint",
                            })
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            logger.warning(f"Could not load weekly constraints: {e}")
        return items
    
    def _format_schedule_display(self, blocks: List[Dict], week_start: str) -> str:
        """Format schedule blocks into a readable display (chronologically sorted, no IDs)"""
        if not blocks:
            return f"No schedule blocks found for week starting {week_start}."
        
        # Blocks are already sorted chronologically by _merge_consecutive_blocks
        # Group by day for display
        by_day = {}
        for block in blocks:
            day = block.get("day_of_week", 0)
            if day not in by_day:
                by_day[day] = []
            by_day[day].append(block)
        
        # Format output - only show readable information, no IDs
        lines = []
        lines.append(f"Week starting: {week_start}")
        lines.append("=" * 60)
        
        # Display days in chronological order (Sunday=0 to Saturday=6)
        for day in range(7):
            if day not in by_day:
                continue
            
            day_name = DAY_NAMES_HEBREW[day] if day < len(DAY_NAMES_HEBREW) else DAY_NAMES[day]
            lines.append(f"\n{day_name}:")
            
            # Sort day blocks by start_time (should already be sorted, but just in case)
            day_blocks = sorted(by_day[day], key=lambda b: self._time_to_minutes(b.get("start_time", "00:00")))
            
            for block in day_blocks:
                start_time = block.get("start_time", "00:00")
                end_time = block.get("end_time", "00:00")
                work_type = block.get("work_type", "personal")
                if work_type == "constraint":
                    title = block.get("course_name", block.get("title", "Constraint"))
                    lines.append(f"  {start_time}-{end_time} | {title} (אילוץ)")
                else:
                    course_name = block.get("course_name", block.get("course_number", "Unknown"))
                    course_num = block.get("course_number", "")
                    work_type_label = "Group" if work_type == "group" else ("Semester" if work_type == "semester" else "Personal")
                    lines.append(f"  {start_time}-{end_time} | {course_name} ({course_num}) - {work_type_label}")
        
        return "\n".join(lines)
    
    async def execute(
        self,
        user_id: str,
        date: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Retrieve weekly schedule for a specific week
        
        Args:
            user_id: User ID
            date: Date in YYYY-MM-DD or YYYY/MM/DD format (defaults to today)
            **kwargs: Additional parameters
        
        Returns:
            Dict with weekly schedule
        """
        try:
            client = supabase_admin if supabase_admin else supabase
            if not client:
                raise HTTPException(status_code=500, detail="Supabase client not configured")
            
            # Parse date
            if date:
                try:
                    target_date = self._parse_date(date)
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
            else:
                target_date = datetime.now()
            
            # Find Sunday of that week
            # weekday() returns: Monday=0, Tuesday=1, ..., Saturday=5, Sunday=6
            # We want to find the Sunday of the week containing target_date
            # The week starts on Sunday and ends on Saturday
            # JavaScript getDay(): 0=Sunday, 1=Monday, ..., 6=Saturday
            # Python weekday(): 0=Monday, 1=Tuesday, ..., 6=Sunday
            # To match JavaScript logic: daysToSubtract = JavaScript_day
            # Convert Python weekday to JavaScript day format:
            # Python Sunday (6) -> JavaScript Sunday (0) -> 0 days back
            # Python Monday (0) -> JavaScript Monday (1) -> 1 day back
            # Python Tuesday (1) -> JavaScript Tuesday (2) -> 2 days back
            # ...
            # Python Saturday (5) -> JavaScript Saturday (6) -> 6 days back
            # Formula: Convert Python weekday to JavaScript day: (weekday + 1) % 7
            # Then use that as days to subtract (same as JavaScript's daysToSubtract)
            js_day = (target_date.weekday() + 1) % 7  # Convert to JavaScript day format (0=Sun, 6=Sat)
            days_since_sunday = js_day  # Same as JavaScript's daysToSubtract
            
            week_start = target_date - timedelta(days=days_since_sunday)
            week_start_str = week_start.strftime("%Y-%m-%d")
            
            logger.info(f"📅 Date calculation: target_date={target_date.strftime('%Y-%m-%d')}, weekday={target_date.weekday()} (0=Mon, 6=Sun), js_day={js_day} (0=Sun, 6=Sat), days_since_sunday={days_since_sunday}, week_start={week_start_str}")
            
            logger.info(f"📅 Retrieving schedule for week starting {week_start_str} (requested date: {date or 'today'})")
            
            # Get weekly plan
            logger.info(f"🔍 Searching for weekly_plan: user_id={user_id}, week_start={week_start_str}")
            plan_result = client.table("weekly_plans").select("*").eq("user_id", user_id).eq("week_start", week_start_str).execute()
            
            logger.info(f"📊 Plan query result: found {len(plan_result.data) if plan_result.data else 0} plans")
            
            # If no plan found, still show constraints for the week
            if not plan_result.data or len(plan_result.data) == 0:
                logger.warning(f"⚠️ No weekly plan found for week starting {week_start_str}")
                constraint_items = self._constraints_to_display_items(client, user_id, week_start_str)
                schedule_display = self._format_schedule_display(constraint_items, week_start_str) if constraint_items else f"No schedule found for week starting {week_start_str}"
                all_plans = client.table("weekly_plans").select("week_start").eq("user_id", user_id).order("week_start", desc=True).limit(10).execute()
                available_plans = [p.get('week_start') for p in all_plans.data] if all_plans.data else []
                logger.info(f"📋 Available plans for user (last 10): {available_plans}")
                return {
                    "status": "no_schedule",
                    "message": schedule_display,
                    "week_start": week_start_str,
                    "schedule_display": schedule_display,
                    "blocks": [{"day_of_week": b.get("day_of_week"), "start_time": b.get("start_time"), "end_time": b.get("end_time"), "course_name": b.get("course_name"), "work_type": "constraint"} for b in constraint_items],
                    "available_plans": available_plans
                }
            
            plan = plan_result.data[0]
            plan_id = plan["id"]
            logger.info(f"✅ Found plan: id={plan_id}")
            
            # Get plan blocks
            logger.info(f"🔍 Searching for blocks: plan_id={plan_id}")
            blocks_result = client.table("weekly_plan_blocks").select("*").eq("plan_id", plan_id).order("day_of_week").order("start_time").execute()
            
            raw_blocks = blocks_result.data if blocks_result.data else []
            
            logger.info(f"📋 Found {len(raw_blocks)} raw blocks for week {week_start_str}")
            if raw_blocks:
                logger.info(f"   First raw block sample: {raw_blocks[0]}")
            
            # Merge consecutive blocks
            merged_blocks = self._merge_consecutive_blocks(raw_blocks)
            
            logger.info(f"✅ Merged to {len(merged_blocks)} blocks after grouping consecutive ones")
            if merged_blocks:
                logger.info(f"   First merged block sample: {merged_blocks[0]}")
            
            # Add constraints (permanent + weekly) for this week
            constraint_items = self._constraints_to_display_items(client, user_id, week_start_str)
            combined = merged_blocks + constraint_items
            combined.sort(key=lambda b: (b.get("day_of_week", 0), self._time_to_minutes(b.get("start_time", "00:00"))))
            
            # Format for display (blocks + constraints)
            schedule_display = self._format_schedule_display(combined, week_start_str)
            
            # Clean blocks for response (include block_id for UI interactions; include constraints)
            clean_blocks = []
            for block in combined:
                wt = block.get("work_type")
                if wt == "constraint":
                    clean_block = {
                        "block_id": None,
                        "day_of_week": block.get("day_of_week"),
                        "day_name": DAY_NAMES_HEBREW[block.get("day_of_week", 0)] if block.get("day_of_week", 0) < len(DAY_NAMES_HEBREW) else DAY_NAMES[block.get("day_of_week", 0)],
                        "start_time": block.get("start_time"),
                        "end_time": block.get("end_time"),
                        "course_number": "",
                        "course_name": block.get("course_name", block.get("title", "Constraint")),
                        "work_type": "constraint",
                        "work_type_label": "אילוץ"
                    }
                else:
                    clean_block = {
                        "block_id": block.get("id"),
                        "day_of_week": block.get("day_of_week"),
                        "day_name": DAY_NAMES_HEBREW[block.get("day_of_week", 0)] if block.get("day_of_week", 0) < len(DAY_NAMES_HEBREW) else DAY_NAMES[block.get("day_of_week", 0)],
                        "start_time": block.get("start_time"),
                        "end_time": block.get("end_time"),
                        "course_number": block.get("course_number"),
                        "course_name": block.get("course_name"),
                        "work_type": wt,
                        "work_type_label": "Group" if wt == "group" else ("Semester" if wt == "semester" else "Personal")
                    }
                clean_blocks.append(clean_block)
            
            return {
                "status": "success",
                "message": schedule_display,
                "week_start": week_start_str,
                "schedule_display": schedule_display,
                "blocks": clean_blocks,
                "total_blocks": len(clean_blocks)
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error retrieving schedule: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Error retrieving schedule: {str(e)}")
    
    def get_step_log(
        self,
        prompt: Dict[str, Any],
        response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate step log"""
        return {
            "module": self.module_name,
            "prompt": prompt,
            "response": response
        }
