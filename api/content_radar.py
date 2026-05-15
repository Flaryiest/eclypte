from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from api.storage.models import ContentCandidateRecord, ContentMediaType, ContentProvider

TMDB_API_BASE_URL = "https://api.themoviedb.org/3"
TMDB_WEB_BASE_URL = "https://www.themoviedb.org"
PROVIDER_TYPES = ("flatrate", "free", "ads", "rent", "buy")


@dataclass(frozen=True)
class TmdbSource:
    source: str
    path: str
    media_type: ContentMediaType | None = None


TMDB_SOURCES = (
    TmdbSource("tmdb_trending_day", "/trending/all/day"),
    TmdbSource("tmdb_trending_week", "/trending/all/week"),
    TmdbSource("tmdb_movie_now_playing", "/movie/now_playing", "movie"),
    TmdbSource("tmdb_movie_popular", "/movie/popular", "movie"),
    TmdbSource("tmdb_movie_top_rated", "/movie/top_rated", "movie"),
    TmdbSource("tmdb_tv_on_the_air", "/tv/on_the_air", "tv"),
    TmdbSource("tmdb_tv_popular", "/tv/popular", "tv"),
)


class TmdbApiClient:
    def __init__(self, *, base_url: str = TMDB_API_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.read_access_token = os.environ.get("TMDB_READ_ACCESS_TOKEN") or os.environ.get(
            "ECLYPTE_TMDB_READ_ACCESS_TOKEN"
        )
        self.api_key = os.environ.get("TMDB_API_KEY") or os.environ.get("ECLYPTE_TMDB_API_KEY")
        if not self.read_access_token and not self.api_key:
            raise RuntimeError("TMDb API credentials are not configured")

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(params or {})
        if self.api_key and not self.read_access_token:
            params["api_key"] = self.api_key
        query = f"?{urlencode(params)}" if params else ""
        request = Request(f"{self.base_url}{path}{query}")
        if self.read_access_token:
            request.add_header("Authorization", f"Bearer {self.read_access_token}")
        request.add_header("Accept", "application/json")
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def genre_names(self) -> dict[int, str]:
        names: dict[int, str] = {}
        for media_type in ("movie", "tv"):
            payload = self.get_json(f"/genre/{media_type}/list", {"language": "en-US"})
            for item in payload.get("genres", []):
                genre_id = _int_value(item.get("id"))
                name = str(item.get("name") or "")
                if genre_id is not None and name:
                    names[genre_id] = name
        return names

    def source_results(self, source: TmdbSource, *, region: str, page: int) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"language": "en-US", "page": page}
        if source.media_type == "movie":
            params["region"] = region
        payload = self.get_json(source.path, params)
        results = payload.get("results", [])
        return results if isinstance(results, list) else []

    def watch_providers(self, *, media_type: ContentMediaType, tmdb_id: int) -> dict[str, Any]:
        path_type = "movie" if media_type == "movie" else "tv"
        return self.get_json(f"/{path_type}/{tmdb_id}/watch/providers")


def fetch_tmdb_available_candidates(
    *,
    user_id: str,
    region: str = "US",
    max_pages: int = 1,
    client: TmdbApiClient | None = None,
) -> list[ContentCandidateRecord]:
    tmdb = client or TmdbApiClient()
    region = normalize_region(region)
    max_pages = max(1, min(int(max_pages), 3))
    genre_names = tmdb.genre_names()
    candidates: dict[str, ContentCandidateRecord] = {}
    for source in TMDB_SOURCES:
        for page in range(1, max_pages + 1):
            for item in tmdb.source_results(source, region=region, page=page):
                media_type = _media_type(item, source.media_type)
                if media_type is None:
                    continue
                tmdb_id = _int_value(item.get("id"))
                if tmdb_id is None:
                    continue
                provider_payload = tmdb.watch_providers(media_type=media_type, tmdb_id=tmdb_id)
                candidate = candidate_from_tmdb_item(
                    user_id=user_id,
                    item=item,
                    media_type=media_type,
                    source=source.source,
                    region=region,
                    provider_payload=provider_payload,
                    genre_names=genre_names,
                )
                if candidate is None:
                    continue
                existing = candidates.get(candidate.candidate_id)
                if existing is None or candidate.score > existing.score:
                    candidates[candidate.candidate_id] = candidate
    return sorted(candidates.values(), key=lambda item: (item.score, item.updated_at), reverse=True)


