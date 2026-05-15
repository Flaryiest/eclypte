const CREATE_ACTIONS = new Set(["PutObject", "CopyObject", "CompleteMultipartUpload"]);
const AUDIO_SUFFIXES = new Set([".wav", ".mp3", ".m4a", ".flac", ".aac"]);
const VIDEO_SUFFIXES = new Set([".mp4", ".mov", ".mkv", ".webm"]);
const RETRY_DELAY_SECONDS = 60;

export function isSupportedImportKey(key) {
  if (typeof key !== "string") {
    return false;
  }

  const parts = key.split("/");
  if (
    parts.length < 5 ||
    parts[0] !== "incoming" ||
    parts[1] !== "collections" ||
    parts[2].trim() === ""
  ) {
    return false;
  }

  const role = parts[3];
  const filename = parts.slice(4).join("/").trim();
  if (filename === "") {
    return false;
  }

  const suffix = getSuffix(filename);
  if (role === "songs") {
    return AUDIO_SUFFIXES.has(suffix);
  }
  if (role === "videos") {
    return VIDEO_SUFFIXES.has(suffix);
  }
  return false;
}

export function buildImportEventRequest(body) {
  const event = parseBody(body);
  if (!event || typeof event !== "object") {
    return null;
  }

  const action = stringValue(event.action);
  if (!action || !CREATE_ACTIONS.has(action)) {
    return null;
  }

  const bucket = stringValue(event.bucket);
  const object = event.object;
  const key = object && typeof object === "object" ? stringValue(object.key) : null;
  if (!bucket || !key || !isSupportedImportKey(key)) {
    return null;
  }

  return {
    bucket,
    action,
    eventTime: stringValue(event.eventTime),
    object: {
      key,
      size: numberValue(object.size),
      eTag: stringValue(object.eTag ?? object.etag),
    },
  };
}

export async function handleQueueBatch(batch, env, fetchFn = fetch, logger = console) {
  for (const message of batch.messages) {
    const payload = buildImportEventRequest(message.body);
    if (!payload) {
      message.ack();
      continue;
    }

    try {
      const response = await forwardImportEvent(payload, env, fetchFn);
      if (response.ok) {
        message.ack();
      } else {
        const detail = await response.text();
        logger.error(`Eclypte import failed: ${response.status} ${detail}`);
        message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
      }
    } catch (error) {
      logger.error("Eclypte import request failed", error);
      message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
    }
  }
}

export async function forwardImportEvent(payload, env, fetchFn = fetch) {
  const baseUrl = requiredEnv(env, "ECLYPTE_API_BASE_URL").replace(/\/+$/, "");
  const token = requiredEnv(env, "ECLYPTE_INTERNAL_TOKEN");
  const headers = {
    "Content-Type": "application/json",
    "X-Eclypte-Internal-Token": token,
  };

  const userId = stringValue(env.ECLYPTE_USER_ID);
  if (userId) {
    headers["X-User-Id"] = userId;
  }

  return fetchFn(`${baseUrl}/internal/import-events`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
}

function parseBody(body) {
  if (typeof body === "string") {
    try {
      return JSON.parse(body);
    } catch {
      return null;
    }
  }
  return body;
}

function stringValue(value) {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function numberValue(value) {
  if (Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return null;
}

function getSuffix(filename) {
  const name = filename.split("/").at(-1).toLowerCase();
  const dotIndex = name.lastIndexOf(".");
  return dotIndex >= 0 ? name.slice(dotIndex) : "";
}

function requiredEnv(env, name) {
  const value = stringValue(env[name]);
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}
