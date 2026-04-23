from pathlib import Path
import tempfile

import modal

from analysis_modal import image

app = modal.App("eclypte-video-r2")
storage_image = image.pip_install("boto3")


def _s3_client(config: dict):
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=config["endpoint_url"],
        aws_access_key_id=config["access_key_id"],
        aws_secret_access_key=config["secret_access_key"],
        region_name=config.get("region_name", "auto"),
    )


@app.function(image=storage_image, gpu="T4", timeout=14400)
def analyze_r2(r2_config: dict, source_key: str, filename: str) -> dict:
    from analysis_cuda import analyze_cuda

    suffix = Path(filename).suffix or ".mp4"
    client = _s3_client(r2_config)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        client.download_fileobj(r2_config["bucket"], source_key, tmp)
        tmp_path = tmp.name
    try:
        return analyze_cuda(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
