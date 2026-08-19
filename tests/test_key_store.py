import os

import pytest

from offline_bili.key_store import DeviceKeyStore


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI only")
def test_device_key_is_persisted_and_protected(tmp_path):
    path = tmp_path / "integrity.key"
    store = DeviceKeyStore(path)

    first = store.load_or_create()
    second = store.load_or_create()

    assert first == second
    assert len(first) == 32
    assert path.read_bytes() != first
