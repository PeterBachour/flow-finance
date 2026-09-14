from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from .forecast import PlannedEvent
from .projection_routes import dashboard_v2_data

router = APIRouter(prefix='/api/v2.3', tags=['Flow V2.3'])

ScenarioType = Literal['purchase','savings_transfer','monthly_investment','future_expense','target_closing_balance']


class AdvancedSimulationIn(BaseModel):
    scenario_type: ScenarioType
    amount_cents: int = Field(default=0, ge=0)
    due_date: date | None = None
    label: str = Field(default='Simulation', min_length=1, max_length=180)
    monthly_amount_cents: int = Field(default=0, ge=0)
    months: int = Field(default=3, ge=1, le=24)
    target_closing_balance_cents: int = Field(default=0, ge=0)

    @model_validator(mode='before')
    @classmethod
    def v3_compatibility(cls, values):
        if not isinstance(values, dict):
            return values
        data = dict(values)
        if not data.get('scenario_type') and data.get('scenario'):
            data['scenario_type'] = data['scenario']
        scenario = data.get('scenario_type')
        amount = int(data.get('amount_cents') or 0)
        if scenario == 'monthly_investment' and not data.get('monthly_amount_cents'):
            data['monthly_amount_cents'] = amount
        if scenario == 'target_closing_balance' and not data.get('target_closing_balance_cents'):
            data['target_closing_balance_cents'] = amount
        if not data.get('label'):
            data['label'] = 'Simulation'
        return data


def _verdict(base: dict, result: dict) -> tuple[str, str]:
    low = int(result['low_point']['balance_cents'])
    safe = int(result['safe_to_spend_cents'])
    if low < 0:
        return 'not_recommended', 'Non recommandé'
    if safe <= 0:
        return 'tight', 'Possible mais serré'
    delta = safe - int(base['safe_to_spend_cents'])
    if delta < -int(base['safe_to_spend_cents']) * .5:
        return 'prudent', 'Possible avec prudence'
    return 'compatible', 'Compatible'


def _month_add(value: date, offset: int) -> date:
    idx = value.year * 12 + value.month - 1 + offset
    year, month = idx // 12, idx % 12 + 1
    day = min(value.day, 28)
    return date(year, month, day)


@router.post('/simulate')
def simulate(payload: AdvancedSimulationIn):
    today = date.today()
    baseline_data = dashboard_v2_data()
    baseline = baseline_data['projections']['realistic']
    events: list[PlannedEvent] = []
    due = payload.due_date or today
    assumptions: list[str] = []

    if payload.scenario_type in {'purchase','future_expense'}:
        events.append(PlannedEvent(due, -payload.amount_cents, payload.label, 'confirmed', 'commitment', 'simulation'))
        assumptions.append(f'Dépense ponctuelle de {payload.amount_cents / 100:.2f} € le {due.isoformat()}')
    elif payload.scenario_type == 'savings_transfer':
        events.append(PlannedEvent(due, -payload.amount_cents, payload.label or 'Versement épargne', 'confirmed', 'commitment', 'simulation'))
        assumptions.append('Le versement vers l’épargne est traité comme indisponible pour le Safe to Spend.')
    elif payload.scenario_type == 'monthly_investment':
        monthly = payload.monthly_amount_cents or payload.amount_cents
        for offset in range(payload.months):
            d = _month_add(due, offset)
            events.append(PlannedEvent(d, -monthly, payload.label or 'Investissement mensuel', 'confirmed', 'commitment', 'simulation'))
        assumptions.append(f'Engagement mensuel de {monthly / 100:.2f} € pendant {payload.months} mois.')
    elif payload.scenario_type == 'target_closing_balance':
        target = payload.target_closing_balance_cents
        current_close = int(baseline['closing_balance_cents'])
        capacity = max(0, current_close - target)
        return {
            'scenario_type': payload.scenario_type,
            'baseline': baseline,
            'simulated': baseline,
            'impact': {'safe_to_spend_delta_cents': 0, 'low_point_delta_cents': 0, 'closing_balance_delta_cents': 0},
            'target': {'closing_balance_cents': target, 'maximum_additional_spend_cents': capacity},
            'verdict': 'target', 'verdict_label': 'Budget calculé',
            'summary': f'Pour conserver {target / 100:.2f} € à la clôture projetée, la dépense additionnelle maximale est de {capacity / 100:.2f} €.',
            'assumptions': ['Calcul basé sur la trajectoire réaliste actuelle.'],
        }

    simulated_data = dashboard_v2_data(events)
    result = simulated_data['projections']['realistic']
    verdict, label = _verdict(baseline, result)
    impact = {
        'safe_to_spend_delta_cents': int(result['safe_to_spend_cents']) - int(baseline['safe_to_spend_cents']),
        'low_point_delta_cents': int(result['low_point']['balance_cents']) - int(baseline['low_point']['balance_cents']),
        'closing_balance_delta_cents': int(result['closing_balance_cents']) - int(baseline['closing_balance_cents']),
    }
    summary = {
        'compatible': 'Cette décision reste compatible avec la trajectoire actuelle.',
        'prudent': 'Cette décision reste finançable mais réduit fortement ta marge de sécurité.',
        'tight': 'Cette décision consomme pratiquement tout le disponible sécurisé.',
        'not_recommended': 'Cette décision crée un risque de découvert dans la projection.',
    }[verdict]
    return {
        'scenario_type': payload.scenario_type,
        'baseline': baseline,
        'simulated': result,
        'impact': impact,
        'verdict': verdict,
        'verdict_label': label,
        'summary': summary,
        'assumptions': assumptions,
        'persisted': False,
    }
