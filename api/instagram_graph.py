"""Direct Instagram Graph API publishing client (reach-recovery Phase B).

Stdlib-only HTTP mirroring ``BufferClient``'s urllib pattern: pure payload
builders and response parsers are unit-tested; ``GraphPublisher`` wraps them
with form-encoded requests against ``graph.facebook.com``. Field shapes that
depend on the live API (``copyright_check_status``, ``audio_configuration``)
are handled tolerantly — the Task 0 probe in
``docs/superpowers/plans/2026-08-04-graph-publishing.md`` confirms them.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib import parse as urlparse
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

DEFAULT_GRAPH_API_BASE = "https://graph.facebook.com/v23.0"

# Reel insight metrics to request on the metrics-refresh pass. Names align
# with the lowercase keys the Buffer path stores, so performance_score's
# views->impressions fallback works across providers. The API returns only
# what it supports for the media — absent metrics stay absent.
GRAPH_INSIGHT_METRICS = "views,reach,likes,comments,shares,saved,total_interactions"

CONTAINER_POLL_INTERVAL_SEC = 5.0
CONTAINER_TIMEOUT_SEC = 600.0


class GraphApiError(RuntimeError):
    pass


class GraphConfigError(GraphApiError):
    """The graph provider is selected but its env config is incomplete."""


class CopyrightBlockedError(GraphApiError):
    """The container's copyright check reported matches — the send is vetoed."""


@dataclass(frozen=True)
class GraphConfig:
    ig_user_id: str
    access_token: str
    api_base: str = DEFAULT_GRAPH_API_BASE

    @classmethod
    def from_env(cls) -> "GraphConfig":
        ig_user_id = os.environ.get("ECLYPTE_IG_USER_ID") or ""
        access_token = os.environ.get("ECLYPTE_IG_ACCESS_TOKEN") or ""
        missing = [
            name
            for name, value in (
                ("ECLYPTE_IG_USER_ID", ig_user_id),
                ("ECLYPTE_IG_ACCESS_TOKEN", access_token),
            )
            if not value
        ]
        if missing:
            raise GraphConfigError(f"missing required env vars: {', '.join(missing)}")
        return cls(
            ig_user_id=ig_user_id,
            access_token=access_token,
            api_base=os.environ.get("ECLYPTE_GRAPH_API_BASE", DEFAULT_GRAPH_API_BASE),
        )


def build_reel_container_params(
    *,
    video_url: str,
    caption: str,
    share_to_feed: bool = True,
    cover_url: str | None = None,
    thumb_offset_ms: int | None = None,
    audio_name: str | None = None,
    audio_config: dict[str, Any] | None = None,
) -> dict[str, str]:
    params: dict[str, str] = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true" if share_to_feed else "false",
    }
    if cover_url:
        params["cover_url"] = cover_url
    if thumb_offset_ms is not None:
        params["thumb_offset"] = str(thumb_offset_ms)
    if audio_name:
        params["audio_name"] = audio_name
    if audio_config:
        params["audio_configuration"] = json.dumps(audio_config)
    return params


def parse_insights(payload: dict[str, Any]) -> dict[str, float]:
    """Insights entries -> {metric_name: value}, tolerantly.

    A metric the API did not report stays absent — never zero (the same
    discipline as Buffer's ``get_post_metrics``)."""
    metrics: dict[str, float] = {}
    for entry in payload.get("data") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        value: Any = None
        values = entry.get("values")
        if isinstance(values, list) and values and isinstance(values[0], dict):
            value = values[0].get("value")
        if value is None and isinstance(entry.get("total_value"), dict):
            value = entry["total_value"].get("value")
        if isinstance(value, (int, float)):
            metrics[str(name)] = float(value)
    return metrics


def copyright_matches_found(status: Any) -> bool:
    """Conservative read of a container's copyright_check_status blob."""
    if not isinstance(status, dict):
        return False
    return bool(status.get("matches_found"))