def candidate_from_tmdb_item(
    *,
    user_id: str,
    item: dict[str, Any],
    media_type: ContentMediaType,
    source: str,
    region: str,
    provider_payload: dict[str, Any],
    genre_names: dict[int, str],
) -> ContentCandidateRecord | None:
    tmdb_id = _int_value(item.get("id"))
    if tmdb_id is None:
        return None
    providers, provider_link = _region_providers(provider_payload, region)
    if not providers:
        return None
    title = _title(item, media_type)
    if not title:
        return None
    genre_ids = [
        genre_id
        for genre_id in (_int_value(value) for value in item.get("genre_ids", []))
        if genre_id is not None
    ]
    now = _utc_now()
    release_date = _release_date(item, media_type)
    return ContentCandidateRecord(
        candidate_id=f"tmdb_{media_type}_{tmdb_id}",
        owner_user_id=user_id,
        source=source,
        status="available",
        media_type=media_type,
        tmdb_id=tmdb_id,
        title=title,
        overview=str(item.get("overview") or ""),
        release_date=release_date,
        poster_path=_optional_str(item.get("poster_path")),
        backdrop_path=_optional_str(item.get("backdrop_path")),
        genre_ids=genre_ids,
        genres=[genre_names[genre_id] for genre_id in genre_ids if genre_id in genre_names],
        popularity=_float_value(item.get("popularity")),
        vote_average=_float_value(item.get("vote_average")),
        vote_count=_int_value(item.get("vote_count")) or 0,
        provider_region=normalize_region(region),
        provider_link=provider_link,
        providers=providers,
        score=_score_item(item=item, release_date=release_date, provider_count=len(providers)),
        tmdb_url=tmdb_web_url(media_type=media_type, tmdb_id=tmdb_id),
        created_at=now,
        updated_at=now,
    )


def normalize_region(region: str) -> str:
    region = (region or "US").strip().upper()
    return region if len(region) == 2 else "US"


def tmdb_web_url(*, media_type: ContentMediaType, tmdb_id: int) -> str:
    return f"{TMDB_WEB_BASE_URL}/{media_type}/{tmdb_id}"


def _region_providers(
    provider_payload: dict[str, Any],
    region: str,
) -> tuple[list[ContentProvider], str | None]:
    region_payload = provider_payload.get("results", {}).get(normalize_region(region), {})
    if not isinstance(region_payload, dict):
        return [], None
    providers: list[ContentProvider] = []
    seen: set[tuple[int, str]] = set()
    for provider_type in PROVIDER_TYPES:
        for raw in region_payload.get(provider_type, []) or []:
            provider_id = _int_value(raw.get("provider_id"))
            name = str(raw.get("provider_name") or "").strip()
            if provider_id is None or not name:
                continue
            key = (provider_id, provider_type)
            if key in seen:
                continue
            seen.add(key)
            providers.append(
                ContentProvider(
                    provider_id=provider_id,
                    name=name,
                    logo_path=_optional_str(raw.get("logo_path")),
                    provider_type=provider_type,
                )
            )
    return providers, _optional_str(region_payload.get("link"))


def _media_type(
    item: dict[str, Any],
    fallback: ContentMediaType | None,
) -> ContentMediaType | None:
    value = item.get("media_type") or fallback
    if value in {"movie", "tv"}:
        return value
    return None


def _title(item: dict[str, Any], media_type: ContentMediaType) -> str:
    if media_type == "movie":
        return str(item.get("title") or item.get("original_title") or "").strip()
    return str(item.get("name") or item.get("original_name") or "").strip()


def _release_date(item: dict[str, Any], media_type: ContentMediaType) -> str | None:
    key = "release_date" if media_type == "movie" else "first_air_date"
    return _optional_str(item.get(key))


def _score_item(*, item: dict[str, Any], release_date: str | None, provider_count: int) -> float:
    popularity = _float_value(item.get("popularity"))
    vote_average = _float_value(item.get("vote_average"))
    vote_count = _int_value(item.get("vote_count")) or 0
    recency = _recency_score(release_date)
    availability = min(provider_count * 2.5, 15.0)
    vote_weight = min(vote_count / 100.0, 25.0)
    return round(popularity + vote_average * 5.0 + vote_weight + recency + availability, 3)


def _recency_score(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        released = date.fromisoformat(value)
    except ValueError:
        return 0.0
    age_days = (datetime.now(timezone.utc).date() - released).days
    if age_days < 0:
        return 20.0
    if age_days <= 30:
        return 18.0
    if age_days <= 90:
        return 12.0
    if age_days <= 365:
        return 6.0
    return 0.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
