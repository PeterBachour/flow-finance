import json
import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .financial_routes import router as financial_router
from .notion_routes import router as notion_router
from .version import VERSION

router = APIRouter()
router.include_router(notion_router)
router.include_router(financial_router)
MAINTENANCE = Path(os.getenv('FLOW_MAINTENANCE_DIR', '/maintenance'))
STATUS = MAINTENANCE / 'status.json'
REQUEST = MAINTENANCE / 'request'
CHECK_REQUEST = MAINTENANCE / 'check-request'
BUSY_STATES = {'checking', 'requested', 'downloading', 'building', 'restarting'}


class UpdateRequest(BaseModel):
    confirmation: str


def enabled() -> bool:
    return os.getenv('FLOW_UPDATE_ENABLED') == '1' and MAINTENANCE.exists() and os.access(MAINTENANCE, os.W_OK)


def read_status() -> dict:
    try:
        data = json.loads(STATUS.read_text())
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (OSError, ValueError, json.JSONDecodeError):
        return {
            'state': 'idle' if enabled() else 'disabled',
            'message': 'Prêt à vérifier' if enabled() else 'Helper de mise à jour non configuré',
            'current_commit': os.getenv('FLOW_GIT_COMMIT', ''),
            'remote_commit': '',
            'local_version': VERSION,
            'remote_version': '',
            'updated_at': None,
        }


def write_status(data: dict) -> None:
    tmp = STATUS.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(STATUS)


@router.get('/api/version')
def app_version():
    return {'version': VERSION, 'commit': os.getenv('FLOW_GIT_COMMIT', '')}


@router.get('/api/update/status')
def update_status():
    data = read_status()
    current = data.get('current_commit') or os.getenv('FLOW_GIT_COMMIT', '')
    remote = data.get('remote_commit') or ''
    state = data.get('state') or 'idle'
    known = bool(current and remote and current != 'unknown' and remote != 'unknown')
    data.update({
        'current_version': VERSION,
        'local_version': VERSION,
        'remote_version': data.get('remote_version') or '',
        'enabled': enabled(),
        'current_commit': current,
        'update_available': state == 'available' and known and current != remote,
        'up_to_date': state in {'idle', 'completed'} and known and current == remote,
        'busy': state in BUSY_STATES,
        'blocked': state == 'blocked',
        'last_checked': data.get('updated_at'),
    })
    return data


@router.post('/api/update/check', status_code=202)
def check_update():
    if not enabled():
        raise HTTPException(503, 'Update helper not configured')
    if read_status().get('state') in BUSY_STATES:
        raise HTTPException(409, 'Update operation already running')
    payload = {
        'state': 'checking',
        'message': 'Vérification demandée…',
        'current_commit': os.getenv('FLOW_GIT_COMMIT', ''),
        'remote_commit': '',
        'local_version': VERSION,
        'remote_version': '',
        'updated_at': int(time.time()),
    }
    try:
        write_status(payload)
        CHECK_REQUEST.write_text(str(time.time()))
    except OSError as exc:
        raise HTTPException(503, 'Update check unavailable') from exc
    return {'ok': True, 'state': 'checking'}


@router.post('/api/update', status_code=202)
def run_update(payload: UpdateRequest):
    if payload.confirmation != 'METTRE A JOUR':
        raise HTTPException(400, 'Confirmation required')
    if not enabled():
        raise HTTPException(503, 'Update helper not configured')
    current = read_status()
    if current.get('state') in BUSY_STATES:
        raise HTTPException(409, 'Update already running')
    if current.get('state') == 'blocked':
        raise HTTPException(409, current.get('message') or 'Update blocked')
    if not current.get('current_commit') or not current.get('remote_commit'):
        raise HTTPException(409, 'Check for updates first')
    if current['current_commit'] == current['remote_commit']:
        raise HTTPException(409, 'Already up to date')
    if current.get('relation') not in {None, '', 'fast_forward'}:
        raise HTTPException(409, 'Fast-forward update not possible')
    requested = {**current, 'state': 'requested', 'message': 'Mise à jour demandée…', 'updated_at': int(time.time())}
    try:
        write_status(requested)
        REQUEST.write_text(str(time.time()))
    except OSError as exc:
        raise HTTPException(503, 'Update request unavailable') from exc
    return {'ok': True, 'state': 'requested'}