class GraphPublisher:
    def __init__(self, config: GraphConfig):
        self._config = config

    @classmethod
    def from_env(cls) -> "GraphPublisher":
        return cls(GraphConfig.from_env())

    def create_reel_container(
        self,
        *,
        video_url: str,
        caption: str,
        share_to_feed: bool = True,
        cover_url: str | None = None,
        thumb_offset_ms: int | None = None,
        audio_name: str | None = None,
        audio_config: dict[str, Any] | None = None,
    ) -> str:
        params = build_reel_container_params(
            video_url=video_url,
            caption=caption,
            share_to_feed=share_to_feed,
            cover_url=cover_url,
            thumb_offset_ms=thumb_offset_ms,
            audio_name=audio_name,
            audio_config=audio_config,
        )
        response = self._request("POST", f"/{self._config.ig_user_id}/media", params)
        container_id = response.get("id")
        if not container_id:
            raise GraphApiError("Graph API did not return a container id")
        return str(container_id)

    def get_container_status(self, container_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/{container_id}",
            {"fields": "status_code,status,copyright_check_status"},
        )

    def wait_for_container(
        self,
        container_id: str,
        *,
        timeout_sec: float = CONTAINER_TIMEOUT_SEC,
        poll_interval_sec: float = CONTAINER_POLL_INTERVAL_SEC,
        sleep: Callable[[float], None] = time.sleep,
    ) -> dict[str, Any]:
        """Poll until the container is FINISHED; raise on ERROR/EXPIRED/timeout."""
        waited = 0.0
        while True:
            status = self.get_container_status(container_id)
            code = str(status.get("status_code") or "").upper()
            if code == "FINISHED":
                return status
            if code in {"ERROR", "EXPIRED"}:
                detail = status.get("status") or code
                raise GraphApiError(f"reel container failed processing: {detail}")
            if waited >= timeout_sec:
                raise GraphApiError(
                    f"reel container not finished after {timeout_sec:.0f}s (last status: {code or 'unknown'})"
                )
            sleep(poll_interval_sec)
            waited += poll_interval_sec

    def publish_container(self, container_id: str) -> str:
        response = self._request(
            "POST",
            f"/{self._config.ig_user_id}/media_publish",
            {"creation_id": container_id},
        )
        media_id = response.get("id")
        if not media_id:
            raise GraphApiError("Graph API did not return a media id on publish")
        return str(media_id)

    def get_media(self, media_id: str, *, fields: str) -> dict[str, Any]:
        return self._request("GET", f"/{media_id}", {"fields": fields})

    def get_insights(self, media_id: str, *, metrics: str) -> dict[str, float]:
        response = self._request("GET", f"/{media_id}/insights", {"metric": metrics})
        return parse_insights(response)

    def search_audio(self, query: str) -> list[dict[str, Any]]:
        """Licensed/trending audio search (Audio API, ~Q2 2026; Facebook-Login
        connections). Empty query returns trending audio per the docs."""
        params = {"audio_type": "music"}
        if query:
            params["search_query"] = query
        response = self._request(
            "GET", f"/{self._config.ig_user_id}/ig_audio", params
        )
        data = response.get("data")
        return [entry for entry in data if isinstance(entry, dict)] if isinstance(data, list) else []

    def _request(self, method: str, path: str, params: dict[str, str]) -> dict[str, Any]:
        merged = {**params, "access_token": self._config.access_token}
        url = f"{self._config.api_base}{path}"
        body: bytes | None = None
        if method == "GET":
            url = f"{url}?{urlparse.urlencode(merged)}"
        else:
            body = urlparse.urlencode(merged).encode("utf-8")
        request = urlrequest.Request(url, data=body, method=method)
        try:
            with urlrequest.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GraphApiError(_graph_error_message(detail, f"HTTP {exc.code}")) from exc
        except (URLError, TimeoutError) as exc:
            raise GraphApiError(f"Graph API request failed: {exc}") from exc
        if isinstance(payload, dict) and payload.get("error"):
            raise GraphApiError(_graph_error_message(json.dumps(payload), "error"))
        return payload if isinstance(payload, dict) else {}


def _graph_error_message(detail: str, fallback: str) -> str:
    try:
        parsed = json.loads(detail)
        message = parsed.get("error", {}).get("message")
        if message:
            return f"Graph API error: {message}"
    except (ValueError, AttributeError):
        pass
    return f"Graph API error ({fallback}): {detail[:500]}"
