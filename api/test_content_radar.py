from fastapi.testclient import TestClient

from api.app import create_app
from api.content_radar import candidate_from_tmdb_item
from api.storage.models import ContentCandidateRecord, ContentProvider
from api.storage.repository import StorageRepository
from api.storage.test_fakes import InMemoryObjectStore


class RecordingRadarRunner:
    def __init__(self):
        self.calls = []

    def run_content_radar_discovery(self, **kwargs):
        self.calls.append(("content_radar_discovery", kwargs))

    def run_music_analysis(self, **kwargs): ...
    def run_youtube_song_import(self, **kwargs): ...
    def run_video_analysis(self, **kwargs): ...
    def run_timeline_plan(self, **kwargs): ...
    def run_render(self, **kwargs): ...
    def run_edit_pipeline(self, **kwargs): ...
    def run_synthesis_reference_ingest(self, **kwargs): ...
    def run_synthesis_consolidation(self, **kwargs): ...
    def run_bucket_import(self, **kwargs): ...
    def run_auto_draft(self, **kwargs): ...


def test_tmdb_item_normalizes_available_candidate_with_provider_details():
    candidate = candidate_from_tmdb_item(
        user_id="user_123",
        item={
            "id": 123,
            "media_type": "movie",
            "title": "Neon Action",
            "overview": "A clean test fixture.",
            "release_date": "2026-05-01",
            "genre_ids": [28],
            "popularity": 120.0,
            "vote_average": 7.8,
            "vote_count": 420,
            "poster_path": "/poster.jpg",
            "backdrop_path": "/backdrop.jpg",
        },
        media_type="movie",
        source="tmdb_trending_day",
        region="US",
        provider_payload={
            "results": {
                "US": {
                    "link": "https://www.themoviedb.org/movie/123/watch",
                    "flatrate": [
                        {
                            "provider_id": 8,
                            "provider_name": "Netflix",
                            "logo_path": "/netflix.jpg",
                        }
                    ],
                    "rent": [
                        {
                            "provider_id": 2,
                            "provider_name": "Apple TV",
                            "logo_path": "/apple.jpg",
                        }
                    ],
                }
            }
        },
        genre_names={28: "Action"},
    )

    assert candidate is not None
    assert candidate.candidate_id == "tmdb_movie_123"
    assert candidate.status == "available"
    assert candidate.title == "Neon Action"
    assert candidate.genres == ["Action"]
    assert candidate.provider_region == "US"
    assert [provider.provider_type for provider in candidate.providers] == ["flatrate", "rent"]
    assert candidate.provider_link == "https://www.themoviedb.org/movie/123/watch"
    assert candidate.tmdb_url == "https://www.themoviedb.org/movie/123"
    assert candidate.score > 0


def test_tmdb_item_without_region_providers_is_not_available():
    candidate = candidate_from_tmdb_item(
        user_id="user_123",
        item={"id": 123, "title": "Unavailable", "release_date": "2026-05-01"},
        media_type="movie",
        source="tmdb_popular_movie",
        region="US",
        provider_payload={"results": {"CA": {"flatrate": [{"provider_id": 8, "provider_name": "Netflix"}]}}},
        genre_names={},
    )

    assert candidate is None


def test_content_candidate_upsert_preserves_review_state():
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    candidate = _candidate(score=10.0)

    repo.upsert_content_candidate(candidate)
    repo.update_content_candidate_status(
        user_id="user_123",
        candidate_id="tmdb_movie_123",
        status="approved",
    )
    repo.upsert_content_candidate(candidate.model_copy(update={"title": "Updated", "score": 25.0}))

    restored = repo.load_content_candidate(user_id="user_123", candidate_id="tmdb_movie_123")
    assert restored.status == "approved"
    assert restored.title == "Updated"
    assert restored.score == 25.0


def test_content_candidates_list_by_score_descending():
    repo = StorageRepository(InMemoryObjectStore())
    repo.upsert_content_candidate(_candidate(candidate_id="tmdb_movie_1", tmdb_id=1, title="Low", score=5))
    repo.upsert_content_candidate(_candidate(candidate_id="tmdb_tv_2", media_type="tv", tmdb_id=2, title="High", score=50))

    candidates = repo.list_content_candidates("user_123")

    assert [candidate.title for candidate in candidates] == ["High", "Low"]


def test_content_radar_discover_endpoint_creates_workflow_run():
    store = InMemoryObjectStore()
    runner = RecordingRadarRunner()
    client = TestClient(create_app(store=store, workflow_runner=runner))

    response = client.post(
        "/v1/content-radar/discover",
        headers={"X-User-Id": "user_123"},
        json={"region": "CA", "max_pages": 2},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["workflow_type"] == "content_radar_discovery"
    assert body["inputs"]["region"] == "CA"
    assert body["inputs"]["max_pages"] == "2"
    assert runner.calls == [
        (
            "content_radar_discovery",
            {"user_id": "user_123", "run_id": body["run_id"], "region": "CA", "max_pages": 2},
        )
    ]


def test_content_candidate_api_filters_and_status_actions():
    store = InMemoryObjectStore()
    repo = StorageRepository(store)
    repo.upsert_content_candidate(
        _candidate(
            candidate_id="tmdb_movie_123",
            media_type="movie",
            tmdb_id=123,
            title="Action Movie",
            genres=["Action"],
            providers=[ContentProvider(provider_id=8, name="Netflix", provider_type="flatrate")],
        )
    )
    repo.upsert_content_candidate(
        _candidate(
            candidate_id="tmdb_tv_456",
            media_type="tv",
            tmdb_id=456,
            title="Drama Show",
            genres=["Drama"],
            providers=[ContentProvider(provider_id=15, name="Hulu", provider_type="flatrate")],
        )
    )
    client = TestClient(create_app(store=store, workflow_runner=RecordingRadarRunner()))

    filtered = client.get(
        "/v1/content-candidates?media_type=movie&provider=netflix&genre=Action",
        headers={"X-User-Id": "user_123"},
    )
    approved = client.post(
        "/v1/content-candidates/tmdb_movie_123/approve",
        headers={"X-User-Id": "user_123"},
    )
    imported = client.post(
        "/v1/content-candidates/tmdb_movie_123/mark-imported",
        headers={"X-User-Id": "user_123"},
    )

    assert filtered.status_code == 200
    assert [item["candidate_id"] for item in filtered.json()] == ["tmdb_movie_123"]
    assert approved.json()["status"] == "approved"
    assert imported.json()["status"] == "imported"


def _candidate(
    *,
    candidate_id="tmdb_movie_123",
    media_type="movie",
    tmdb_id=123,
    title="Neon Action",
    genres=None,
    providers=None,
    score=10.0,
):
    return ContentCandidateRecord(
        candidate_id=candidate_id,
        owner_user_id="user_123",
        source="tmdb_trending_day",
        status="available",
        media_type=media_type,
        tmdb_id=tmdb_id,
        title=title,
        overview="",
        release_date="2026-05-01",
        poster_path="/poster.jpg",
        backdrop_path="/backdrop.jpg",
        genre_ids=[],
        genres=genres or [],
        popularity=42.0,
        vote_average=7.5,
        vote_count=100,
        provider_region="US",
        provider_link="https://www.themoviedb.org/watch",
        providers=providers
        or [ContentProvider(provider_id=8, name="Netflix", logo_path="/netflix.jpg", provider_type="flatrate")],
        score=score,
        tmdb_url=f"https://www.themoviedb.org/{media_type}/{tmdb_id}",
        created_at="2026-05-15T00:00:00Z",
        updated_at="2026-05-15T00:00:00Z",
    )
