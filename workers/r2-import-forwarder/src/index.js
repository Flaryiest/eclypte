import { handleQueueBatch } from "./importEvent.js";

export default {
  async fetch() {
    return Response.json({
      ok: true,
      service: "eclypte-r2-import-forwarder",
    });
  },

  async queue(batch, env) {
    await handleQueueBatch(batch, env);
  },
};
