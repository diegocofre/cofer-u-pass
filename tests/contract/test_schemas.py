import json
from pathlib import Path


def test_required_versioned_schemas_exist_and_parse():
    root = Path(__file__).parents[2] / "schemas"
    expected = {
        "protocol-v1.schema.json", "event-v1.schema.json", "canonical-block-v1.schema.json",
        "adapter-rules-v1.schema.json", "adapter-manifest-v1.schema.json", "config-v1.schema.json", "run-v1.schema.json",
    }
    assert expected <= {p.name for p in root.glob("*.json")}
    for name in expected:
        assert isinstance(json.loads((root / name).read_text(encoding="utf-8")), dict)


def test_adapter_manifests_validate_against_versioned_schema():
    import jsonschema

    root = Path(__file__).parents[2]
    schema = json.loads((root / "schemas" / "adapter-manifest-v1.schema.json").read_text(encoding="utf-8"))
    for manifest_path in (root / "src" / "cofer_u_pass" / "adapters").glob("*/manifest.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        jsonschema.validate(manifest, schema)
