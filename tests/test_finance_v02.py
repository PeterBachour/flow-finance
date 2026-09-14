from datetime import date

from app.finance import budget_status, goal_summary


def test_budget_status_reports_remaining_and_overage():
    normal=budget_status(15000,9200,'limit')
    assert normal['remaining_cents']==5800
    assert normal['over_budget'] is False
    over=budget_status(15000,16300,'limit')
    assert over['remaining_cents']==0
    assert over['over_budget'] is True


def test_goal_summary_computes_monthly_trajectory():
    goal={'id':1,'name':'Appartement','target_cents':300000,'target_date':'2027-03-31','priority':10}
    summary=goal_summary(goal,120000,date(2026,9,8))
    assert summary['remaining_cents']==180000
    assert summary['monthly_needed_cents']==30000
    assert summary['progress']==0.4
