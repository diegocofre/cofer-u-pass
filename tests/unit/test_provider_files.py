from __future__ import annotations

import io

import pytest

from cofer_u_pass.provider.files import ProviderFileStore


def test_provider_file_store_roundtrip(config):
    store = ProviderFileStore(config)
    meta = store.put_stream(io.BytesIO(b"abc"), filename="input.txt")
    assert meta.id.startswith("file-")
    assert store.content_path(meta.id).read_bytes() == b"abc"
    assert store.get(meta.id).sha256 == meta.sha256
    store.delete(meta.id)
    with pytest.raises(KeyError):
        store.get(meta.id)
