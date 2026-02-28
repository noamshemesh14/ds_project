"""
Weekly Planner Executor
Triggers weekly plan generation for all users (same as POST /api/system/weekly-plan/generate).
Only allowed for weeks from May 2026 onwards to avoid overwriting existing schedules.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# First date allowed for weekly plan generation via execute (May 1, 2026)
WEEKLY_PLANNER_MIN_DATE = "2026-05-01"


def _parse_date_to_week_start(date_str: str) -> str:
    """
    Parse a date string in various formats and return the Sunday (week start) of that week.
    Supports: YYYY-MM-DD, YYYY/MM/DD, DD/MM/YY, DD/MM/YYYY.
    """
    date_str = (date_str or "").strip()
    if not date_str:
        raise ValueError("Date or week_start is required")
    dt = None
    # YYYY-MM-DD or YYYY/MM/DD
    for sep in ["-", "/"]:
        try:
            if sep in date_str and len(date_str) >= 10:
                parts = date_str.replace("/", "-").split("-")
                if len(parts) == 3 and len(parts[0]) == 4:  # YYYY first
                    dt = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
                    break
                if len(parts) == 3 and len(parts[2]) <= 2:  # DD/MM/YY
                    y = int(parts[2])
                    year = 2000 + y if y < 100 else y
                    dt = datetime(year, int(parts[1]), int(parts[0]))
                    break
        except (ValueError, IndexError):
            continue
    if dt is None:
        # Try DD/MM/YY or DD/MM/YYYY
        match = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", date_str)
        if match:
            d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
            year = 2000 + y if y < 100 else y
            dt = datetime(year, m, d)
    if dt is None:
        raise ValueError(f"Could not parse date: {date_str}. Use YYYY-MM-DD or DD/MM/YY.")
    # Week starts on Sunday: (weekday()+1)%7 gives days since Sunday (Sun=0)
    days_since_sunday = (dt.weekday() + 1) % 7
    sunday = dt - timedelta(days=days_since_sunday)
    return sunday.strftime("%Y-%m-%d")


class WeeklyPlannerExecutor:
    """
    Executor that runs the global weekly plan generation (same as system endpoint).
    Allowed only for week_start >= May 2026.
    """

    def __init__(self):
        self.module_name = "weekly_planner"

    async def execute(
        self,
        user_id: str,
        week_start: Optional[str] = None,
        date: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run weekly plan generation for all users for the given week.
        week_start: YYYY-MM-DD (Sunday). date: any date in the week (will be normalized to Sunday).
        """
        try:
            raw = week_start or date
            if not raw:
                return {
                    "status": "error",
                    "message": "Please specify a week (e.g. week_start or date). Example: 'run weekly plan for week starting 03/05/26'.",
                    "response": "Please specify a week (e.g. week_start or date).",
                }
            week_start_str = _parse_date_to_week_start(raw)
            if week_start_str < WEEKLY_PLANNER_MIN_DATE:
                return {
                    "status": "error",
                    "message": "Weekly plan generation via the agent is only available from May 2026 onwards to avoid overwriting existing schedules.",
                    "response": "Weekly plan generation is only available from May 2026 onwards.",
                    "week_start": week_start_str,
                }
            # Lazy import to avoid circular import (main imports supervisor -> executors)
            from app.main import _run_weekly_auto_for_all_users
            await _run_weekly_auto_for_all_users(week_start_override=week_start_str)
            planning_steps = [
                "Cleanup existing plans and blocks for the week",
                "Plan group blocks with LLM (common free slots, sync across members)",
                "Plan and refine personal blocks with LLM (preferences, hour distribution)",
                "Sync group blocks to all members",
            ]
            return {
                "status": "success",
                "message": f"Weekly plans generated for all users (week_start={week_start_str})",
                "response": f"Weekly plans generated for all users (week_start={week_start_str})",
                "week_start": week_start_str,
                "planning_steps": planning_steps,
            }
        except ValueError as e:
            return {
                "status": "error",
                "message": str(e),
                "response": str(e),
            }
        except Exception as e:
            logger.exception("Weekly planner execution failed")
            return {
                "status": "error",
                "message": str(e) if str(e) else "Weekly plan generation failed",
                "response": str(e) if str(e) else "Weekly plan generation failed",
            }

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
