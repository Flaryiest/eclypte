from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import re
from typing import Any, Literal
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from api.storage.models import PublishingPostRecord
from api.storage.r2_client import ObjectStore
from api.storage.refs import FileRef, FileVersionRef, RunRef
from api.storage.repository import StorageRepository

BufferShareMode = Literal["addToQueue", "customScheduled"]


@dataclass(frozen=True)
class CaptionDraft:
    caption: str
    hashtags: list[str]
    notes: str = ""
    caption_source: str = "fallback"
    caption_error: str | None = None


@dataclass(frozen=True)
class BufferPostResult:
    post_id: str
    status: str | None = None
    post_url: str | None = None
    sent_at: str | None = None


@dataclass(frozen=True)
class BufferChannelStatus:
    id: str
    name: str | None = None
    service: str | None = None
    display_name: str | None = None
    is_disconnected: bool | None = None
    is_locked: bool | None = None
    external_link: str | None = None
    last_error: str | None = None


class BufferClientError(RuntimeError):
    pass


class BufferClient:
    def __init__(self, *, api_key: str, api_url: str = "https://api.buffer.com"):
        self._api_key = api_key
        self._api_url = api_url

    @classmethod
    def from_env(cls) -> "BufferClient":
        api_key = os.environ.get("BUFFER_API_KEY")
        if not api_key:
            raise BufferClientError("BUFFER_API_KEY is not configured")
        return cls(api_key=api_key, api_url=os.environ.get("BUFFER_API_URL", "https://api.buffer.com"))

    def create_video_post(
        self,
        *,
        channel_id: str,
        text: str,
        media_url: str,
        mode: BufferShareMode,
        due_at: str | None = None,
    ) -> BufferPostResult:
        payload = build_buffer_create_post_payload(
            channel_id=channel_id,
            text=text,
            media_url=media_url,
            mode=mode,
            due_at=due_at,
        )
        response = self._graphql(payload)
        if response.get("errors"):
            raise BufferClientError(_first_error_message(response["errors"]))
        result = response.get("data", {}).get("createPost")
        if not isinstance(result, dict):
            raise BufferClientError("Buffer did not return a createPost result")
        if result.get("message"):
            raise BufferClientError(str(result["message"]))
        post = result.get("post")
        if not isinstance(post, dict) or not post.get("id"):
            raise BufferClientError("Buffer did not return a post id")
        return _buffer_post_result(post)

    def get_post(self, *, post_id: str) -> BufferPostResult:
        response = self._graphql(build_buffer_get_post_payload(post_id=post_id))
        if response.get("errors"):
            raise BufferClientError(_first_error_message(response["errors"]))
        post = response.get("data", {}).get("post")
        if not isinstance(post, dict) or not post.get("id"):
            raise BufferClientError("Buffer did not return a post")
        return _buffer_post_result(post)

    def get_channel(self, *, channel_id: str) -> BufferChannelStatus:
        response = self._graphql(build_buffer_channel_payload(channel_id=channel_id))
        if response.get("errors"):
            raise BufferClientError(_first_error_message(response["errors"]))
        channel = response.get("data", {}).get("channel")
        if not isinstance(channel, dict):
            raise BufferClientError("Buffer did not return a channel")
        return BufferChannelStatus(
            id=str(channel.get("id") or channel_id),
            name=optional_str(channel.get("name")),
            service=optional_str(channel.get("service")),
            display_name=optional_str(channel.get("displayName")),
            is_disconnected=optional_bool(channel.get("isDisconnected")),
            is_locked=optional_bool(channel.get("isLocked")),
            external_link=optional_str(channel.get("externalLink")),
        )

    def _graphql(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urlrequest.Request(
            self._api_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlrequest.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BufferClientError(f"Buffer HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise BufferClientError(f"Buffer request failed: {exc}") from exc


def build_buffer_create_post_payload(
    *,
    channel_id: str,
    text: str,
    media_url: str,
    mode: BufferShareMode,
    due_at: str | None = None,
) -> dict[str, Any]:
    input_payload: dict[str, Any] = {
        "text": text,
        "channelId": channel_id,
        "schedulingType": "automatic",
        "mode": mode,
        "assets": [{"video": {"url": media_url}}],
        # Buffer requires a channel-specific post type for Instagram; we publish
        # Reels. `shouldShareToFeed` is also non-null on InstagramPostMetadataInput.
        "metadata": {"instagram": {"type": "reel", "shouldShareToFeed": True}},
    }
    if due_at:
        input_payload["dueAt"] = due_at
    return {
        "query": """
            mutation CreatePost($input: CreatePostInput!) {
              createPost(input: $input) {
                ... on PostActionSuccess {
                  post {
                    id
                    status
                    externalLink
                    dueAt
                    text
                    channelId
                    assets {
                      source
                    }
                  }
                }
                ... on MutationError {
                  message
                }
              }
            }
        """,
        "variables": {"input": input_payload},
    }


def build_buffer_get_post_payload(*, post_id: str) -> dict[str, Any]:
    return {
        "query": """
            query Post($input: PostInput!) {
              post(input: $input) {
                id
                status
                externalLink
                sentAt
              }
            }
        """,
        "variables": {"input": {"id": post_id}},
    }


def _buffer_post_result(post: dict[str, Any]) -> BufferPostResult:
    return BufferPostResult(
        post_id=str(post["id"]),
        status=str(post["status"]) if post.get("status") is not None else None,
        post_url=str(post["externalLink"]) if post.get("externalLink") else None,
        sent_at=str(post["sentAt"]) if post.get("sentAt") else None,
    )


def build_buffer_channel_payload(*, channel_id: str) -> dict[str, Any]:
    return {
        "query": """
            query Channel($input: ChannelInput!) {
              channel(input: $input) {
                id
                name
                service
                displayName
                isDisconnected
                isLocked
                externalLink
              }
            }
        """,
        "variables": {"input": {"id": channel_id}},
    }


def generate_caption_draft(
    *,
    render_name: str,
    collection_slug: str = "",
    source_name: str = "",
    song_name: str = "",
    openai_client: Any | None = None,
    model: str | None = None,
) -> CaptionDraft:
    fallback = _fallback_caption_draft(
        render_name=render_name,
        collection_slug=collection_slug,
        source_name=source_name,
        song_name=song_name,
    )
    try:
        client = openai_client or _openai_client_from_env()
        if client is None:
            return fallback
        payload = _openai_caption_draft(
            client=client,
            render_name=render_name,
            collection_slug=collection_slug,
            source_name=source_name,
            song_name=song_name,
            model=model or os.environ.get("ECLYPTE_CAPTION_MODEL", "gpt-5.4-mini"),
        )
        if not payload.caption.strip():
            raise ValueError("caption model returned an empty caption")
        return payload
    except Exception as exc:
        return CaptionDraft(
            caption=fallback.caption,
            hashtags=fallback.hashtags,
            notes=fallback.notes,
            caption_source="fallback",
            caption_error=str(exc),
        )


def _fallback_caption_draft(
    *,
    render_name: str,
    collection_slug: str = "",
    source_name: str = "",
    song_name: str = "",
) -> CaptionDraft:
    label = source_name or _humanize(collection_slug)
    caption = f"{label} edit fr 🔥" if label else "this one goes crazy fr 🔥"
    hashtags = _dedupe_hashtags(
        [
            "#amv",
            "#edit",
            "#anime",
            "#animeedit",
            "#fyp",
            _hashtag(source_name) if source_name else "",
            _hashtag(song_name) if song_name else "",
            _hashtag(collection_slug) if collection_slug else "",
        ]
    )
    return CaptionDraft(
        caption=caption[:2200],
        hashtags=hashtags[:30],
        caption_source="fallback",
    )


def _openai_caption_draft(
    *,
    client: Any,
    render_name: str,
    collection_slug: str,
    source_name: str,
    song_name: str,
    model: str,
) -> CaptionDraft:
    collection_label = collection_slug or "uncategorized"
    response = client.responses.create(
        model=model,
        instructions=(
            "You write Instagram Reels captions for anime edits (AMVs) the way a real "
            "Gen-Z creator posts them — NOT like a brand, marketer, or AI. "
            "Return only valid JSON with keys caption, hashtags, and notes.\n"
            "VOICE: short and casual, internet-native. Usually one line (a few words is "
            "fine), mostly lowercase, at most 1-2 emojis. Slang is good. The caption does "
            "NOT need to describe the video — a relatable, funny, or trending/nonsense "
            "one-liner works great.\n"
            "HARD BANS (these scream AI, never do them): listing pacing/transitions/energy; "
            "the phrases 'hits different', 'quick thoughts', 'if you're into', 'worth the "
            "watch', 'drop a rating', 'the vibe', 'let that sink in'; em dashes; any "
            "corporate/marketing tone; claiming rights or official status.\n"
            "Vary it every time. Vibe examples (DO NOT copy, just match the energy): "
            "'ok this one ate'; 'no bc why did this go so hard'; 'pov: you cant stop "
            "rewatching'; 'they really said cinema'; 'this is my roman empire fr'; "
            "'lowkey cooked'; 'hi yes one ticket to this please'.\n"
            "Caption under 2200 characters (keep it short). "
            "hashtags = 8-12 lowercase hashtag strings: include one for the "
            "anime/source and one for the song/artist when they are known, plus a "
            "few broad discovery tags (#amv #anime #edit #fyp). No spaces or "
            "punctuation. notes = a brief internal note for the editor."
        ),
        input=(
            "Make a caption for this anime edit (AMV) reel.\n"
            f"Anime/source: {source_name or 'unknown'}\n"
            f"Song: {song_name or 'unknown'}\n"
            f"Loose collection label (optional): {collection_label}.\n"
            "Write ONE caption a real creator would actually post. You may "
            "reference the anime or song naturally if it fits, but never force it."
        ),
        text={
            "format": {
                "type": "json_schema",
                "name": "eclypte_caption",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "caption": {"type": "string", "minLength": 1},
                        "hashtags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 12,
                        },
                        "notes": {"type": "string"},
                    },
                    "required": ["caption", "hashtags", "notes"],
                    "additionalProperties": False,
                },
            }
        },
        store=False,
    )
    data = json.loads(str(getattr(response, "output_text", "") or ""))
    if not isinstance(data, dict):
        raise ValueError("caption model returned invalid JSON")
    caption = str(data.get("caption") or "").strip()
    raw_hashtags = data.get("hashtags") or []
    if not isinstance(raw_hashtags, list):
        raise ValueError("caption model returned invalid hashtags")
    return CaptionDraft(
        caption=caption[:2200],
        hashtags=_dedupe_hashtags([str(item) for item in raw_hashtags])[:30],
        notes=str(data.get("notes") or "").strip(),
        caption_source="openai",
    )


