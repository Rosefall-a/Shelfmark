# OpenID Connect / SSO

OIDC is configured from **Settings → OIDC / SSO** after the application is installed. This is the user-facing configuration reference; OIDC should not be configured through the first-run setup flow.

## Before configuring

Create an OIDC client in your identity provider using the authorization-code flow.

For a named provider, the callback is:

\`\`\`text
https://<application-host>/api/auth/oidc/callback/<provider-slug>
\`\`\`

Use the exact redirect URI displayed in Settings when registering the client.

## Provider settings

Each provider can configure:

- Provider name and slug
- Issuer / discovery URL
- Client ID and client secret
- Scopes, defaulting to \`openid profile email\`
- Groups claim, defaulting to \`groups\`
- Optional administrator group
- User matching by email or username
- Whether new users may be created
- Login button text, image and colour
- Whether the provider is enabled and shown on the login page
- Whether autostart URLs are enabled

Providers can be added, removed, reordered, and configured independently.

The **Default login method** setting controls whether the normal login page initially prioritises local credentials or SSO.

## Redirect URI

The settings UI generates the redirect URI from the address currently used to access the application and displays it as read-only.

For example:

\`\`\`text
https://archive.example.com/api/auth/oidc/callback/authentik
\`\`\`

Register exactly that URI with the identity provider.

## Account matching

After the authorization-code exchange, the application requires an OIDC \`sub\` and an email identity claim.

A verified email is **not required**. An \`email_verified: false\` claim is not rejected solely because it is false.

Existing users are matched according to **User matching**:

- **Email** matches the local account email.
- **Username** uses the OIDC \`preferred_username\` or \`name\` value.

The OIDC subject is linked to the matched account. A subject already linked to another account is rejected as an identity conflict.

When **Allow new users** is enabled, an unmatched identity creates a local account. When it is disabled, an unmatched identity cannot sign in until an account is available to match.

## Administrator groups

If **Admin group** is configured, the application checks the configured groups claim. Membership in that group controls the user's administrator flag when the OIDC account is created or updated.

## Environment-managed settings

Deployments can supply supported OIDC values through environment configuration. Environment-managed values can be locked in the settings UI and cannot be overridden there.

For ordinary application configuration, use **Settings → OIDC / SSO**.

## Troubleshooting

- **Callback rejected:** compare the identity provider callback with the exact URI shown in Settings.
- **Provider unavailable:** check the issuer/discovery URL and client credentials.
- **User cannot be created:** check **Allow new users**.
- **Wrong administrator status:** check the groups claim and **Admin group**.
- **Fields cannot be edited:** the relevant values may be deployment/environment managed.
