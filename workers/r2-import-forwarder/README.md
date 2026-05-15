# Eclypte R2 Import Forwarder

Cloudflare Queue consumer for R2 object-create notifications. It forwards supported incoming media objects to the Eclypte API endpoint:

`POST /internal/import-events`

Supported keys:

- `incoming/collections/{collection_slug}/songs/*.{wav,mp3,m4a,flac,aac}`
- `incoming/collections/{collection_slug}/videos/*.{mp4,mov,mkv,webm}`

## Configure

Edit `wrangler.jsonc` and set:

`wrangler.jsonc` currently points at `https://api-production-8fb8.up.railway.app`.

Set the Worker secret to the same value as Railway's `ECLYPTE_INTERNAL_PROGRESS_TOKEN`:

```powershell
npx wrangler secret put ECLYPTE_INTERNAL_TOKEN
```

For local `wrangler dev`, copy `.dev.vars.example` to `.dev.vars` and fill in the same values. Do not commit `.dev.vars`.

Optional: if imports should be stored under one specific Eclypte user instead of the API's `ECLYPTE_DEFAULT_USER_ID`, set:

```powershell
npx wrangler secret put ECLYPTE_USER_ID
```

## Verify And Deploy

From this folder:

```powershell
npm test
npm run deploy
```

Then make sure the R2 notification rule points at the queue:

```powershell
npx wrangler r2 bucket notification create eclypte `
  --event-type object-create `
  --queue eclypte-import-events `
  --prefix "incoming/collections/"
```

Tail Worker logs while testing uploads:

```powershell
npm run tail
```

Upload objects into the incoming prefix, for example:

```text
incoming/collections/mario/songs/song.mp3
incoming/collections/mario/videos/source.mkv
```
