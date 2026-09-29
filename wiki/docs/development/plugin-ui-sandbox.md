# Custom frontend sandbox design

The declarative Plugin UI v1 host is the default. Complex interfaces that cannot be represented by native primitives have a future custom-frontend path, but custom code is deliberately outside the first implementation.

## Security model

Custom frontend code must not execute inside the core Vue application. It needs a separate browser execution context and a narrow, typed message channel to the authenticated Plugin Gateway.

The host must not expose core environment variables, application credentials, unrestricted DOM access, arbitrary network access, or a second permission system.

## Lifecycle

The runtime verifies package integrity and compatibility before the browser loads custom code. Renderer failures are isolated and can transition the plugin into the lifecycle/quarantine flow without affecting core startup.

The exact browser isolation primitive is intentionally undecided until runtime and browser compatibility work is available.

See [Plugin UI Protocol](plugin-ui.md) for the native renderer and [Plugin API v1](plugin-api-v1.md) for the gateway contract.
