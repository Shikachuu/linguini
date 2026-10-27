# Linguini

Self-hosted, food-focused household AI chat. A household shares a pantry inventory and chat threads. The agent suggests and invents recipes, drains the inventory when you cook, warns about old purchases, and talks to Kifli through its MCP server to import orders and manage the cart.

Backend: FastAPI, Pydantic AI, SQLite. Works with any OpenAI-compatible model server (OpenRouter, vLLM, Ollama, llama.cpp). Ships as one distroless container that also serves the web app.

Web app: a React SPA in `web/`, built with Vite+ and served by the backend from the same origin (cookie session). Mobile app: pending; the API supports a native app with a bearer session.

## Run locally

```sh
mise install
mise trust
cp .env.example .env   # fill in LINGUINI_SECRET_KEY and the model settings
mise run dev
```

mise pins Node and pnpm next to uv; run `pnpm -C web install` once. `mise run dev` loads `.env`, builds the web app, rebuilds it on every change, and serves it together with the API on `http://localhost:8000`. Other tasks such as `check` and `e2e` do not read `.env`, so local settings cannot leak into the tests. There is no hot reload; refresh the page after a rebuild.

`mise run check` runs ruff, ty, pytest, `vp check` (Oxlint, Oxfmt, TypeScript), `vp test`, and fails when the generated API client is stale. `mise run fmt` fixes formatting and lint findings in both. After changing an API route or model, run `mise run gen` to regenerate `web/openapi.json` and the typed client in `web/src/api/gen/`.

`mise run e2e` builds the web app and runs the browser tests in `tests/e2e/` with Playwright and Chromium. Each test starts the API in-process on a random port with a scripted model and a fake Google and Apple sign-in page, so no model server or real accounts are needed. A failing test leaves a trace in `test-results/`; open it with `uv run playwright show-trace`. The plain `pytest` run skips these tests.

### Prompts and evals

The model-visible prompts live in `src/linguini/prompts/`. `chat.yaml` and `summary.yaml` are pydantic-ai agent specs loaded with `Agent.from_file`; they hold the static instructions, the agent name, retries, and model settings. `chat_context.hbs` and `summary_input.hbs` are Handlebars templates for the per-run context and the summarizer's input. `reply_language.md` is sent after the newest message on every model request but never stored; the system instructions sit above the whole history, so on their own they let a thread that started in Hungarian pull English replies back to Hungarian. Tool descriptions stay in the docstrings in `src/linguini/chat/tools.py`. `tests/test_prompts.py` pins the rendered context for every state the template can be in, so a template edit that changes what the model sees fails until the test is updated. The static instructions in the YAML are not duplicated in a test; the evals cover their effect.

`mise run eval` runs the cases in `evals/datasets/` against the model in `.env`. Each chat case seeds a fresh SQLite database, runs the real guarded agent and tools for each message, and checks the tool calls, the final inventory, and the reply. Each summary case runs the summarizer on a short conversation. Rule checks run in Python. Subjective checks use `DecisionJudge`, which asks a decision model how likely each listed statement is true of the case and passes when every statement scores at least 0.5; the report lists each statement with its score. The judge defaults to `typesafe/jev-1.14` on the System One API at `LINGUINI_DECISIONS_BASE_URL`, and `LINGUINI_EVAL_JUDGE_MODEL` or `--judge-model` changes it. Write judge statements short and checkable, one fact each, since a decision model scores them independently and writes no reasoning.

The datasets are `chat`, `summary`, `guardrails` and `topic_gate`. `guardrails` runs the chat agent on off-topic requests, kitchen questions that sound off-topic, direct attacks, instructions planted in item notes, names, recipes, history and the summary, pasted secrets, and personal data, in Hungarian and English. Its evaluators check whether the gate blocked a turn, whether the raw secret or phone number reached the model (`SentToModelNotMentions` reads every request the model received), and whether a reply leaked. `topic_gate` sends 58 labelled messages to the gate alone and passes a case when the block decision matches the label; its report keeps both scores, so the thresholds in `src/linguini/chat/guard.py` can be tuned from one run. `--guard-model` picks the gate model and defaults to `LINGUINI_GUARD_MODEL`.

Every case is a real, billed model call. Pass a dataset name, `--case NAME` to run single cases, or `--repeat N` to measure pass rates, since one run of a nondeterministic model proves little. `mise run eval -- --help` lists the options. Each run prints a table and writes the full report to `evals/reports/` (gitignored). The command exits non-zero when a case or an evaluator raised, for example when the judge model is unknown, but not when assertions fail; read the pass rate from the table. `mise run check` loads the datasets and runs the eval tasks against a scripted model, so it needs no model server.

### Guardrails

`src/linguini/chat/guard.py` adds these checks to the chat agent as pydantic-ai capabilities, so the chat endpoint and the evals run the same code:

