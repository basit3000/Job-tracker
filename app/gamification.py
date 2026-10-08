"""Progress derived from existing records, never from record creation times."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_

from app.extensions import db
from app.models import JobApplication

SUBMITTED_STATUSES = (
    "applied",
    "interviewing",
    "offer",
    "accepted",
    "rejected",
)


def submitted_query(user_ids, today=None):
    today = today or datetime.now(timezone.utc).date()
    return JobApplication.query.filter(
        JobApplication.user_id.in_(user_ids),
        JobApplication.deleted_at.is_(None),
        or_(
            JobApplication.status.in_(SUBMITTED_STATUSES),
            and_(
                JobApplication.status == "closed",
                JobApplication.applied_on.isnot(None),
            ),
        ),
        or_(
            JobApplication.applied_on.is_(None),
            JobApplication.applied_on <= today,
        ),
    )


def _streaks(days, today):
    best = run = 0
    previous = None
    for day in sorted(days):
        run = (
            run + 1
            if previous is not None and day - previous == timedelta(days=1)
            else 1
        )
        best = max(best, run)
        previous = day
    current = 0
    cursor = today if today in days else today - timedelta(days=1)
    while cursor in days:
        current += 1
        cursor -= timedelta(days=1)
    return current, best


def _summarize(rows, today):
    days = defaultdict(int)
    total = unknown = interviews = offers = 0
    for day, status, count in rows:
        total += count
        if day is None:
            unknown += count
        else:
            days[day] += count
        if status in {"interviewing", "offer", "accepted"}:
            interviews += count
        if status in {"offer", "accepted"}:
            offers += count
    current, best_streak = _streaks(days, today)
    best_day = max(days, key=lambda day: (days[day], day), default=None)
    best_count = days[best_day] if best_day else 0
    badges = [
        {"name": name, "description": description, "earned": earned}
        for name, description, earned in (
            (
                "First step",
                "Track your first submitted application",
                total >= 1,
            ),
            ("Momentum", "Track 10 submitted applications", total >= 10),
            ("Century", "Track 100 submitted applications", total >= 100),
            ("On a roll", "Apply on 7 consecutive days", best_streak >= 7),
            ("Big day", "Record 10 applications on one day", best_count >= 10),
            (
                "Conversation starter",
                "Reach interviewing or beyond",
                interviews >= 1,
            ),
        )
    ]
    activity = [
        {
            "day": today - timedelta(days=offset),
            "count": days[today - timedelta(days=offset)],
        }
        for offset in reversed(range(14))
    ]
    return {
        **_chart_data(days, today),
        "total": total,
        "unknown_dates": unknown,
        "today": days[today],
        "week": sum(
            count
            for day, count in days.items()
            if day >= today - timedelta(days=6)
        ),
        "best_day": best_count,
        "best_date": best_day,
        "streak": current,
        "best_streak": best_streak,
        "interviews": interviews,
        "offers": offers,
        "xp": total * 10,
        "level": total // 10 + 1,
        "level_progress": total % 10 * 10,
        "to_next_level": 10 - total % 10,
        "badges": badges,
        "activity": activity,
        "activity_max": max((item["count"] for item in activity), default=0)
        or 1,
    }


def _chart_data(days, today):
    daily = [
        {
            "day": today - timedelta(days=offset),
            "count": days[today - timedelta(days=offset)],
        }
        for offset in reversed(range(28))
    ]
    start = today - timedelta(days=today.weekday() + 77)
    calendar = [
        {
            "day": start + timedelta(days=offset),
            "count": days.get(start + timedelta(days=offset), 0),
            "future": start + timedelta(days=offset) > today,
        }
        for offset in range(84)
    ]
    previous_week = sum(
        days.get(today - timedelta(days=offset), 0) for offset in range(7, 14)
    )
    this_week = sum(
        days.get(today - timedelta(days=offset), 0) for offset in range(7)
    )
    return {
        "chart_days": daily,
        "chart_max": max(1, *(item["count"] for item in daily)),
        "calendar_weeks": [
            calendar[index : index + 7] for index in range(0, 84, 7)
        ],
        "active_days": sum(item["count"] > 0 for item in daily),
        "chart_total": sum(item["count"] for item in daily),
        "week_change": this_week - previous_week,
        "previous_week": previous_week,
    }


def application_stats(user_ids, *, today=None):
    """Aggregate many profiles in one query; callers enforce profile access."""
    today = today or datetime.now(timezone.utc).date()
    user_ids = set(user_ids)
    grouped = defaultdict(list)
    rows = (
        submitted_query(user_ids, today)
        .with_entities(
            JobApplication.user_id,
            JobApplication.applied_on,
            JobApplication.status,
            db.func.count(JobApplication.id),
        )
        .group_by(
            JobApplication.user_id,
            JobApplication.applied_on,
            JobApplication.status,
        )
        .all()
    )
    for user_id, day, status, count in rows:
        grouped[user_id].append((day, status, count))
    return {
        user_id: _summarize(grouped[user_id], today) for user_id in user_ids
    }
