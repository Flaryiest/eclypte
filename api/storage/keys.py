def file_manifest_key(*, user_id: str, file_id: str) -> str:
    return f"users/{user_id}/files/{file_id}/manifest.json"


def file_version_blob_key(*, user_id: str, file_id: str, version_id: str) -> str:
    return f"users/{user_id}/files/{file_id}/versions/{version_id}/blob"


def file_version_meta_key(*, user_id: str, file_id: str, version_id: str) -> str:
    return f"users/{user_id}/files/{file_id}/versions/{version_id}/meta.json"


def run_manifest_key(*, user_id: str, run_id: str) -> str:
    return f"users/{user_id}/runs/{run_id}/manifest.json"


def run_event_key(*, user_id: str, run_id: str, timestamp: str, event_id: str) -> str:
    return f"users/{user_id}/runs/{run_id}/events/{timestamp}_{event_id}.json"


def upload_reservation_key(*, upload_id: str) -> str:
    return f"uploads/{upload_id}.json"


def synthesis_reference_prefix(*, user_id: str) -> str:
    return f"users/{user_id}/synthesis/references/"


def synthesis_reference_key(*, user_id: str, reference_id: str) -> str:
    return f"{synthesis_reference_prefix(user_id=user_id)}{reference_id}.json"


def content_candidate_prefix(*, user_id: str) -> str:
    return f"users/{user_id}/content/candidates/"


def content_candidate_key(*, user_id: str, candidate_id: str) -> str:
    return f"{content_candidate_prefix(user_id=user_id)}{candidate_id}.json"


def synthesis_prompt_state_key(*, user_id: str) -> str:
    return f"users/{user_id}/synthesis/prompt/state.json"


def synthesis_prompt_version_prefix(*, user_id: str) -> str:
    return f"users/{user_id}/synthesis/prompt/versions/"


def synthesis_prompt_version_key(*, user_id: str, version_id: str) -> str:
    return f"{synthesis_prompt_version_prefix(user_id=user_id)}{version_id}.json"
