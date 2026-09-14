from datetime import date

from fastapi import APIRouter, HTTPException, Query

from .bulk_import import ensure_bulk_schema
from .certified_safe_to_spend import build_certified_safe_to_spend
from .db import connection
from .documentary_evidence import build_documentary_evidence, transaction_evidence
from .forecast_v6 import build_v6_daily_trajectory
from .imports import ensure_import_schema

router = APIRouter(prefix='/api/v6', tags=['v6'])


@router.get('/safe-to-spend')
def certified_safe_to_spend(as_of: date | None = None, horizon_days: int | None = Query(default=None, ge=0, le=366)):
    with connection() as conn:
        return build_certified_safe_to_spend(conn, as_of=as_of, horizon_days=horizon_days)



@router.get('/safe-to-spend/explanation')
def safe_to_spend_explanation(as_of: date | None = None, horizon_days: int | None = Query(default=None, ge=0, le=366)):
    with connection() as conn:
        return build_safe_to_spend_explanation(conn, as_of=as_of, horizon_days=horizon_days)


@router.get('/trajectory')
def daily_trajectory(as_of: date | None = None, horizon_days: int | None = Query(default=None, ge=0, le=366)):
    with connection() as conn:
        return build_v6_daily_trajectory(conn, as_of=as_of, horizon_days=horizon_days)


@router.get('/documentary-evidence')
def documentary_evidence(
    months: int = Query(default=24, ge=1, le=120),
    as_of: date | None = None,
):
    with connection() as conn:
        ensure_import_schema(conn)
        ensure_bulk_schema(conn)
        return build_documentary_evidence(conn, as_of=as_of, months=months)


@router.get('/transactions/{transaction_id}/evidence')
def get_transaction_evidence(transaction_id: int):
    with connection() as conn:
        ensure_import_schema(conn)
        result = transaction_evidence(conn, transaction_id)
    if result is None:
        raise HTTPException(404, 'Mouvement introuvable')
    return result
