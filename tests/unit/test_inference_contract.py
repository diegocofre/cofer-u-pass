import pytest
from pydantic import ValidationError

from cofer_u_pass.adapters.base import AdapterManifest, AdapterRules, ProviderAdapter
from cofer_u_pass.domain.errors import AdapterMismatch, ProtocolError
from cofer_u_pass.domain.models import (
    InferenceSelection,
    InferenceState,
    ProtocolDefinition,
    ProtocolOperation,
    ProviderModel,
)
from cofer_u_pass.protocols.loader import build_plan


def _adapter() -> ProviderAdapter:
    rules = AdapterRules(
        provider="test",
        version="1.0.0",
        home_url="https://example.test/",
        allowed_origins=["https://example.test"],
        capabilities=[],
        authenticated=[],
        message_input=[],
        response=[],
    )
    manifest = AdapterManifest(
        provider="test",
        adapter_version="1.0.0",
        rule_version="1.0.0",
        capabilities=[],
        allowed_origins=["https://example.test"],
    )
    return ProviderAdapter(rules, manifest)


def test_provider_model_normalizes_and_deduplicates_efforts():
    model = ProviderModel(
        id=" gpt-test ",
        provider=" Test ",
        display_name=" GPT Test ",
        supported_efforts=["High", "high", " XHIGH "],
    )
    assert model.id == "gpt-test"
    assert model.provider == "test"
    assert model.display_name == "GPT Test"
    assert model.supported_efforts == ["high", "xhigh"]


def test_inference_selection_normalizes_effort():
    selection = InferenceSelection(model="  gpt-test  ", effort=" High ")
    assert selection.model == "gpt-test"
    assert selection.effort == "high"


def test_inference_selection_rejects_blank_values_after_trim():
    with pytest.raises(ValidationError):
        InferenceSelection(model="   ", effort="high")
    with pytest.raises(ValidationError):
        InferenceSelection(model="gpt-test", effort="   ")


def test_verified_inference_evidence_fails_closed_on_mismatch():
    adapter = _adapter()
    requested = InferenceSelection(model="gpt-test", effort="high")
    wrong = InferenceState(model="gpt-test", effort="medium", verified=True)
    with pytest.raises(AdapterMismatch, match="requested"):
        adapter.verified_inference_evidence(requested, wrong)


def test_verified_inference_evidence_records_requested_and_effective_state():
    adapter = _adapter()
    requested = InferenceSelection(model="gpt-test", effort="high")
    state = InferenceState(
        model="gpt-test",
        effort="high",
        native_model="GPT Test",
        native_effort="High",
        verified=True,
    )
    evidence = adapter.verified_inference_evidence(requested, state).data
    assert evidence["verified"] is True
    assert evidence["requested_model"] == "gpt-test"
    assert evidence["effective_model"] == "gpt-test"
    assert evidence["effective_effort"] == "high"
    assert evidence["native_effort"] == "High"


def test_configure_inference_is_a_first_class_plan_operation():
    protocol = ProtocolDefinition(
        protocol_id="inference-test",
        version="1.0.0",
        required_capabilities=["inference.model.select", "inference.effort.select"],
        operations=[
            ProtocolOperation(type="open_conversation"),
            ProtocolOperation(type="configure_inference", params={"model": "gpt-test", "effort": "High"}),
            ProtocolOperation(type="send_message", params={"text": "hello"}),
            ProtocolOperation(type="finalize"),
        ],
    )
    plan = build_plan(protocol, {}, 30)
    assert [action.type for action in plan.actions] == [
        "open_conversation",
        "configure_inference",
        "send_message",
        "finalize",
    ]
    assert plan.actions[1].external_effects == []
    assert plan.actions[1].inputs == {"model": "gpt-test", "effort": "high"}


def test_invalid_configure_inference_is_a_protocol_error():
    protocol = ProtocolDefinition(
        protocol_id="bad-inference-test",
        version="1.0.0",
        operations=[
            ProtocolOperation(type="open_conversation"),
            ProtocolOperation(type="configure_inference", params={"model": "   ", "effort": "high"}),
            ProtocolOperation(type="send_message", params={"text": "hello"}),
        ],
    )
    with pytest.raises(ProtocolError, match="configure_inference"):
        build_plan(protocol, {}, 30)
