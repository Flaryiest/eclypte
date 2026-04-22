from contextlib import nullcontext
from types import SimpleNamespace


def _seed_music_workspace(tmp_path):
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    return content_dir


def test_main_skips_cloud_publish_when_storage_is_unconfigured(tmp_path, monkeypatch):
    from api.prototyping.music import main as main_module

    content_dir = _seed_music_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    def fake_download(_url):
        (content_dir / "output.wav").write_bytes(b"wav-bytes")
        return "Test Song"

    def fake_lyrics(title):
        assert title == "Test Song"
        (content_dir / "lyrics.txt").write_text("line one", encoding="utf-8")
        return "line one"

    monkeypatch.setattr(
        main_module,
        "ytdownload",
        SimpleNamespace(url="https://example.test/song", main=fake_download),
    )
    monkeypatch.setattr(main_module, "lyrics", SimpleNamespace(main=fake_lyrics))
    monkeypatch.setattr(main_module, "app", SimpleNamespace(run=lambda: nullcontext()))
    monkeypatch.setattr(
        main_module,
        "analyze_remote",
        SimpleNamespace(remote=lambda *_: {"source": {}, "tempo_bpm": 120}),
    )
    monkeypatch.setattr(main_module, "get_object_store", lambda required=False: None)

    publish_calls = []
    monkeypatch.setattr(
        main_module,
        "publish_music_artifacts",
        lambda **kwargs: publish_calls.append(kwargs),
    )

    main_module.main()

    assert (content_dir / "output.json").exists()
    assert publish_calls == []


def test_main_publishes_music_outputs_when_storage_is_available(tmp_path, monkeypatch):
    from api.prototyping.music import main as main_module

    content_dir = _seed_music_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    def fake_download(_url):
        (content_dir / "output.wav").write_bytes(b"wav-bytes")
        return "Test Song"

    def fake_lyrics(_title):
        (content_dir / "lyrics.txt").write_text("line one", encoding="utf-8")
        return "line one"

    store = object()
    repository = object()
    captured = {}

    monkeypatch.setattr(
        main_module,
        "ytdownload",
        SimpleNamespace(url="https://example.test/song", main=fake_download),
    )
    monkeypatch.setattr(main_module, "lyrics", SimpleNamespace(main=fake_lyrics))
    monkeypatch.setattr(main_module, "app", SimpleNamespace(run=lambda: nullcontext()))
    monkeypatch.setattr(
        main_module,
        "analyze_remote",
        SimpleNamespace(remote=lambda *_: {"source": {}, "tempo_bpm": 120}),
    )
    monkeypatch.setattr(main_module, "get_object_store", lambda required=False: store)
    monkeypatch.setattr(main_module, "get_default_user_id", lambda: "local_dev")
    monkeypatch.setattr(main_module, "StorageRepository", lambda store_arg: repository)
    monkeypatch.setattr(
        main_module,
        "publish_music_artifacts",
        lambda **kwargs: captured.update(kwargs)
        or SimpleNamespace(
            run_id="run_123",
            audio=SimpleNamespace(version_id="ver_audio"),
            analysis=SimpleNamespace(version_id="ver_analysis"),
            lyrics=SimpleNamespace(version_id="ver_lyrics"),
        ),
    )

    main_module.main()

    assert captured["repository"] is repository
    assert captured["user_id"] == "local_dev"
    assert captured["wav_path"].resolve() == (content_dir / "output.wav").resolve()
    assert captured["analysis_path"].resolve() == (content_dir / "output.json").resolve()
    assert captured["lyrics_path"].resolve() == (content_dir / "lyrics.txt").resolve()
