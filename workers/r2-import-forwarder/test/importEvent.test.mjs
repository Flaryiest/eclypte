import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildImportEventRequest,
  handleQueueBatch,
  isSupportedImportKey,
} from "../src/importEvent.js";

const r2CreateEvent = {
  account: "3f4b7e3dcab231cbfdaa90a6a28bd548",
  action: "PutObject",
  bucket: "eclypte",
  object: {
    key: "incoming/collections/mario/songs/track.mp3",
    size: 65536,
    eTag: "c846ff7a18f28c2e262116d6e8719ef0",
  },
  eventTime: "2024-05-24T19:36:44.379Z",
};

test("recognizes supported incoming song and video keys", () => {
  assert.equal(
    isSupportedImportKey("incoming/collections/mario/songs/track.mp3"),
    true,
  );
  assert.equal(
    isSupportedImportKey("incoming/collections/mario/videos/source.mkv"),
    true,
  );
});

test("rejects unsupported incoming keys before forwarding", () => {
  assert.equal(
    isSupportedImportKey("incoming/collections/mario/songs/notes.txt"),
    false,
  );
  assert.equal(isSupportedImportKey("incoming/mario/songs/track.mp3"), false);
  assert.equal(
    isSupportedImportKey("incoming/collections/mario/images/shot.png"),
    false,
  );
});

test("builds the internal API import payload from an R2 create event", () => {
  assert.deepEqual(buildImportEventRequest(r2CreateEvent), {
    bucket: "eclypte",
    action: "PutObject",
    eventTime: "2024-05-24T19:36:44.379Z",
    object: {
      key: "incoming/collections/mario/songs/track.mp3",
      size: 65536,
      eTag: "c846ff7a18f28c2e262116d6e8719ef0",
    },
  });
});

test("parses string queue bodies and lowercase etag values defensively", () => {
  const body = JSON.stringify({
    ...r2CreateEvent,
    object: {
      ...r2CreateEvent.object,
      eTag: undefined,
      etag: "lowercase-etag",
    },
  });

  assert.deepEqual(buildImportEventRequest(body)?.object, {
    key: "incoming/collections/mario/songs/track.mp3",
    size: 65536,
    eTag: "lowercase-etag",
  });
});

test("ignores delete events and malformed event bodies", () => {
  assert.equal(buildImportEventRequest({ ...r2CreateEvent, action: "DeleteObject" }), null);
  assert.equal(buildImportEventRequest({ ...r2CreateEvent, object: {} }), null);
  assert.equal(buildImportEventRequest("not json"), null);
});

test("queue handler acknowledges forwarded and ignored messages independently", async () => {
  const forwarded = [];
  const messages = [
    fakeMessage(r2CreateEvent),
    fakeMessage({ ...r2CreateEvent, action: "DeleteObject" }),
  ];

  await handleQueueBatch(
    { messages },
    {
      ECLYPTE_API_BASE_URL: "https://api.example.test/",
      ECLYPTE_INTERNAL_TOKEN: "secret",
      ECLYPTE_USER_ID: "user_123",
    },
    async (url, init) => {
      forwarded.push({ url, init });
      return new Response(JSON.stringify({ accepted: true }), { status: 202 });
    },
    quietLogger(),
  );

  assert.equal(forwarded.length, 1);
  assert.equal(forwarded[0].url, "https://api.example.test/internal/import-events");
  assert.equal(forwarded[0].init.headers["X-Eclypte-Internal-Token"], "secret");
  assert.equal(forwarded[0].init.headers["X-User-Id"], "user_123");
  assert.deepEqual(JSON.parse(forwarded[0].init.body), buildImportEventRequest(r2CreateEvent));
  assert.equal(messages[0].acked, true);
  assert.equal(messages[1].acked, true);
  assert.equal(messages[0].retried, false);
});

test("queue handler retries failed API posts without acknowledging them", async () => {
  const message = fakeMessage(r2CreateEvent);

  await handleQueueBatch(
    { messages: [message] },
    {
      ECLYPTE_API_BASE_URL: "https://api.example.test",
      ECLYPTE_INTERNAL_TOKEN: "secret",
    },
    async () => new Response("queue full", { status: 429 }),
    quietLogger(),
  );

  assert.equal(message.acked, false);
  assert.deepEqual(message.retried, { delaySeconds: 60 });
});

function fakeMessage(body) {
  return {
    body,
    acked: false,
    retried: false,
    ack() {
      this.acked = true;
    },
    retry(options) {
      this.retried = options;
    },
  };
}

function quietLogger() {
  return {
    error() {},
  };
}
