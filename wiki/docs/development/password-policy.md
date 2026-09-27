# Password policy

The local password policy is deployment-wide and is defined in the central configuration registry.

## Configuration

| Variable | Default | Meaning |
|---|---:|---|
| PASSWORD_MIN_LENGTH | 9 | Minimum password length |
| PASSWORD_REQUIRE_UPPERCASE | true | Require an uppercase letter |
| PASSWORD_REQUIRE_LOWERCASE | true | Require a lowercase letter |
| PASSWORD_REQUIRE_DIGIT | false | Require a number |
| PASSWORD_REQUIRE_SYMBOL | true | Require a non-alphanumeric symbol |

These variables are declared as ConfigSpec entries and resolved by EnvConfigHandler.

## Validation architecture

src/core/auth.py owns the authoritative backend validator. The /api/auth/password-policy endpoint exposes only the non-sensitive effective rules needed by the frontend.

The frontend uses the same rule set for immediate feedback in new-password forms. This prevents avoidable requests and gives users actionable feedback, but the backend remains the security boundary and validates every password that creates or changes a local account.

Confirmation is a frontend-only UX check. The backend receives one password value and does not store or compare a second copy.

## UI

The effective policy is visible under **Settings → Password Policy**. Changing the policy is deployment configuration work: update the environment variables and restart the application.

When changing a password rule, keep the frontend passwordValidationErrors() and backend validate_password() messages/rules synchronized, and add backend tests for the configured defaults and validation behavior.
