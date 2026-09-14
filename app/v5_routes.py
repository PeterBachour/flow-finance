from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .db import connection
from .financial_routes import _ensure_recurring_intelligence_schema
from .v2_migrations import ensure_v2_schema
from .v22_migrations import ensure_v22_schema
from .v36_routes import InboxStatusIn, set_inbox_status
from .v46_routes import financial_decisions
from .v47_routes import decision_priorities
from .v5_engine import build_v5_cockpit
from .v5_planning import build_v5_plan, build_v5_scenario
from .v5_predictive import build_v5_predictive_pilot
from .v5_recommendations import build_v5_recommendations
from .v51_events import build_upcoming_events
from .v51_goals import build_goal_control, simulate_goal_contribution
from .v51_scenarios import (
    compare_v51_scenario,
    create_v51_scenario,
    delete_v51_scenario,
    list_v51_scenarios,
)
from .v52_decisions import build_v52_decision_center
from .v53_home_snapshot import build_v53_home_snapshot
from .version import VERSION

router = APIRouter(prefix='/api/v5', tags=['Flow V5'])


class ScenarioIn(BaseModel):
    months: int = Field(default=6, ge=1, le=12)
    one_time_expense_cents: int = Field(default=0, ge=0)
    one_time_date: date | None = None
    monthly_spend_delta_cents: int = Field(default=0, ge=0)
    monthly_income_delta_cents: int = Field(default=0, ge=0)


class SavedScenarioEventIn(BaseModel):
    event_type: str = Field(default='one_time', pattern='^(one_time|monthly)$')
    label: str = Field(min_length=1, max_length=180)
    amount_cents: int
    due_date: date | None = None
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    start_date: date | None = None
    end_date: date | None = None


class SavedScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=400)
    horizon_months: int = Field(default=6, ge=1, le=12)
    events: list[SavedScenarioEventIn] = Field(default_factory=list)


class GoalContributionSimulationIn(BaseModel):
    monthly_contribution_cents: int = Field(ge=0)
    months: int = Field(default=12, ge=1, le=12)


@router.get('/home-snapshot')
def home_snapshot(as_of: date | None = None, months: int = Query(default=6, ge=1, le=12)):
    observed = as_of or date.today()
    decisions = financial_decisions(include_closed=True)
    with connection() as conn:
        ensure_v2_schema(conn)
        _ensure_recurring_intelligence_schema(conn)
        result = build_v53_home_snapshot(
            conn,
            as_of=observed,
            all_financial_decisions=decisions.get('items', []),
            quality_review_count=int(decisions.get('quality_review_count') or 0),
            months=months,
        )
    return {**result, 'runtime_version': VERSION}


@router.get('/cockpit')
def cockpit(as_of: date | None = None):
    observed = as_of or date.today()
    decisions = decision_priorities()
    with connection() as conn:
        ensure_v2_schema(conn)
        _ensure_recurring_intelligence_schema(conn)
        payload = build_v5_cockpit(
            conn,
            as_of=observed,
            financial_decisions=decisions.get('items', []),
        )
    return {
        **payload,
        'runtime_version': VERSION,
        'open_financial_decisions': int(decisions.get('open_count') or 0),
        'quality_review_count': int(decisions.get('quality_review_count') or 0),
    }


@router.get('/plan')
def plan(months: int = Query(default=6, ge=1, le=12)):
    with connection() as conn:
        ensure_v2_schema(conn)
        _ensure_recurring_intelligence_schema(conn)
        payload = build_v5_plan(conn, months=months)
    return {**payload, 'runtime_version': VERSION}


@router.post('/scenario')
def scenario(payload: ScenarioIn):
    with connection() as conn:
        ensure_v2_schema(conn)
        _ensure_recurring_intelligence_schema(conn)
        result = build_v5_scenario(
            conn,
            months=payload.months,
            one_time_expense_cents=payload.one_time_expense_cents,
            one_time_date=payload.one_time_date,
            monthly_spend_delta_cents=payload.monthly_spend_delta_cents,
            monthly_income_delta_cents=payload.monthly_income_delta_cents,
        )
    return {**result, 'runtime_version': VERSION}


@router.get('/scenarios')
def saved_scenarios():
    with connection() as conn:
        items = list_v51_scenarios(conn)
    return {
        'items': items,
        'count': len(items),
        'runtime_version': VERSION,
        'principle': 'Les scénarios enregistrés sont séparés des transactions réelles.',
    }


@router.post('/scenarios', status_code=201)
def save_scenario(payload: SavedScenarioIn):
    with connection() as conn:
        result = create_v51_scenario(
            conn,
            name=payload.name,
            description=payload.description,
            horizon_months=payload.horizon_months,
            events=[event.model_dump(mode='json') for event in payload.events],
        )
    return {**result, 'runtime_version': VERSION}


