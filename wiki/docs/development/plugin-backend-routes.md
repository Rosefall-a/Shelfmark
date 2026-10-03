# Plugin backend routes

Plugin API v1 supports host-mediated JSON backend handlers without giving plugin code the FastAPI application, its router, middleware, database session, or authentication internals.

## Route scopes

`plugin` is the normal scope. The host mounts the route below `/api/plugins/<plugin-id>/` and requires the `backend.routes.plugin` capability. A declaration with `path: reports/{report_id}` is therefore available at `/api/plugins/example.plugin/reports/<report-id>`.

`host` is an exceptional scope for trusted integrations that need a direct application URL. Its path must start with `/api/`, may not claim `/api/plugins/`, and requires the critical-risk `backend.routes.host` capability. Core application routes are registered before the plugin host-route dispatcher, so a plugin cannot shadow a host endpoint. Overlapping host-route ownership between plugins is rejected, including literal/parameter overlaps such as `/api/reports/current` and `/api/reports/{report_id}`.

```json
{
  "capabilities": [{"name": "backend.routes.plugin", "version": 1}],
  "permissions": [
    {
      "capability": {"name": "backend.routes.plugin", "version": 1},
      "rationale": "Serve the plugin's authenticated report API."
    }
  ],
  "backend_routes": [
    {
      "id": "report",
      "scope": "plugin",
      "path": "reports/{report_id}",
      "methods": ["GET"],
      "handler": "plugin_routes:get_report",
      "authorization": "authenticated"
    }
  ]
}
```

Routes may use `GET`, `POST`, `PUT`, `PATCH`, and `DELETE`. `authorization` is either `authenticated` or `admin`; the host enforces it before starting plugin code. Route IDs, paths, parameter names, methods, handlers, and ownership are static manifest data and cannot be changed by a running plugin.

## Handler contract

The declared Python handler receives one JSON object:

```json
{
  "method": "POST",
  "path": "/api/plugins/example.plugin/reports/42",
  "path_parameters": {"report_id": "42"},
  "query": {"view": ["summary"]},
  "headers": {"accept": "application/json", "content-type": "application/json"},
  "body": {"refresh": true},
  "user": {"id": "...", "username": "alice", "is_admin": false}
}
```

Cookies, bearer tokens, and unrelated request headers are never forwarded. The handler returns a JSON object containing `status_code` and `body`. Unknown response fields, non-object responses, invalid JSON, and responses outside the supported status range are rejected as upstream plugin errors.

The request body must be a JSON object and is limited to 48 KiB so the complete route envelope remains within the runtime's existing 64 KiB action transport limit. Execution uses the runtime's existing sandbox, 30-second wall timeout, CPU/memory/process/file limits, and 64 KiB response limit. Deployment-level request rate controls remain applicable; the plugin route layer does not introduce a competing rate-limit system.

## Authorization and domain access

Browser authentication is always performed by the host. Every dispatch then checks the current installation ID, enabled/compatible/healthy lifecycle state, route authorization policy, and the applicable active capability grant for the authenticated user. Knowing a URL, declaring a manifest capability, or rendering a frontend contribution does not authorize a request.

The runtime executes the handler with the current request user's ID. Calls that the handler makes through Plugin API v1 therefore retain the same user scope, and domain gateways continue to enforce ownership and administrator requirements. A route handler must use those public domain APIs for games, media, documents, sessions, notifications, settings, and plugin storage. It must not import host source, access the application database, or receive host ORM objects.

## Lifecycle and auditing

Disabled, failed, incompatible, uninstalled, or unhealthy plugins do not execute backend handlers. Uninstall removes route ownership with the package. Update atomically replaces declarations; retained permissions remain installation-scoped, removed route capabilities are revoked through the normal update permission flow, and newly requested capabilities require review.

Successful route calls and capability denials are logged with request ID, plugin ID, installation ID, route ID, scope, method, user ID, and status. Request bodies, authorization headers, cookies, settings, and secrets are not logged.
