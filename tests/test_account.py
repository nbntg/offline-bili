import json

from offline_bili.account import has_login, import_legacy_data, login_config_path


def test_legacy_login_can_be_migrated_between_portable_folders(tmp_path):
    old_root = tmp_path / "old"
    new_data = tmp_path / "new" / "data"
    source = login_config_path(old_root / "data")
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps({"Cookie": {"is_login": True, "SESSDATA": "secret"}}),
        encoding="utf-8",
    )

    import_legacy_data(old_root, new_data)

    assert has_login(new_data)
    assert login_config_path(new_data).read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
