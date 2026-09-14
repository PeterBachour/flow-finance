from datetime import date


def month_key(value: date) -> str:
    return value.strftime('%Y-%m')


def goal_summary(goal: dict, allocated_cents: int, today: date) -> dict:
    target = max(0, int(goal['target_cents']))
    imported_current = max(0, int(goal.get('current_cents') or 0))
    manual_allocations = max(0, int(allocated_cents))
    allocated = imported_current + manual_allocations
    remaining = max(0, target - allocated)
    progress = 1.0 if target == 0 else min(1.0, allocated / target)
    monthly_needed = 0
    target_date = goal.get('target_date')
    if remaining and target_date:
        end = date.fromisoformat(target_date)
        months = max(1, (end.year - today.year) * 12 + end.month - today.month)
        monthly_needed = (remaining + months - 1) // months
    return {**goal, 'allocated_cents': allocated, 'imported_current_cents': imported_current, 'manual_allocations_cents': manual_allocations, 'remaining_cents': remaining, 'progress': progress, 'monthly_needed_cents': monthly_needed}


def budget_status(planned_cents: int, spent_cents: int, mode: str) -> dict:
    planned = max(0, int(planned_cents))
    spent = max(0, int(spent_cents))
    remaining = max(0, planned - spent)
    ratio = 0 if planned == 0 else spent / planned
    return {'planned_cents': planned, 'spent_cents': spent, 'remaining_cents': remaining, 'ratio': ratio, 'mode': mode, 'over_budget': planned > 0 and spent > planned}
