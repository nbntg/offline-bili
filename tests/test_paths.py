from offline_bili.paths import AppPaths


def test_portable_directories_are_relative_to_root(tmp_path):
    paths = AppPaths.from_root(tmp_path)
    paths.ensure()

    assert paths.data == tmp_path / "data"
    assert paths.library == tmp_path / "library"
    assert paths.logs == tmp_path / "logs"
    assert paths.tools == tmp_path / "tools"
    assert all(path.is_dir() for path in (paths.data, paths.library, paths.logs, paths.tools))

