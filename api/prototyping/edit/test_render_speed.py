import importlib
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


def _fake_modal_module():
    module = types.ModuleType("modal")

    class FakeImage:
        @staticmethod
        def debian_slim(**kwargs):
            del kwargs
            return FakeImage()

        def apt_install(self, *args):
            del args
            return self

        def pip_install(self, *args):
            del args
            return self

        def add_local_python_source(self, *args):
            del args
            return self

    class FakeVolume:
        def __init__(self):
            self.commit = MagicMock()

        @classmethod
        def from_name(cls, *args, **kwargs):
            del args, kwargs
            return cls()

    class FakeApp:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def function(self, **kwargs):
            def decorator(fn):
                fn._modal_function_kwargs = kwargs
                fn.remote = MagicMock(side_effect=fn)
                return fn

            return decorator

        def local_entrypoint(self):
            def decorator(fn):
                return fn

            return decorator

    module.Image = FakeImage
    module.Volume = FakeVolume
    module.App = FakeApp
    return module


def _load_render_modal(monkeypatch):
    monkeypatch.setitem(sys.modules, "modal", _fake_modal_module())
    sys.modules.pop("api.prototyping.edit.render_modal", None)
    return importlib.import_module("api.prototyping.edit.render_modal")


def test_main_render_defaults_preserve_medium_quality():
    from api.prototyping.edit import main as edit_main

    timeline = Path("C:/repo/timeline.json")
    out = Path("C:/repo/output.mp4")

    with patch("api.prototyping.edit.main.subprocess.run") as mock_run, \
         patch("pathlib.Path.mkdir"):
        edit_main._render(timeline, out)

    cmd = mock_run.call_args.args[0]
    assert "--encode-preset" in cmd
    assert cmd[cmd.index("--encode-preset") + 1] == "medium"
    assert "--threads" in cmd
    assert cmd[cmd.index("--threads") + 1] == "16"
    assert "--render-profile" in cmd
    assert cmd[cmd.index("--render-profile") + 1] == "standard"
    assert "--store-only" not in cmd


def test_main_render_store_only_keeps_medium_quality():
    from api.prototyping.edit import main as edit_main

    timeline = Path("C:/repo/timeline.json")
    out = Path("C:/repo/output.mp4")

    with patch("api.prototyping.edit.main.subprocess.run") as mock_run, \
         patch("pathlib.Path.mkdir"):
        edit_main._render(timeline, out, store_only=True)

    cmd = mock_run.call_args.args[0]
    assert "--store-only" in cmd
    assert cmd[cmd.index("--encode-preset") + 1] == "medium"


def test_main_render_boosted_profile_uses_boosted_thread_default():
    from api.prototyping.edit import main as edit_main

    timeline = Path("C:/repo/timeline.json")
    out = Path("C:/repo/output.mp4")

    with patch("api.prototyping.edit.main.subprocess.run") as mock_run, \
         patch("pathlib.Path.mkdir"):
        edit_main._render(timeline, out, render_profile="boosted", threads=None)

    cmd = mock_run.call_args.args[0]
    assert "--render-profile" in cmd
    assert cmd[cmd.index("--render-profile") + 1] == "boosted"
    assert "--threads" in cmd
    assert cmd[cmd.index("--threads") + 1] == "24"


def test_main_render_stage_inputs_local_is_forwarded():
    from api.prototyping.edit import main as edit_main

    timeline = Path("C:/repo/timeline.json")
    out = Path("C:/repo/output.mp4")

    with patch("api.prototyping.edit.main.subprocess.run") as mock_run, \
         patch("pathlib.Path.mkdir"):
        edit_main._render(timeline, out, render_stage_inputs_local=True)

    cmd = mock_run.call_args.args[0]
    assert "--render-stage-inputs-local" in cmd
    assert cmd[cmd.index("--encode-preset") + 1] == "medium"


def test_render_remote_to_volume_preserves_default_encode_settings(monkeypatch):
    render_modal = _load_render_modal(monkeypatch)
    render_modal.WORKDIR = "/workdir"

    rendered = MagicMock()
    rendered.stat.return_value.st_size = len(b"video")
    with patch.object(render_modal, "_render_impl", return_value=rendered) as mock_render:
        meta = render_modal.render_remote_to_volume(b"{}", "output.mp4")

    kwargs = mock_render.call_args.kwargs
    assert kwargs["encode_preset"] == "medium"
    assert kwargs["threads"] == 16
    assert kwargs["preview"] is False
    assert kwargs["stage_inputs_local"] is False
    render_modal.edit_volume.commit.assert_called_once()
    assert meta["remote_path"] == os.path.join("/workdir", "output.mp4")
    assert meta["size_bytes"] == len(b"video")


def test_render_remote_boosted_to_volume_uses_boosted_capacity(monkeypatch):
    render_modal = _load_render_modal(monkeypatch)
    render_modal.WORKDIR = "/workdir"

    rendered = MagicMock()
    rendered.stat.return_value.st_size = len(b"video")
    with patch.object(render_modal, "_render_impl", return_value=rendered) as mock_render:
        render_modal.render_remote_boosted_to_volume(b"{}", "output.mp4")

    kwargs = mock_render.call_args.kwargs
    assert kwargs["threads"] == 24
    assert render_modal.render_remote_boosted_to_volume._modal_function_kwargs["cpu"] == 24
    assert render_modal.render_remote_boosted_to_volume._modal_function_kwargs["memory"] == 32768