def _openai_client_from_env() -> Any | None:
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    from openai import OpenAI

    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def resolve_edit_source_names(
    repo: StorageRepository, *, user_id: str, render_manifest: Any
) -> tuple[str, str]:
    """(source_name, song_name) from the render's run lineage; ("", "") on any miss.

    The render output's source_run_id points at the render run, whose inputs carry
    the source-video and song *file IDs*; their file-manifest display names are the
    movie/anime and song names (assets are named after their media).
    """
    run_id = getattr(render_manifest, "source_run_id", None)
    if not run_id:
        return "", ""
    try:
        run = repo.load_run_manifest(RunRef(user_id=user_id, run_id=run_id))
    except Exception:
        return "", ""
    source_name = _display_name_for_file(repo, user_id, run.inputs.get("source_video_file_id"))
    song_name = _display_name_for_file(repo, user_id, run.inputs.get("audio_file_id"))
    return source_name, song_name


def _display_name_for_file(repo: StorageRepository, user_id: str, file_id: str | None) -> str:
    if not file_id:
        return ""
    try:
        manifest = repo.load_file_manifest(FileRef(user_id=user_id, file_id=file_id))
    except Exception:
        return ""
    return _strip_media_extension(manifest.display_name)


def _strip_media_extension(name: str) -> str:
    base = name.rsplit("/", 1)[-1].strip()
    if "." in base:
        stem, ext = base.rsplit(".", 1)
        if 1 <= len(ext) <= 5 and ext.isalnum():
            return stem.strip()
    return base


