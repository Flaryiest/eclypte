import importlib
import sys
import types
from unittest.mock import MagicMock


def _fake_modal_module():
    module = types.ModuleType("modal")

    class FakeImage:
        @staticmethod
        def debian_slim(**kwargs):
            del kwargs
            return FakeImage()

        def pip_install(self, *args):
            del args
            return self

        def add_local_python_source(self, *args):
            del args
            return self

    class FakeVolume:
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

    module.App = FakeApp
    module.Image = FakeImage
    module.Volume = FakeVolume
    return module


def _load_query_modal(monkeypatch):
    monkeypatch.setitem(sys.modules, "modal", _fake_modal_module())
    sys.modules.pop("api.prototyping.edit.index.query_modal", None)
    return importlib.import_module("api.prototyping.edit.index.query_modal")


def test_query_index_keeps_container_warm_longer_for_bursty_runs(monkeypatch):
    query_modal = _load_query_modal(monkeypatch)

    assert query_modal.query_index._modal_function_kwargs["gpu"] == "T4"
    assert query_modal.query_index._modal_function_kwargs["scaledown_window"] == 600
