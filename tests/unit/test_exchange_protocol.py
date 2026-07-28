from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from cofer_u_pass.exchange.models import ExchangeProtocol
from cofer_u_pass.exchange.normalizer import normalize_input_files, validate_output_bundle


def test_exchange_protocol_defaults_to_text():
    protocol = ExchangeProtocol.model_validate({"schema": "cofer-u-pass.exchange/1"})
    assert protocol.output.kind == "text"
    assert protocol.input.strategy == "auto"


def test_bundle_protocol_requires_safe_zip_name():
    protocol = ExchangeProtocol.model_validate({
        "schema": "cofer-u-pass.exchange/1",
        "output": {"kind": "bundle", "required_files": ["SPEC.md"]},
    })
    assert protocol.output.filename == "result.zip"
    with pytest.raises(ValueError):
        ExchangeProtocol.model_validate({
            "schema": "cofer-u-pass.exchange/1",
            "output": {"kind": "bundle", "filename": "../result.zip"},
        })


def test_zip_input_is_safely_normalized(config, tmp_path: Path):
    source = tmp_path / "context.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("src/a.py", "print('a')")
        archive.writestr("README.md", "# Demo")
    result = normalize_input_files([source], config, strategy="inline")
    try:
        assert "context.zip/src/a.py" in result.inline_context
        assert "print('a')" in result.inline_context
        assert "context.zip/README.md" in result.inline_context
    finally:
        result.cleanup()


def test_zip_path_traversal_is_rejected(config, tmp_path: Path):
    source = tmp_path / "bad.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError, match="unsafe ZIP member"):
        normalize_input_files([source], config)


def test_output_bundle_required_members_are_validated(config, tmp_path: Path):
    source = tmp_path / "architecture.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("SPEC.md", "# Spec")
        archive.writestr("DECISIONS.md", "# Decisions")
    names = validate_output_bundle(source, config, required_files=["SPEC.md"])
    assert names == ["SPEC.md", "DECISIONS.md"]
    with pytest.raises(ValueError, match="missing required"):
        validate_output_bundle(source, config, required_files=["ACCEPTANCE.md"])


def test_optional_bundle_members_are_allowed_when_extras_are_disabled(tmp_path, config):
    import zipfile
    from cofer_u_pass.exchange.normalizer import validate_output_bundle

    bundle = tmp_path / "result.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("SPEC.md", "spec")
        zf.writestr("DECISIONS.md", "optional")
    members = validate_output_bundle(
        bundle,
        config,
        required_files=["SPEC.md"],
        optional_files=["DECISIONS.md"],
        allow_extra_files=False,
    )
    assert members == ["SPEC.md", "DECISIONS.md"]


def test_text_protocol_rejects_unused_file_contract_fields():
    with pytest.raises(ValueError, match="text output cannot declare filenames"):
        ExchangeProtocol.model_validate({
            "schema": "cofer-u-pass.exchange/1",
            "output": {"kind": "text", "required_files": ["RESULT.md"]},
        })


def test_output_bundle_rejects_nested_zip(tmp_path, config):
    import zipfile
    from cofer_u_pass.exchange.normalizer import validate_output_bundle

    bundle = tmp_path / "result.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("SPEC.md", "# spec")
        archive.writestr("nested.zip", b"PK\x05\x06" + b"\x00" * 18)

    with pytest.raises(ValueError, match="nested archives"):
        validate_output_bundle(bundle, config, required_files=["SPEC.md"])
