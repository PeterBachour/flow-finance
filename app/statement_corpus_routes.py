from fastapi import APIRouter, HTTPException

from .bulk_import import commit_batch, ensure_bulk_schema
from .db import connection
from .statement_corpus_preflight import build_batch_preflight

router = APIRouter()


@router.get('/api/imports/bulk/{batch_id}/preflight')
def bulk_preflight(batch_id: int):
    with connection() as conn:
        ensure_bulk_schema(conn)
        try:
            return build_batch_preflight(conn, batch_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc


@router.post('/api/imports/bulk/{batch_id}/commit')
def guarded_bulk_commit(batch_id: int, confirm_warnings: bool = False):
    with connection() as conn:
        ensure_bulk_schema(conn)
        try:
            preflight = build_batch_preflight(conn, batch_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        if not preflight['can_commit']:
            raise HTTPException(
                409,
                detail={
                    'message': 'Validation bloquée par le contrôle de continuité des relevés.',
                    'preflight': preflight,
                },
            )
        if preflight['requires_confirmation'] and not confirm_warnings:
            raise HTTPException(
                409,
                detail={
                    'code': 'confirmation_required',
                    'message': 'Des périodes sont manquantes. Confirme explicitement pour importer ce lot incomplet.',
                    'preflight': preflight,
                },
            )
        try:
            result = commit_batch(conn, batch_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f'Validation du lot interrompue : {str(exc)[:180]}') from exc
    return {'ok': True, 'batch_id': batch_id, 'preflight': preflight, **result}
