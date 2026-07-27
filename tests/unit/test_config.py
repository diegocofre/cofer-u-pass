import pytest

from cofer_u_pass.config.settings import AppConfig


def test_non_loopback_is_rejected_by_loader(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(f'data_root = "{tmp_path.as_posix()}"\n[api]\nhost="0.0.0.0"\n', encoding="utf-8")
    from cofer_u_pass.config.settings import load_config
    with pytest.raises(ValueError, match="loopback"):
        load_config(config_path=path)
