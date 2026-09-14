from __future__ import annotations

from datetime import date

from .balance_only import enrich_balance_only_position
from .commitment_engine import build_commitment_review
from .financial_intelligence import build_financial_intelligence
from .v47_routes import build_advanced_analysis


def _int(value) -> int:
    return int(value or 0)


def _confidence_label(value: str | None) -> str:
    return {
        'high': 'high',
        'medium': 'medium',
        'low': 'low',
    }.get(value or '', 'low')


def _decision_status(*, safe_cents: int, projected_margin_cents: int, confidence: str) -> str:
    if safe_cents <= 0 or projected_margin_cents < 0:
        return 'critical'
    if confidence == 'low':
        return 'watch'
    if confidence == 'medium':
        return 'prudent'
    return 'comfortable'


def _primary_recommendation(*, safe_cents: int, projected_margin_cents: int, confidence: str,
                            financial_decision: dict | None, signal: dict | None) -> dict:
    if safe_cents <= 0:
        return {
            'kind': 'liquidity',
            'severity': 'critical',
            'title': 'Réduire les dépenses variables',
            'detail': 'Le Safe disponible jusqu’au prochain revenu est nul ou négatif.',
            'source': 'safe_to_spend',
        }
    if projected_margin_cents < 0:
        return {
            'kind': 'forecast',
            'severity': 'critical',
            'title': 'Marge de fin de cycle insuffisante',
            'detail': 'La projection passe sous la réserve de sécurité avant le prochain revenu.',
            'source': 'forecast',
        }
    if financial_decision:
        return {
            'kind': financial_decision.get('type') or 'financial_decision',
            'severity': financial_decision.get('priority') or 'medium',
            'title': financial_decision.get('title') or 'Décision financière à traiter',
            'detail': financial_decision.get('detail') or financial_decision.get('details') or '',
            'amount_cents': financial_decision.get('amount_cents'),
            'key': financial_decision.get('key'),
            'source': 'financial_decisions',
        }
    if signal:
        return {
            'kind': signal.get('kind') or 'historical_signal',
            'severity': signal.get('severity') or 'watch',
            'title': signal.get('title') or 'Signal historique à surveiller',
            'detail': signal.get('detail') or '',
            'amount_cents': signal.get('amount_cents'),
            'source': 'advanced_analysis',
        }
    if confidence == 'low':
        return {
            'kind': 'data_confidence',
            'severity': 'watch',
            'title': 'Actualiser les données avant une décision importante',
            'detail': 'Le niveau de confiance est faible ; la recommandation reste exploitable mais doit être interprétée prudemment.',
            'source': 'data_quality',
        }
    return {
        'kind': 'pace',
        'severity': 'positive',
        'title': 'Maintenir le rythme conseillé',
        'detail': 'Aucun signal financier prioritaire ne nécessite d’ajustement immédiat.',
        'source': 'decision_engine',
    }


