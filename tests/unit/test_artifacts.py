from pathlib import Path

import pytest

from cofer_u_pass.persistence.artifacts import ArtifactStore


def test_artifact_ingest_hashes_and_confines(config, tmp_path):
    source = tmp_path / "result.txt"
    source.write_text("hello", encoding="utf-8")
    store = ArtifactStore(config)
    ref = store.ingest(source, run_id="r1", action_id="a1")
    assert ref.size == 5
    assert len(ref.sha256) == 64
    assert Path(ref.path).parent == config.artifacts_path / "r1"


def test_input_symlink_is_rejected(config, tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation not available")
    with pytest.raises(ValueError):
        ArtifactStore(config).validate_input(link)