def create_publish_post_for_render(
    repo: StorageRepository,
    *,
    user_id: str,
    render_output: dict[str, str],
    collection_slug: str = "",
    auto_created: bool = False,
) -> PublishingPostRecord:
    existing = repo.find_publishing_post_for_render(
        user_id=user_id,
        render_file_id=render_output["file_id"],
        render_version_id=render_output["version_id"],
    )
    if existing is not None:
        return existing

    manifest = repo.load_file_manifest(
        FileRef(user_id=user_id, file_id=render_output["file_id"])
    )
    meta = repo.load_file_version_meta(
        FileVersionRef(
            user_id=user_id,
            file_id=render_output["file_id"],
            version_id=render_output["version_id"],
        )
    )
    resolved_collection = collection_slug or _collection_from_tags(manifest.tags)
    source_name, song_name = resolve_edit_source_names(
        repo, user_id=user_id, render_manifest=manifest
    )
    draft = generate_caption_draft(
        render_name=manifest.display_name or meta.original_filename,
        collection_slug=resolved_collection,
        source_name=source_name,
        song_name=song_name,
    )
    now = _utc_now()
    record = PublishingPostRecord(
        post_id=f"pub_{_safe_id(render_output['version_id'])}",
        owner_user_id=user_id,
        status="ready",
        render_file_id=render_output["file_id"],
        render_version_id=render_output["version_id"],
        render_display_name=manifest.display_name or meta.original_filename,
        collection_slug=resolved_collection,
        generated_caption=draft.caption,
        caption=draft.caption,
        hashtags=draft.hashtags,
        notes=draft.notes,
        caption_source=draft.caption_source,
        caption_error=draft.caption_error,
        auto_created=auto_created,
        source_run_id=manifest.source_run_id,
        source_name=source_name,
        song_name=song_name,
        created_at=now,
        updated_at=now,
    )
    return repo.save_publishing_post(record)


