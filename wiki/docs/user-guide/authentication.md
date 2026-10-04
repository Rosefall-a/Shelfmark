# Authentication

Unnamed Tracking App has two user-facing authentication methods: local username/password authentication and OpenID Connect (OIDC) / SSO.

## Local sign-in

Local accounts use the application's username/password login. A successful login creates a server-side session and the browser receives the application's session cookie.

Passwords are not stored in plaintext. API requests made by the web application normally use the session cookie automatically.

## Password and secret fields

Password and editable secret fields are masked by default. The eye control in the field can reveal the value temporarily and can be used with keyboard focus.

- New-password fields start empty and are intended for values being entered now, such as local sign-in, account creation, and profile password changes.
- Replaceable secrets also start empty when a saved value already exists. For example, an OIDC client secret is never populated into the browser; leave the field blank to keep the saved secret, or enter a replacement.
- Generated API keys are shown only when they are created. The generated value is displayed in a dedicated one-time field with a Copy key button so it can be copied without selecting the secret manually. Existing keys are represented by their prefix rather than their full secret, and the generated value is not persisted in the browser after the one-time display is dismissed.
- The application does not add a client-side encryption layer to password or token requests. These credentials are sent in authenticated request bodies; deployments should use HTTPS/TLS to protect them in transit.

The application supplies its own visibility control and suppresses Edge's native password-reveal control so that password fields do not show two reveal buttons.

## API keys

Users can create API keys for integrations that need to authenticate without a browser session.

API keys use the `utk_` prefix and are sent as:

```http
Authorization: Bearer utk_<secret>
```

Keys are associated with the user who created them and can be revoked. The server stores a hash of the key rather than the full secret.

## OIDC / SSO

OIDC is configured by an administrator under **Settings → OIDC / SSO**. It is a server-side login flow; the identity-provider client secret is not sent to the browser.

After a successful OIDC login, the application creates the same type of local server-side session used by normal login.

See [OpenID Connect / SSO](oidc.md) for provider settings and account matching.

## Session security

Sessions are stored server-side and have an expiry. Authenticated requests can use a bearer API key or the normal session cookie.

For HTTPS deployments, configure \`AUTH_COOKIE_SECURE=true\` so the authentication cookie is restricted to secure connections.



## Local password requirements

New local passwords are checked in the browser as they are entered and again by the backend when submitted. The frontend displays each active requirement and identifies unmet requirements before the form can be submitted.

The default policy is:

- At least 9 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one symbol
- A number is not required by default

Deployments can customise these rules with the environment variables `PASSWORD_MIN_LENGTH`, `PASSWORD_REQUIRE_UPPERCASE`, `PASSWORD_REQUIRE_LOWERCASE`, `PASSWORD_REQUIRE_DIGIT`, and `PASSWORD_REQUIRE_SYMBOL`. The effective policy is shown in **Settings → Password Policy**. Administrators can change it there when the corresponding values are not supplied by the environment; environment-provided values remain authoritative.

Password confirmation is required when creating a user and when changing the current user's password. Confirmation is checked in the frontend and is not sent as a second password to the backend.

The backend remains the final security boundary: it enforces the same configured policy even if a client bypasses the frontend validation.