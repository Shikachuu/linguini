# Linguini

Self-hosted, food-focused household AI chat. A household shares a pantry inventory and chat threads. The agent suggests and invents recipes, drains the inventory when you cook, warns about old purchases, and talks to Kifli through its MCP server to import orders and manage the cart.

Backend: FastAPI, Pydantic AI, SQLite. Works with any OpenAI-compatible model server (OpenRouter, vLLM, Ollama, llama.cpp). Ships as one distroless container that also serves the web app.

Web SPA and mobile app: pending. The API is designed for a React SPA served from the same origin (cookie session) and a native app (bearer session).

## Run locally

```sh
mise install
mise trust
cp .env.example .env   # fill in LINGUINI_SECRET_KEY and the model settings
set -a; . ./.env; set +a
mise run dev
```

`mise run check` runs ruff, ty, and pytest. Google login works on `http://localhost:8000`; Apple does not allow localhost redirects, so test Apple behind an HTTPS tunnel with a real domain.

## Run with Docker

```sh
cp .env.example .env
docker compose up -d
```

The SQLite file lives in the `data` volume at `/data/linguini.db`. The container runs as uid 65532; bind mounts must be owned by that uid.

The compose file publishes port 8000 on loopback only and trusts `X-Forwarded-*` headers from any peer, which is safe together with the `caddy` profile (`docker compose --profile caddy up -d` with `LINGUINI_DOMAIN` set). To expose the app on the LAN without Caddy, change the port mapping to `8000:8000` and remove `FORWARDED_ALLOW_IPS`.

Backups: set `LITESTREAM_REPLICA_URL` in `.env` (S3-compatible, SFTP, or `file://`) and uncomment the `entrypoint` line in `docker-compose.yml`. Litestream then restores the database on first boot and replicates continuously. Replication is asynchronous, so a crash can lose the last second of writes.

Images are published for `linux/amd64` and `linux/arm64`; a 64-bit Raspberry Pi works.

## Configuration

Every setting is an environment variable with the `LINGUINI_` prefix. Docker secrets in `/run/secrets/<name>` are read as well.

| Variable | Required | Purpose |
|---|---|---|
| `PUBLIC_URL` | yes in production | External origin, e.g. `https://linguini.example.com`. Used for OAuth redirect URIs, cookies, and CSRF checks. |
| `SECRET_KEY` | yes | Long random string. Encrypts stored shop and Apple tokens. Changing it invalidates them. |
| `MODEL` | yes | Model name sent to the model server. |
| `OPENAI_BASE_URL` | yes | OpenAI-compatible endpoint, e.g. `https://openrouter.ai/api/v1` or `http://ollama:11434/v1`. |
| `OPENAI_API_KEY` | depends | API key for that server; local servers often ignore it. |
| `SUMMARY_MODEL` | no | Cheaper model used to summarize long threads. Defaults to `MODEL`. |
| `MODEL_PROFILE` | no | JSON object of overrides for picky servers, e.g. `{"strict_tools": false}`. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | for Google login | Web client from Google Cloud Console; redirect URI `PUBLIC_URL/api/auth/google/callback`. |
| `GOOGLE_EXTRA_AUDIENCES` | no | JSON list of iOS and Android client ids accepted on the native login endpoint. |
| `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`, `APPLE_SERVICES_ID` | for Apple login | Services ID with return URL `PUBLIC_URL/api/auth/apple/callback`; the key is the `.p8` contents or `file:/run/secrets/apple_key`. |
| `APPLE_BUNDLE_IDS` | no | JSON list of iOS bundle ids accepted on the native login endpoint. |
| `KIFLI_MCP_URL` | no | Defaults to `https://mcp.kifli.hu/mcp`. Sister shops work by URL, e.g. `https://mcp.rohlik.cz/mcp`. |
| `LOCALE` | no | Default `hu-HU`; used for dates in the agent's instructions. |
| `HISTORY_TOKEN_BUDGET` | no | Default 24000; above this a thread's older turns are summarized. |
| `SESSION_TTL_DAYS`, `SESSION_IDLE_DAYS` | no | Default 90 and 14. |
| `DATA_DIR`, `STATIC_DIR` | no | Set by the image; override only for local runs. |

Login providers are optional. `GET /api/config` tells the web app which ones are enabled. Apple requires a paid Apple Developer membership per self-hoster; there is no shared client.

## Accounts and households

The first person to sign in creates the first account. Everyone else needs an invite link, minted by any member of a household. Households are flat: any member can invite, remove members, rename, or delete the household. A user can belong to several households.

Accounts are never linked by email. A signed-in user can link a second provider from the account page.

## Connecting Kifli

Kifli's identity server only allows `localhost` redirect URIs for dynamically registered clients (see `docs/kifli-spike.md`), so the connection is a paste flow:

1. In a household, call `POST /api/households/{id}/kifli/connect` (the web app will have a button). You get a link.
2. Open the link and sign in to Kifli. The browser then tries to open `http://localhost:3334/oauth/callback?...`, which does not load.
3. Copy that whole address and paste it into the app (`POST .../kifli/callback`).

Tokens are stored encrypted per household and refreshed automatically. Any member can connect or disconnect. The agent can search products, read orders, and edit the cart; checkout happens on kifli.hu.

Kifli's MCP terms allow personal use only. Do not run this as a service for strangers.

## API

OpenAPI docs are at `/docs`. All routes live under `/api`. Browser clients authenticate with the session cookie and must send `X-Requested-With: linguini` on mutating requests; native clients send `Authorization: Bearer <token>` obtained from `POST /api/auth/{provider}/native`.

Chat is `POST /api/households/{id}/threads/{thread}/chat` with a Vercel AI SDK `useChat` request body; the response is the Vercel AI SDK data stream. The server keeps the conversation history; only the newest user message in the request is used.
