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
