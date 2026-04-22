from pathlib import Path
import os


def test_main_redirects_syncedlyrics_cache_to_local_content_on_windows(
    tmp_path, monkeypatch
):
    from api.prototyping.music import lyrics as lyrics_module

    content_dir = tmp_path / "content"
    content_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\denied-cache")
    monkeypatch.setattr(lyrics_module.os, "name", "nt", raising=False)

    seen = {}

    def fake_search(query):
        seen["query"] = query
        seen["localappdata"] = os.environ["LOCALAPPDATA"]
        token_path = (
            Path(seen["localappdata"]) / "syncedlyrics" / "musixmatch_token.json"
        )
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("{}", encoding="utf-8")
        return "line one"

    monkeypatch.setattr(lyrics_module.syncedlyrics, "search", fake_search)

    result = lyrics_module.main("Test Song (Official Audio)")

    assert result == "line one"
    assert seen["query"] == "Test Song"
    assert Path(seen["localappdata"]).resolve() == (content_dir / ".cache").resolve()
    assert (
        content_dir / ".cache" / "syncedlyrics" / "musixmatch_token.json"
    ).exists()
    assert (content_dir / "lyrics.txt").read_text(encoding="utf-8") == "line one"
    assert os.environ["LOCALAPPDATA"] == r"C:\denied-cache"