def test_render_remote_to_volume_stage_inputs_local_preserves_medium_quality(monkeypatch):
    render_modal = _load_render_modal(monkeypatch)
    render_modal.WORKDIR = "/workdir"

    rendered = MagicMock()
    rendered.stat.return_value.st_size = len(b"video")
    with patch.object(render_modal, "_render_impl", return_value=rendered) as mock_render:
        render_modal.render_remote_to_volume(
            b"{}",
            "output.mp4",
            stage_inputs_local=True,
        )

    kwargs = mock_render.call_args.kwargs
    assert kwargs["stage_inputs_local"] is True
    assert kwargs["encode_preset"] == "medium"


def test_render_modal_main_store_only_skips_local_write(monkeypatch):
    render_modal = _load_render_modal(monkeypatch)
    render_modal.render_remote_to_volume.remote = MagicMock(return_value={
        "remote_path": "/workdir/output.mp4",
        "size_bytes": 4096,
        "preview": False,
        "encode_preset": "medium",
        "threads": 16,
    })
    render_modal.render_remote.remote = MagicMock()

    with patch("pathlib.Path.read_bytes", return_value=b"{}"), \
         patch("pathlib.Path.write_bytes") as mock_write_bytes:
        render_modal.main(
            timeline="C:/repo/timeline.json",
            out="C:/repo/output.mp4",
            store_only=True,
        )

    render_modal.render_remote_to_volume.remote.assert_called_once_with(
        b"{}",
        "output.mp4",
        preview=False,
        encode_preset="medium",
        threads=16,
        stage_inputs_local=False,
    )
    render_modal.render_remote.remote.assert_not_called()
    mock_write_bytes.assert_not_called()


def test_render_modal_main_boosted_store_only_selects_boosted_remote(monkeypatch):
    render_modal = _load_render_modal(monkeypatch)
    render_modal.render_remote_to_volume.remote = MagicMock()
    render_modal.render_remote_boosted_to_volume.remote = MagicMock(return_value={
        "remote_path": "/workdir/output.mp4",
        "size_bytes": 4096,
        "preview": False,
        "encode_preset": "medium",
        "threads": 24,
    })
    render_modal.render_remote.remote = MagicMock()
    render_modal.render_remote_boosted.remote = MagicMock()

    with patch("pathlib.Path.read_bytes", return_value=b"{}"), \
         patch("pathlib.Path.write_bytes") as mock_write_bytes:
        render_modal.main(
            timeline="C:/repo/timeline.json",
            out="C:/repo/output.mp4",
            store_only=True,
            render_profile="boosted",
        )

    render_modal.render_remote_boosted_to_volume.remote.assert_called_once_with(
        b"{}",
        "output.mp4",
        preview=False,
        encode_preset="medium",
        threads=24,
        stage_inputs_local=False,
    )
    render_modal.render_remote_to_volume.remote.assert_not_called()
    render_modal.render_remote.remote.assert_not_called()
    render_modal.render_remote_boosted.remote.assert_not_called()
    mock_write_bytes.assert_not_called()


def test_render_modal_main_download_path_writes_local_output(monkeypatch):
    render_modal = _load_render_modal(monkeypatch)
    render_modal.render_remote.remote = MagicMock(return_value=b"video-bytes")
    render_modal.render_remote_boosted.remote = MagicMock()
    render_modal.render_remote_to_volume.remote = MagicMock()
    render_modal.render_remote_boosted_to_volume.remote = MagicMock()

    with patch("pathlib.Path.read_bytes", return_value=b"{}"), \
         patch("pathlib.Path.write_bytes") as mock_write_bytes, \
         patch("pathlib.Path.mkdir"):
        render_modal.main(timeline="C:/repo/timeline.json", out="C:/repo/output.mp4")

    render_modal.render_remote.remote.assert_called_once_with(
        b"{}",
        "output.mp4",
        preview=False,
        encode_preset="medium",
        threads=16,
        stage_inputs_local=False,
    )
    render_modal.render_remote_to_volume.remote.assert_not_called()
    render_modal.render_remote_boosted.remote.assert_not_called()
    render_modal.render_remote_boosted_to_volume.remote.assert_not_called()
    mock_write_bytes.assert_called_once_with(b"video-bytes")


def test_render_modal_main_stage_inputs_local_forwarded(monkeypatch):
    render_modal = _load_render_modal(monkeypatch)
    render_modal.render_remote.remote = MagicMock(return_value=b"video-bytes")
    render_modal.render_remote_boosted.remote = MagicMock()
    render_modal.render_remote_to_volume.remote = MagicMock()
    render_modal.render_remote_boosted_to_volume.remote = MagicMock()

    with patch("pathlib.Path.read_bytes", return_value=b"{}"), \
         patch("pathlib.Path.write_bytes"), \
         patch("pathlib.Path.mkdir"):
        render_modal.main(
            timeline="C:/repo/timeline.json",
            out="C:/repo/output.mp4",
            render_stage_inputs_local=True,
        )

    render_modal.render_remote.remote.assert_called_once_with(
        b"{}",
        "output.mp4",
        preview=False,
        encode_preset="medium",
        threads=16,
        stage_inputs_local=True,
    )
