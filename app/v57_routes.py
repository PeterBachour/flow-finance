from datetime import date

from fastapi import APIRouter, Query

from .bulk_import import ensure_bulk_schema
from .data_quality_actions import build_data_quality_actions
from .db import connection
from .history_coverage import build_history_coverage
from .history_readiness import build_history_readiness
from .imports import ensure_import_schema

router = APIRouter(prefix='/api/v5.7', tags=['v5.7'])


@router.get('/data-quality-actions')
def data_quality_actions(
    months: int = Query(default=24, ge=6, le=120),
    as_of: date | None = None,
):
    with connection() as conn:
        ensure_import_schema(conn)
        ensure_bulk_schema(conn)
        coverage = build_history_coverage(conn, as_of=as_of, months=months)
        readiness = build_history_readiness(coverage)
        result = build_data_quality_actions(coverage, readiness)
        return {
            'as_of': coverage['as_of'],
            'period_start': coverage['period_start'],
            'period_end': coverage['period_end'],
            **result,
        }
