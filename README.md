# Linguini

Self-hosted, food-focused household AI chat. A household shares a pantry inventory and chat threads. The agent suggests recipes, drains the inventory when you cook, warns about old purchases, and talks to Kifli through its MCP server to import orders and manage the cart.

Backend: FastAPI, Pydantic AI, SQLite. Any OpenAI-compatible model server (OpenRouter, vLLM, Ollama, llama.cpp). Ships as one distroless container that also serves the web app.

Web SPA and mobile app: pending.

## Run locally

```sh
mise install
mise trust
cp .env.example .env   # fill in LINGUINI_SECRET_KEY and the model settings
set -a; . ./.env; set +a
mise run dev
```

`mise run check` runs ruff, ty, and pytest.

## Run with Docker

```sh
cp .env.example .env
docker compose up -d
```

The SQLite file lives in the `data` volume at `/data/linguini.db`. The container runs as uid 65532; bind mounts must be owned by that uid.

The compose file publishes port 8000 on loopback only and trusts `X-Forwarded-*` headers from any peer, which is safe together with the `caddy` profile (`docker compose --profile caddy up -d` with `LINGUINI_DOMAIN` set). To expose the app on the LAN without Caddy, change the port mapping to `8000:8000` and remove `FORWARDED_ALLOW_IPS`.

Backups: set `LITESTREAM_REPLICA_URL` in `.env` and uncomment the `entrypoint` line in `docker-compose.yml`. Litestream then restores the database on first boot and replicates continuously.

Kifli's MCP terms allow personal use only. Do not run this as a service for strangers.