def prepare_public_media_copy(
    repo: StorageRepository,
    *,
    store: ObjectStore,
    post: PublishingPostRecord,
    public_base_url: str,
) -> PublishingPostRecord:
    source_ref = FileVersionRef(
        user_id=post.owner_user_id,
        file_id=post.render_file_id,
        version_id=post.render_version_id,
    )
    meta = repo.load_file_version_meta(source_ref)
    extension = _extension(meta.original_filename) or "mp4"
    key = (
        f"public/publishing/{post.owner_user_id}/"
        f"{post.post_id}/{post.render_version_id}.{extension}"
    )
    store.put_bytes(
        key,
        repo.read_version_bytes(source_ref),
        content_type=meta.content_type or "video/mp4",
        metadata={
            "eclypte-post-id": post.post_id,
            "eclypte-render-version-id": post.render_version_id,
        },
    )
    return repo.save_publishing_post(
        post.model_copy(
            update={
                "public_media_key": key,
                "public_media_url": f"{public_base_url.rstrip('/')}/{key}",
                "updated_at": _utc_now(),
                "last_error": None,
            }
        )
    )


def format_post_text(caption: str, hashtags: list[str]) -> str:
    clean_caption = caption.strip()
    clean_hashtags = " ".join(_dedupe_hashtags(hashtags))
    if clean_caption and clean_hashtags:
        return f"{clean_caption}\n\n{clean_hashtags}"
    return clean_caption or clean_hashtags


