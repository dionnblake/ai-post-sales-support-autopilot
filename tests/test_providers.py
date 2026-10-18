import json

import pytest

from conftest import NOW
from support_autopilot.providers import LiveProvider, ProviderError, validate_draft


def response(value):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}]}


def test_live_mode_is_explicit_and_requires_configuration():
    with pytest.raises(ProviderError):
        LiveProvider(key="", model="", enabled=False)
    with pytest.raises(ProviderError):
        LiveProvider(key="synthetic-test-value", model="test-model", enabled=True, base_url="http://example.invalid")


def test_live_adapter_uses_structured_api_contract_without_logging_key(engine, invoice):
    calls = []
    def transport(payload):
        calls.append(payload)
        if len(calls) == 1:
            return response({"category": "billing", "urgency": "normal", "sentiment": "neutral"})
        data = json.loads(payload["messages"][1]["content"])
        excerpt = data["evidence"][0]
        return response({"body": excerpt["text"] + " [" + excerpt["id"] + "]", "citations": [excerpt["id"]]})
    engine.provider = LiveProvider(key="synthetic-test-value", model="test-model", enabled=True, transport=transport)
    ticket = engine.process(invoice, now=NOW)
    assert ticket["status"] == "NEEDS_REVIEW"
    assert ticket["mode"] == "live"
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "synthetic-test-value" not in json.dumps(calls)
    assert engine.outbox() == []


@pytest.mark.parametrize("bad", [response({"category": "made_up", "urgency": "normal", "sentiment": "neutral"}),
    {"choices": []}, {"choices": [None]}, {"choices": [[]]}, {"choices": ["invalid"]},
    {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}])
def test_invalid_model_output_fails_closed(engine, invoice, bad):
    engine.provider = LiveProvider(key="synthetic-test-value", model="test-model", enabled=True, transport=lambda _: bad)
    assert engine.process(invoice, now=NOW)["status"] == "ERROR"
    assert engine.outbox() == []


def test_unknown_or_missing_citations_are_rejected():
    with pytest.raises(ProviderError):
        validate_draft({"body": "A plausible but unsupported reply [invented]", "citations": ["invented"]},
                       [{"id": "billing-1"}])
    with pytest.raises(ProviderError):
        validate_draft({"body": "No evidence supports this reply", "citations": []}, [])
