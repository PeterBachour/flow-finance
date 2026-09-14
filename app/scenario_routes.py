from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .forecast import PlannedEvent
from .projection_routes import dashboard_v2_data

router = APIRouter()


class DecisionIn(BaseModel):
    amount_cents: int = Field(gt=0)
    due_date: date
    label: str = Field(default='Dépense envisagée', min_length=1, max_length=180)
    exceptional_buffer_cents: int = Field(default=30000, ge=0)


def _scenario_result(name: str, baseline: dict, extra_events: list[PlannedEvent], assumptions: list[str]) -> dict:
    simulated = dashboard_v2_data(extra_events)
    forecast = simulated['projections']['realistic']
    low = forecast['low_point']['balance_cents']
    safe = forecast['safe_to_spend_cents']
    if low < 0:
        verdict = 'no'
        verdict_label = 'Non recommandé'
    elif safe <= 0:
        verdict = 'caution'
        verdict_label = 'Possible mais tendu'
    else:
        verdict = 'yes'
        verdict_label = 'Compatible'
    return {
        'name': name,
        'verdict': verdict,
        'verdict_label': verdict_label,
        'safe_to_spend_cents': safe,
        'low_point': forecast['low_point'],
        'closing_balance_cents': forecast['closing_balance_cents'],
        'impact_safe_cents': safe - baseline['safe_to_spend_cents'],
        'assumptions': assumptions,
    }


@router.post('/api/decisions/evaluate')
def evaluate_decision(payload: DecisionIn):
    baseline_data = dashboard_v2_data()
    baseline = baseline_data['projections']['realistic']
    purchase = PlannedEvent(payload.due_date, -payload.amount_cents, payload.label, 'confirmed', 'commitment', 'decision')
    contingency = max(10000, round(payload.amount_cents * 0.10))
    prudent_extra = PlannedEvent(payload.due_date, -contingency, 'Marge prudente', 'confirmed', 'commitment', 'scenario')
    exceptional_extra = PlannedEvent(payload.due_date, -payload.exceptional_buffer_cents, 'Imprévu exceptionnel', 'confirmed', 'commitment', 'scenario')
    scenarios = [
        _scenario_result('Normal', baseline, [purchase], ['Projection réaliste actuelle', 'Montant de la dépense inchangé']),
        _scenario_result('Prudent', baseline, [purchase, prudent_extra], ['Projection réaliste actuelle', 'Dépense + 10 % de marge, minimum 100 €']),
        _scenario_result('Exceptionnel', baseline, [purchase, prudent_extra, exceptional_extra], ['Scénario prudent', f'Imprévu supplémentaire de {payload.exceptional_buffer_cents / 100:.2f} €']),
    ]
    normal = scenarios[0]
    if normal['verdict'] == 'no':
        summary = 'La dépense crée un risque de découvert dans la projection normale.'
    elif normal['verdict'] == 'caution':
        summary = 'La dépense reste finançable mais consomme tout le disponible sans risque.'
    else:
        summary = 'La dépense reste compatible avec la projection normale.'
    return {
        'as_of': baseline_data['as_of'],
        'decision': {'label': payload.label, 'amount_cents': payload.amount_cents, 'due_date': payload.due_date.isoformat()},
        'baseline_safe_to_spend_cents': baseline['safe_to_spend_cents'],
        'summary': summary,
        'scenarios': scenarios,
        'persisted': False,
    }
