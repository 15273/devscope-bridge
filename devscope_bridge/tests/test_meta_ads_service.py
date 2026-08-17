# test_meta_ads_service.py — pure parsers without network.
from devscope_bridge.meta_ads import meta_ads_service as svc


def test_parse_campaign_budget_cents_to_currency():
    raw = {
        "id": "123",
        "name": "Summer",
        "status": "ACTIVE",
        "effective_status": "ACTIVE",
        "objective": "OUTCOME_LEADS",
        "daily_budget": "5000",
        "lifetime_budget": None,
    }
    out = svc.parse_campaign(raw)
    assert out["id"] == "123"
    assert out["name"] == "Summer"
    assert out["daily_budget"] == 50.0


def test_parse_insight_row_numeric_fields():
    raw = {
        "campaign_id": "c1",
        "campaign_name": "Test",
        "spend": "12.34",
        "impressions": "1000",
        "clicks": "50",
        "ctr": "5.0",
        "cpc": "0.25",
        "cpm": "12.34",
        "actions": [],
    }
    out = svc.parse_insight_row(raw)
    assert out["spend"] == 12.34
    assert out["impressions"] == 1000
    assert out["clicks"] == 50


def test_token_configured_false_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "_TOKEN_FILE", tmp_path / "missing.json")
    assert svc.token_configured() is False
