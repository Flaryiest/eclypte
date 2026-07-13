from pathlib import Path
import modal

REQUIREMENTS = Path(__file__).parent.parent.parent / "requirements-lyrics-modal.txt"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .pip_install_from_requirements(str(REQUIREMENTS))
    # Whisper (~/.cache/whisper) and demucs (~/.cache/torch/hub) model downloads
    # land on the persistent volume instead of re-downloading per container.
    .run_commands("rm -rf /root/.cache && ln -s /cache /root/.cache")
    .add_local_python_source("lyrics_align", "progress_events")
)

app = modal.App("eclypte-lyrics")
model_cache = modal.Volume.from_name("lyrics-align-cache", create_if_missing=True)


@app.function(
    image=image,
    gpu="T4",
    # Demucs separation + large-v3 alignment on a long song, plus a possible
    # transcription fallback pass.
    timeout=900,
    volumes={"/cache": model_cache},
)
def align_lyrics_remote(
    audio_bytes: bytes,
    filename: str = "input.wav",
    lyrics_text: str | None = None,
    progress_context: dict | None = None,
) -> dict | None:
    import os
    import tempfile
    from lyrics_align import produce_lyrics_timing
    from progress_events import emit_progress

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, filename)
        with open(path, "wb") as f:
            f.write(audio_bytes)
        return produce_lyrics_timing(
            path,
            lyrics_text,
            progress_callback=lambda percent, detail: emit_progress(
                progress_context,
                percent,
                detail,
            ),
        )
