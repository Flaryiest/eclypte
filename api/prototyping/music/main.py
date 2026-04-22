import json
from importlib import import_module
from pathlib import Path

from api.storage.factory import get_default_user_id, get_object_store
from api.storage.repository import StorageRepository

ytdownload = None
lyrics = None
app = None
analyze_remote = None
publish_music_artifacts = None


def _load_runtime_dependencies() -> None:
    global ytdownload, lyrics, app, analyze_remote, publish_music_artifacts

    if (
        ytdownload is not None
        and lyrics is not None
        and app is not None
        and analyze_remote is not None
        and publish_music_artifacts is not None
    ):
        return

    if __package__:
        prefix = f"{__package__}."
    else:
        prefix = ""

    ytdownload = import_module(f"{prefix}ytdownload")
    lyrics = import_module(f"{prefix}lyrics")
    analysis_modal = import_module(f"{prefix}analysis_modal")
    publish_module = import_module(f"{prefix}storage_publish")
    app = analysis_modal.app
    analyze_remote = analysis_modal.analyze_remote
    publish_music_artifacts = publish_module.publish_music_artifacts


def _print_publish_summary(summary) -> None:
    print(
        "published to R2 "
        f"run={summary.run_id} "
        f"audio={summary.audio.version_id} "
        f"analysis={summary.analysis.version_id} "
        f"lyrics={summary.lyrics.version_id}"
    )


def main():
    _load_runtime_dependencies()
    title = ytdownload.main(ytdownload.url)

    wav = Path("./content/output.wav")
    out = Path("./content/output.json")
    lyrics_path = Path("./content/lyrics.txt")
    with app.run():
        result = analyze_remote.remote(wav.read_bytes(), wav.name)
    result["source"]["path"] = str(wav)
    out.write_text(json.dumps(result, indent=2))

    lyrics.main(title)

    store = get_object_store(required=False)
    if store is None:
        print("R2 publish skipped: storage not configured.")
        return

    summary = publish_music_artifacts(
        repository=StorageRepository(store),
        user_id=get_default_user_id(),
        wav_path=wav,
        analysis_path=out,
        lyrics_path=lyrics_path,
    )
    _print_publish_summary(summary)


if __name__ == "__main__":
    main()