@router.get('/scenarios/{scenario_id}/compare')
def compare_saved_scenario(scenario_id: int):
    with connection() as conn:
        result = compare_v51_scenario(conn, scenario_id)
    return {**result, 'runtime_version': VERSION}


@router.delete('/scenarios/{scenario_id}', status_code=204)
def remove_saved_scenario(scenario_id: int):
    with connection() as conn:
        delete_v51_scenario(conn, scenario_id)


@router.get('/goals-control')
def goals_control(as_of: date | None = None, months: int = Query(default=12, ge=1, le=12)):
    observed = as_of or date.today()
    with connection() as conn:
        ensure_v22_schema(conn)
        result = build_goal_control(conn, today=observed, months=months)
    return {**result, 'runtime_version': VERSION}


@router.post('/goals/{goal_id}/simulate-contribution')
def goal_contribution_simulation(goal_id: int, payload: GoalContributionSimulationIn, as_of: date | None = None):
    observed = as_of or date.today()
    with connection() as conn:
        ensure_v22_schema(conn)
        result = simulate_goal_contribution(
            conn,
            goal_id=goal_id,
            monthly_contribution_cents=payload.monthly_contribution_cents,
            today=observed,
            months=payload.months,
        )
    if result is None:
        raise HTTPException(404, 'Objectif introuvable')
    return {**result, 'runtime_version': VERSION}


@router.get('/recommendations')
def recommendations(as_of: date | None = None, months: int = Query(default=6, ge=1, le=12)):
    observed = as_of or date.today()
    decisions = decision_priorities()
    with connection() as conn:
        ensure_v2_schema(conn)
        _ensure_recurring_intelligence_schema(conn)
        result = build_v5_recommendations(
            conn,
            as_of=observed,
            financial_decisions=decisions.get('items', []),
            months=months,
        )
    return {
        **result,
        'runtime_version': VERSION,
        'open_financial_decisions': int(decisions.get('open_count') or 0),
        'quality_review_count': int(decisions.get('quality_review_count') or 0),
    }


@router.get('/decision-center')
def decision_center(as_of: date | None = None, months: int = Query(default=6, ge=1, le=12)):
    observed = as_of or date.today()
    decisions = decision_priorities()
    all_decisions = financial_decisions(include_closed=True)
    with connection() as conn:
        ensure_v2_schema(conn)
        _ensure_recurring_intelligence_schema(conn)
        result = build_v52_decision_center(
            conn,
            as_of=observed,
            financial_decisions=decisions.get('items', []),
            closed_decisions=all_decisions.get('items', []),
            quality_review_count=int(decisions.get('quality_review_count') or 0),
            months=months,
        )
    return {
        **result,
        'runtime_version': VERSION,
        'open_financial_decisions': int(decisions.get('open_count') or 0),
    }


@router.patch('/decision-center/{item_key:path}')
def update_decision_center_status(item_key: str, payload: InboxStatusIn):
    decisions = financial_decisions(include_closed=True)
    allowed_keys = {str(item.get('key')) for item in decisions.get('items', []) if item.get('key')}
    if item_key not in allowed_keys:
        raise HTTPException(
            409,
            'Seul le statut d’une décision financière existante peut être modifié. Les recommandations V5 restent en lecture seule.',
        )
    result = set_inbox_status(item_key, payload)
    return {
        **result,
        'origin': 'financial_decision',
        'financial_data_changed': False,
        'runtime_version': VERSION,
    }


@router.get('/predictive-pilot')
def predictive_pilot(as_of: date | None = None, months: int = Query(default=6, ge=1, le=12)):
    observed = as_of or date.today()
    decisions = decision_priorities()
    with connection() as conn:
        ensure_v2_schema(conn)
        _ensure_recurring_intelligence_schema(conn)
        result = build_v5_predictive_pilot(
            conn,
            as_of=observed,
            financial_decisions=decisions.get('items', []),
            months=months,
        )
    return {
        **result,
        'runtime_version': VERSION,
        'open_financial_decisions': int(decisions.get('open_count') or 0),
        'quality_review_count': int(decisions.get('quality_review_count') or 0),
    }


@router.get('/upcoming-events')
def upcoming_events(as_of: date | None = None, days: int = Query(default=45, ge=7, le=120)):
    observed = as_of or date.today()
    with connection() as conn:
        ensure_v2_schema(conn)
        _ensure_recurring_intelligence_schema(conn)
        result = build_upcoming_events(conn, as_of=observed, days=days)
    return {**result, 'runtime_version': VERSION}
