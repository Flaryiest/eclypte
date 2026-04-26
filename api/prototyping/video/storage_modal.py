from pathlib import Path
import tempfile

import modal

CUDA_BASE = "nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04"
OPENCV_VERSION = "4.10.0"

image = (
    modal.Image.from_registry(CUDA_BASE, add_python="3.11")
    .apt_install(
        "ffmpeg", "git", "cmake", "build-essential", "pkg-config",
        "libavcodec-dev", "libavformat-dev", "libswscale-dev",
        "libjpeg-dev", "libpng-dev",
    )
    .pip_install("numpy")
    .run_commands(
        f"git clone --depth 1 --branch {OPENCV_VERSION} "
        "https://github.com/opencv/opencv.git /opt/opencv",
        f"git clone --depth 1 --branch {OPENCV_VERSION} "
        "https://github.com/opencv/opencv_contrib.git /opt/opencv_contrib",
        "mkdir /opt/opencv/build && cd /opt/opencv/build && cmake "
        "-DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local "
        "-DWITH_CUDA=ON -DWITH_CUDNN=ON -DCUDA_ARCH_BIN=\"7.5;8.0;8.6;9.0\" "
        "-DOPENCV_EXTRA_MODULES_PATH=/opt/opencv_contrib/modules "
        "-DPYTHON3_EXECUTABLE=$(which python3) "
        "-DOPENCV_PYTHON3_INSTALL_PATH=$(python3 -c 'import sysconfig;print(sysconfig.get_paths()[\"purelib\"])') "
        "-DBUILD_EXAMPLES=OFF -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF "
        "-DBUILD_opencv_python3=ON -DOPENCV_DNN_CUDA=OFF "
        "..",
        "cd /opt/opencv/build && make -j$(nproc) && make install && ldconfig",
        "rm -rf /opt/opencv /opt/opencv_contrib",
    )
    .pip_install("scenedetect", "boto3")
    .add_local_python_source("analysis_cuda", "scenes", "motion", "impact", "progress_events")
)

app = modal.App("eclypte-video-r2")
storage_image = image


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
def analyze_r2(
    r2_config: dict,
    source_key: str,
    filename: str,
    progress_context: dict | None = None,
) -> dict:
    from analysis_cuda import analyze_cuda
    from progress_events import emit_progress

    suffix = Path(filename).suffix or ".mp4"
    client = _s3_client(r2_config)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        emit_progress(progress_context, 2, "Downloading source video")
        client.download_fileobj(r2_config["bucket"], source_key, tmp)
        tmp_path = tmp.name
    try:
        return analyze_cuda(
            tmp_path,
            progress_callback=lambda percent, detail: emit_progress(
                progress_context,
                percent,
                detail,
            ),
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