def queue_status_for_mode(mode: BufferShareMode) -> str:
    return "scheduled" if mode == "customScheduled" else "queued"


# Default lead before an immediate "post now" is due, in seconds. Buffer rejects a
# `dueAt` in the past ("dueAt must be in the future"), so we schedule slightly ahead to
# absorb client/server clock skew + request latency; Buffer's automatic publisher then
# sends it on its next cycle after that time (near-immediate, not literally instant).
DEFAULT_POST_NOW_LEAD_SEC = 60


def immediate_due_at(lead_seconds: int | None = None) -> str:
    """A near-future ISO-8601 UTC ``dueAt`` for posting as soon as Buffer allows.

    Used by "post now": send Buffer a ``customScheduled`` post due ``now + lead`` so it
    bypasses the posting-schedule queue and publishes right away rather than waiting for
    the next slot. The lead defaults to ``ECLYPTE_BUFFER_POST_NOW_LEAD_SEC``
    (``DEFAULT_POST_NOW_LEAD_SEC``).
    """
    if lead_seconds is None:
        raw = os.environ.get("ECLYPTE_BUFFER_POST_NOW_LEAD_SEC")
        try:
            lead_seconds = int(raw) if raw else DEFAULT_POST_NOW_LEAD_SEC
        except ValueError:
            lead_seconds = DEFAULT_POST_NOW_LEAD_SEC
    lead_seconds = max(0, lead_seconds)
    due = datetime.now(timezone.utc) + timedelta(seconds=lead_seconds)
    return due.strftime("%Y-%m-%dT%H:%M:%SZ")


# Buffer Post.status values that mean the post has gone live on the channel.
SENT_BUFFER_STATUSES = {"sent", "service", "published"}


def apply_buffer_status(
    post: PublishingPostRecord,
    result: BufferPostResult,
    *,
    now: str,
) -> PublishingPostRecord:
    """Merge a Buffer ``get_post`` result into a publishing record.

    A post becomes ``published`` as soon as Buffer reports it sent (``sentAt`` set, or
    a sent-like status) — not only once the Instagram permalink (``externalLink``)
    appears, which can lag well behind the post going live. The permalink is
    back-filled independently whenever it shows up, so a published-without-URL post
    keeps reconciling on later refreshes. A ``published`` or ``canceled`` record is
    never downgraded.
    """
    # A successful read clears any stale lookup error recorded by a prior failure.
    update: dict[str, Any] = {"updated_at": now, "last_error": None}
    if result.status:
        update["buffer_status"] = result.status
    if result.post_url:
        update["post_url"] = result.post_url
    is_sent = bool(result.sent_at) or (result.status or "").lower() in SENT_BUFFER_STATUSES
    if (is_sent or result.post_url) and post.status not in ("published", "canceled"):
        update["status"] = "published"
        update["posted_at"] = post.posted_at or result.sent_at or now
    return post.model_copy(update=update)


def _first_error_message(errors: Any) -> str:
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict) and first.get("message"):
            return str(first["message"])
    return "Buffer returned an error"


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _collection_from_tags(tags: list[str]) -> str:
    return next((tag.removeprefix("collection:") for tag in tags if tag.startswith("collection:")), "")


def _dedupe_hashtags(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        if not normalized.startswith("#"):
            normalized = f"#{normalized}"
        normalized = re.sub(r"[^#A-Za-z0-9_]", "", normalized)
        key = normalized.lower()
        if len(normalized) > 1 and key not in seen:
            seen.add(key)
            result.append(normalized.lower())
    return result


def _extension(filename: str) -> str:
    if "." not in filename:
        return ""
    extension = filename.rsplit(".", 1)[-1].lower()
    return re.sub(r"[^a-z0-9]", "", extension)


def _hashtag(value: str) -> str:
    return f"#{re.sub(r'[^A-Za-z0-9_]', '', value.replace('-', '_').replace(' ', '_'))}"


def _humanize(value: str) -> str:
    return value.replace("-", " ").replace("_", " ").strip() or value


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
