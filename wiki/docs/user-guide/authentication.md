# Authentication

Unnamed Tracking App supports local username/password authentication and OpenID Connect (OIDC) / SSO.

## Local sign-in

A successful local login creates a server-side session. The browser receives an opaque, HttpOnly session cookie; the session record is stored server-side and expires after 30 days.

Passwords are hashed and are never stored in plaintext.

### Password requirements

The default local-password policy is at least 9 characters, one uppercase, one lowercase and one symbol; a number is not required by default. Administrators can change the policy in **Settings → Password Policy** unless the relevant values are environment-managed.

Password and editable secret fields are masked by default and include an accessible eye control for temporary reveal. Saved secrets are not populated into browser fields.

## API keys

Users can create bearer API keys for integrations that do not use a browser session:

```http
Authorization: Bearer utk_<secret>
```

The full key is shown only when created. The server stores a hash, and keys can be revoked.

## OIDC / SSO

Administrators configure OIDC under **Settings → OIDC / SSO**. OIDC credentials remain server-side and successful OIDC sign-in creates the same server-side session type as local login.

The first-run setup flow can also configure OIDC when its section is explicitly selected, or when all required OIDC environment credentials are supplied.

See [OpenID Connect / SSO](oidc.md).

## Multiple application hosts

Session cookie names are derived from the browser-visible Host value, including the port. Separate instances such as `localhost:5173` and `localhost:8080` therefore do not overwrite each other's browser cookie. The server-side sessions remain separate, with HttpOnly, SameSite=Lax and configurable Secure behavior.

## Startup routing

The frontend distinguishes an unavailable backend from a confirmed unauthenticated response. Protected routes preserve a validated internal return path, including query strings and hashes, through login/setup. External and protocol-relative return URLs are rejected. OIDC callbacks preserve the intended route using tab-scoped session storage. Invalid or missing return paths fall back to home.

For HTTPS deployments, configure `AUTH_COOKIE_SECURE=true`.
