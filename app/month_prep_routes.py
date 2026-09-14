from datetime import date

from fastapi import APIRouter, HTTPException, Query

from .alert_routes import router as alert_router
from .db import connection
from .month_prep import build_month_preparation, next_month_key

router = APIRouter()
router.include_router(alert_router)


@router.get('/api/month-prep')
def month_preparation(month: str | None = Query(default=None, pattern=r'^\d{4}-\d{2}$')):
    target = month or next_month_key(date.today())
    try:
        with connection() as conn:
            return build_month_preparation(conn, target)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
