from pathlib import Path
import modal

REQUIREMENTS = Path(__file__).parent.parent.parent / "requirements-modal.txt"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "git", "build-essential")
    .pip_install("cython", "numpy", "boto3")
    .pip_install_from_requirements(str(REQUIREMENTS))
    .run_commands(
        "pip install natten==0.17.4+torch250cu121 "
        "--trusted-host shi-labs.com "
        "-f https://shi-labs.com/natten/wheels/cu121/torch2.5.0/"
    )
    .run_commands("rm -rf /root/.cache && ln -s /cache /root/.cache")
    .add_local_python_source("analysis", "progress_events")
)

app = modal.App("eclypte-analysis")
model_cache = modal.Volume.from_name("allin1-cache", create_if_missing=True)


@app.function(
    image=image,
    gpu="T4",
    timeout=600,
    volumes={"/cache": model_cache},
)
def analyze_remote(audio_bytes: bytes, filename: str = "input.wav", progress_context: dict | None = None) -> dict:
    import os
    import tempfile
    from analysis import analyze
    from progress_events import emit_progress

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, filename)
        with open(path, "wb") as f:
            f.write(audio_bytes)
        return analyze(
            path,
            progress_callback=lambda percent, detail: emit_progress(
                progress_context,
                percent,
                detail,
            ),
        )


@app.local_entrypoint()
def main(wav: str = "./content/output.wav", out: str = "./content/output.json"):
    import json

    result = analyze_remote.remote(Path(wav).read_bytes(), Path(wav).name)
    Path(out).write_text(json.dumps(result, indent=2))
    print(
        f"wrote {out}  ({len(result['beats_sec'])} beats, "
        f"tempo {result['tempo_bpm']} BPM)"
    )
