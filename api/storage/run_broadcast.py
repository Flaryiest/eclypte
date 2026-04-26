from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from .models import RunEvent, RunManifest


class RunUpdateBroadcaster(Protocol):
    def publish_run_manifest(self, manifest: RunManifest) -> None: ...
    def publish_run_event(self, event: RunEvent) -> None: ...

    def listen(
        self,
        *,
        user_id: str,
        run_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...
