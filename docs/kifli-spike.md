# Kifli MCP spike (2026-10-22)

Read-only discovery and one dynamic client registration against the live servers.

- `GET https://mcp.kifli.hu/.well-known/oauth-protected-resource/mcp` -> authorization server `https://identity.kifli.hu`, scopes `openid email roles`, bearer in header only.
- `GET https://identity.kifli.hu/.well-known/oauth-authorization-server` -> authorize `/oauth2/authorize`, token `/oauth2/token`, registration `/connect/register`, PKCE `S256`, grant types include `authorization_code` and `refresh_token`, auth method `none` allowed.
- `GET https://mcp.kifli.hu/mcp` without a token -> 401.
- `POST /connect/register` with `redirect_uris=["https://linguini.example.com/api/kifli/callback"]` -> **400 "Redirect URI is not allowed for dynamic client registration"**.
- `POST /connect/register` with `redirect_uris=["http://localhost:3334/oauth/callback"]` -> 201; the response scope is `openid profile offline_access roles email`, so refresh tokens are available.

Consequence: the backend cannot receive the browser redirect. The connect flow is paste-based: the user opens the authorize URL, signs in, lands on a `localhost:3334` URL that does not load, and pastes that URL into Linguini, which extracts `code` and `state`.

`tools/list` was not captured; it needs a signed-in session. Run the connect flow once and record the output here.
