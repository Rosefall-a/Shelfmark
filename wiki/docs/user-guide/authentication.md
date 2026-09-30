# Authentication

Unnamed Tracking App has two user-facing authentication methods: local username/password authentication and OpenID Connect (OIDC) / SSO.

## Local sign-in

Local accounts use the application's username/password login. A successful login creates a server-side session and the browser receives the application's session cookie.

Passwords are not stored in plaintext. API requests made by the web application normally use the session cookie automatically.

## API keys

Users can create API keys for integrations that need to authenticate without a browser session.

API keys use the \`utk_\` prefix and are sent as:

\`\`\`http
Authorization: Bearer utk_<secret>
\`\`\`

Keys are associated with the user who created them and can be revoked. The server stores a hash of the key rather than the full secret.

## OIDC / SSO

OIDC is configured by an administrator under **Settings → OIDC / SSO**. It is a server-side login flow; the identity-provider client secret is not sent to the browser.

After a successful OIDC login, the application creates the same type of local server-side session used by normal login.

See [OpenID Connect / SSO](oidc.md) for provider settings and account matching.

## Session security

Sessions are stored server-side and have an expiry. Authenticated requests can use a bearer API key or the normal session cookie.

For HTTPS deployments, configure \`AUTH_COOKIE_SECURE=true\` so the authentication cookie is restricted to secure connections.

