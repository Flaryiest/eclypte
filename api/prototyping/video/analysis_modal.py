from pathlib import Path
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
    .pip_install("scenedetect")
    .add_local_python_source("analysis_cuda", "scenes", "motion", "impact", "credits", "poster")
)

app = modal.App("eclypte-video")


@app.function(image=image, gpu="T4", timeout=1800)
def analyze_remote_bytes(video_bytes: bytes, filename: str = "clip.mp4") -> dict:
    import os
    import tempfile
    from analysis_cuda import analyze_cuda

    suffix = Path(filename).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(video_bytes)
        tmp = f.name
    try:
        return analyze_cuda(tmp)
    finally:
        os.unlink(tmp)