- Before the model sees a message, `redact.py` replaces secrets, email addresses, card numbers, IBANs and phone numbers with `[SECRET]`, `[EMAIL]`, `[CARD]`, `[IBAN]` and `[PHONE]`. The database and the thread title get the redacted text too.
- The topic gate sends the redacted message, plus the previous question and reply, to a decision model (`LINGUINI_GUARD_MODEL`, default `typesafe/jev-1.14`). It blocks the turn when the off-topic or attack probability is 0.7 or higher, and answers with a fixed refusal in Hungarian or English. A blocked turn is stored with status `blocked`, shown in the thread, and left out of later model history. When the gate errors or takes longer than 3 seconds, the message goes through, because the checks below do not depend on it.
- Tool results, including Kifli's, go through the stackone prompt-injection classifier; a result with a planted instruction is replaced by a notice telling the model to warn the user. Personal data in tool results is redacted, and tool arguments that repeat the instructions are refused.
- Replies stream through a buffer that releases text sentence by sentence, at least 200 characters behind the model, after redaction. A reply that quotes the per-deployment marker or two lines of the instructions is cut at the sentence before, and its tool calls never run. The stored reply is exactly what the browser showed.
- The chat endpoint rejects messages over 4,000 characters and bodies over 64 KB with 413. Tool arguments are length-capped, and the web app renders no images in replies and asks before opening links outside kifli.hu.

The gate needs a System One API endpoint, which OpenRouter serves. On another provider, set `LINGUINI_GUARD_MODEL=` (empty) to turn the gate off; the other checks still run.

### Testing Sign in with Apple locally

Google login works on `http://localhost:8000`. Apple rejects `localhost` and IP addresses as return URLs, so local Apple testing goes through a Cloudflare named tunnel on a hostname you own. On the free plan, the domain's DNS must be on Cloudflare.

1. In the Apple Developer portal, create a dev-only primary App ID with Sign in with Apple and its own key. A separate App ID keeps dev consent and server notifications away from production, where a revoked consent deletes Apple-only accounts.
2. Under that App ID, create a Services ID with domain `linguini-dev.<domain>` and return URL `https://linguini-dev.<domain>/api/auth/apple/callback`.
3. Create the tunnel once (`cloudflared` is pinned in `mise.toml`):

   ```sh
   cloudflared tunnel login
   cloudflared tunnel create linguini-dev
   cloudflared tunnel route dns linguini-dev linguini-dev.<domain>
   ```

   No `config.yml` is needed: `mise run dev` starts the tunnel with `--url http://127.0.0.1:8000`, and `cloudflared` finds the credentials in `~/.cloudflared/`. Do not add `ingress` rules to `~/.cloudflared/config.yml`; `cloudflared` refuses to start when both are set.

4. Put the dev settings in `.env`, which only the `dev` task reads:

   ```sh
   LINGUINI_PUBLIC_URL=https://linguini-dev.<domain>
   LINGUINI_DEV_TUNNEL=linguini-dev
   LINGUINI_APPLE_TEAM_ID=...
   LINGUINI_APPLE_KEY_ID=...
   LINGUINI_APPLE_SERVICES_ID=...
   LINGUINI_APPLE_PRIVATE_KEY=file:/path/to/AuthKey.p8
   ```

   Do not use `mise.local.toml` for these: its `[env]` applies to every task, including the tests.

5. Add `https://linguini-dev.<domain>/api/auth/google/callback` to the Google client too, because `PUBLIC_URL` sets both redirect URIs.

With `LINGUINI_DEV_TUNNEL` set, `mise run dev` also runs the tunnel. Browse `https://linguini-dev.<domain>`, not localhost, or the login cookies land on the wrong origin. The dev server is public while the tunnel runs. Keep Cloudflare Bot Fight Mode off for the zone; it can block Apple's server-to-server notifications.

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
| `SESSION_HEADER` | no | Header that carries the thread id on every model call, for servers that route or cache by conversation. OpenCode Go requires `x-opencode-session`. |
| `GUARD_MODEL` | no | Decision model that screens each message for off-topic requests and attacks. Default `typesafe/jev-1.14`; empty turns the screen off. |
| `DECISIONS_BASE_URL` | no | System One API base URL serving `GUARD_MODEL`. Default `https://openrouter.ai/api/v1`. |
| `DECISIONS_API_KEY` | no | Key for `DECISIONS_BASE_URL`. Defaults to `OPENAI_API_KEY`. |
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

1. In the web app, open Settings and press Connect under Kifli (`POST /api/households/{id}/kifli/connect`). The Kifli sign-in page opens in a new tab.
2. Open the link and sign in to Kifli. The browser then tries to open `http://localhost:3334/oauth/callback?...`, which does not load.
3. Copy that whole address and paste it into the field in Settings (`POST .../kifli/callback`).

Tokens are stored encrypted per household and refreshed automatically. Any member can connect or disconnect. The agent can search products, read orders, and edit the cart; checkout happens on kifli.hu.

Kifli's MCP terms allow personal use only. Do not run this as a service for strangers.

## API

OpenAPI docs are at `/docs`. All routes live under `/api`. Browser clients authenticate with the session cookie and must send `X-Requested-With: linguini` on mutating requests; native clients send `Authorization: Bearer <token>` obtained from `POST /api/auth/{provider}/native`.

Chat is `POST /api/households/{id}/threads/{thread}/chat` with a Vercel AI SDK `useChat` request body; the response is the Vercel AI SDK data stream. The server keeps the conversation history; only the newest user message in the request is used.