def build_v5_cockpit(conn, *, as_of: date, financial_decisions: list[dict] | None = None) -> dict:
    """Build the single read-only decision contract used by the V5 home screen.

    V5 does not invent a second set of financial formulas. It composes the
    canonical Safe-to-Spend, forecast, commitment and historical-analysis
    engines into one presentation contract.
    """
    intelligence = enrich_balance_only_position(
        conn,
        build_financial_intelligence(conn, as_of=as_of, history_months=12),
    )
    safe = intelligence.get('safe_to_spend') or {}
    forecast = intelligence.get('forecast') or {}
    headline = intelligence.get('headline') or {}
    position = intelligence.get('current_position') or {}
    quality = intelligence.get('data_quality') or {}

    horizon_raw = safe.get('horizon_end') or forecast.get('horizon_end') or as_of.isoformat()
    try:
        horizon = date.fromisoformat(str(horizon_raw)[:10])
    except ValueError:
        horizon = as_of
    commitment_review = build_commitment_review(conn, as_of=as_of, horizon_end=horizon)
    analysis = build_advanced_analysis(conn, as_of=as_of)

    daily_cents = _int(
        headline.get('recommended_daily_spend_cents')
        or position.get('recommended_daily_spend_cents')
        or headline.get('variable_daily_rate_cents')
    )
    safe_cents = _int(headline.get('safe_to_spend_cents') or safe.get('safe_to_spend_cents'))
    balance_cents = _int(safe.get('balance_cents') or position.get('current_balance_cents'))
    projected_bank_cents = _int(forecast.get('projected_bank_balance_at_horizon_cents'))
    projected_margin_cents = _int(
        forecast.get('projected_margin_above_safety_cents')
        or headline.get('expected_remaining_at_horizon_cents')
    )
    projected_variable_cents = _int(forecast.get('projected_variable_to_horizon_cents'))
    reserve_cents = _int(safe.get('safety_reserve_cents'))
    commitment_summary = commitment_review.get('summary') or {}
    protected_commitments_cents = _int(commitment_summary.get('protected_confirmed_cents'))
    planned_commitments_cents = _int(safe.get('planned_commitments_cents'))
    recurring_commitments_cents = _int(safe.get('recurring_commitments_cents'))
    goal_contributions_cents = _int(safe.get('goal_contributions_cents'))
    days_to_horizon = _int(safe.get('horizon_days') or position.get('days_to_horizon'))

    confidence = _confidence_label(headline.get('trend_confidence') or quality.get('trend_confidence'))
    decision_status = _decision_status(
        safe_cents=safe_cents,
        projected_margin_cents=projected_margin_cents,
        confidence=confidence,
    )

    decision_items = financial_decisions or []
    primary_decision = decision_items[0] if decision_items else None
    signals = analysis.get('signals') or []
    primary_signal = signals[0] if signals else None
    recommendation = _primary_recommendation(
        safe_cents=safe_cents,
        projected_margin_cents=projected_margin_cents,
        confidence=confidence,
        financial_decision=primary_decision,
        signal=primary_signal,
    )

    return {
        'schema_version': '5.0',
        'as_of': as_of.isoformat(),
        'decision': {
            'status': decision_status,
            'daily_pace_cents': daily_cents,
            'safe_until_income_cents': safe_cents,
            'balance_cents': balance_cents,
            'days_to_horizon': days_to_horizon,
            'next_salary_date': headline.get('next_salary_date') or safe.get('next_salary_date') or forecast.get('next_salary_date'),
            'recommendation': recommendation,
        },
        'protection': {
            'protected_commitments_cents': protected_commitments_cents,
            'planned_commitments_cents': planned_commitments_cents,
            'recurring_commitments_cents': recurring_commitments_cents,
            'goal_contributions_cents': goal_contributions_cents,
            'safety_reserve_cents': reserve_cents,
        },
        'forecast': {
            'horizon_end': forecast.get('horizon_end') or safe.get('horizon_end'),
            'projected_bank_balance_cents': projected_bank_cents,
            'projected_margin_above_safety_cents': projected_margin_cents,
            'projected_variable_to_horizon_cents': projected_variable_cents,
            'next_salary_date': headline.get('next_salary_date') or forecast.get('next_salary_date'),
        },
        'confidence': {
            'level': confidence,
            'historical_coverage_pct': quality.get('historical_coverage_pct'),
            'balance_as_of': quality.get('balance_as_of'),
            'balance_age_days': quality.get('balance_age_days'),
            'balance_freshness_status': quality.get('balance_freshness_status'),
            'transaction_freshness_status': quality.get('transaction_freshness_status'),
            'current_month_observed': bool(quality.get('current_month_observed')),
        },
        'historical_context': {
            'latest_closed_month': analysis.get('latest_closed_month'),
            'latest_closed_variable_cents': analysis.get('latest_closed_variable_cents'),
            'prior_reference_median_cents': analysis.get('prior_reference_median_cents'),
            'latest_vs_reference_pct': analysis.get('latest_vs_reference_pct'),
            'signals': signals[:3],
        },
        'explanation': {
            'safe_formula': safe.get('formula') or 'balance - engagements protégés - réserve - objectifs',
            'principle': 'Le cockpit V5 compose les moteurs financiers canoniques existants ; il ne recalcule aucun montant dans le frontend.',
            'sources': ['safe_to_spend', 'validated_forecast', 'commitment_engine', 'advanced_analysis'],
        },
    }
