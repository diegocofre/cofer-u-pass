import pytest

from cofer_u_pass.adapters.chatgpt.adapter import _model_choice, _normalize_effort
from cofer_u_pass.adapters.registry import AdapterRegistry


@pytest.mark.parametrize(
    ("label", "expected_id", "expected_display"),
    [
        ("GPT-5.6 Sol", "gpt-5.6-sol", "GPT-5.6 Sol"),
        ("ChatGPT model: GPT 5.6 Pro", "gpt-5.6-pro", "GPT 5.6 Pro"),
        ("o3.2 Pro", "o3.2-pro", "o3.2 Pro"),
        ("5.6 Sol", "5.6-sol", "5.6 Sol"),
    ],
)
def test_chatgpt_model_labels_become_deterministic_public_ids(label, expected_id, expected_display):
    assert _model_choice(label) == (expected_id, expected_display)


def test_chatgpt_unknown_model_family_can_use_stable_native_picker_id():
    assert _model_choice("Orion Preview", "model-switcher-orion-preview") == (
        "orion-preview",
        "Orion Preview",
    )


def test_chatgpt_picker_controls_are_not_mistaken_for_models():
    assert _model_choice("GPT-5.6 Sol", "model-switcher-dropdown-button") == (
        "gpt-5.6-sol",
        "GPT-5.6 Sol",
    )
    assert _model_choice("Configure", "model-switcher-configure") is None


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Medium", "medium"),
        ("Standard", "medium"),
        ("High", "high"),
        ("Advanced", "high"),
        ("Extra High", "xhigh"),
        ("Maximum", "max"),
        ("Reasoning effort: Max", "max"),
        ("Medio", "medium"),
        ("Alto", "high"),
        ("Muy alto", "xhigh"),
        ("Máximo", "max"),
        ("Low", "low"),
        ("Off", "none"),
    ],
)
def test_chatgpt_intelligence_labels_map_to_normalized_effort(label, expected):
    assert _normalize_effort(label) == expected


def test_chatgpt_native_effort_ids_are_normalized_without_visible_english_text():
    assert _normalize_effort("reasoning-effort-high") == "high"
    assert _normalize_effort("intelligence_extra_high") == "xhigh"


def test_chatgpt_intelligence_mapping_does_not_treat_combined_model_labels_as_effort():
    assert _normalize_effort("Pro Standard") is None
    assert _normalize_effort("Pro Extended") is None
    assert _normalize_effort("GPT-5.6 High") is None


def test_chatgpt_non_model_menu_rows_are_not_published_as_models():
    assert _model_choice("Configure") is None
    assert _model_choice("Legacy models") is None
    assert _model_choice("Extra High") is None


def test_chatgpt_registry_advertises_inference_capabilities_consistently():
    adapter = AdapterRegistry().create("chatgpt")
    assert adapter.adapter_version == "1.2.2"
    assert "inference.model.discover" in adapter.capabilities
    assert "inference.model.select" in adapter.capabilities
    assert "inference.effort.select" in adapter.capabilities
    assert "inference.state.verify" in adapter.capabilities
