# Calendar / ICS architecture

The calendar is split between calendar data generation, application-owned manual events, and the public subscription serializer.

## Data flow

```text
Anime / TV / Movie / Game models
            |
            v
  build_calendar_entries()
            |
            +---- calendar preferences
            |
            v
   calendar_feed.py
            |
            v
       _build_ics()
            |
            v
/api/calendar/feed/{token}.ics
```

Manual entries are stored in the `calendar_events` table with a `user_id` foreign key. CRUD operations live in `api/routes/calendar_events.py`. The feed loads only events owned by the user represented by its calendar token.

The calendar token is stored on `users.calendar_token`. It is generated lazily with a cryptographically secure URL-safe random token. Regeneration replaces the stored value, which invalidates the old subscription URL without requiring a separate token-revocation table.

## ICS generation

`src/api/routes/calendar_feed.py` owns the iCalendar serialization. `_ics_escape()` escapes backslashes, commas, semicolons, and line breaks so user-controlled titles and notes cannot create additional iCalendar properties. The feed uses CRLF line endings and emits `VERSION:2.0` and `CALSCALE:GREGORIAN`.

Provider-backed episode UIDs are deterministic from media type, media ID, event kind, and episode number. Manual event UIDs are derived from the persistent `CalendarEvent.id`. These identifiers remain stable between feed fetches, allowing calendar clients to update existing events instead of treating each refresh as a new event.

Episode timestamps are UTC instants. Release dates and manual all-day dates are `VALUE=DATE`. Manual timed entries are floating local times because the current manual-event model stores only `HH:MM`, not an IANA timezone identifier.

The subscription window is 90 days. The feed reuses `build_calendar_entries()` rather than maintaining a second calendar query, so selected airing statuses, title language, release filtering, game filtering, and projected-episode preferences remain aligned with the application calendar.

## Why there is no ICS importer

Importing an external feed would not fit cleanly into the existing `CalendarEvent` table: imported events need persistent source identity and ownership plus enough source metadata to reconcile changes without overwriting manual events. A practical design would likely introduce a per-user calendar-source table and source-scoped event rows keyed by `(source_id, UID, recurrence/component identity)`.

Remote fetching also introduces SSRF risk. A future implementation would need URL parsing and redirect validation on every hop, blocking loopback/private/link-local/multicast ranges, cloud metadata addresses, internal Docker/service names, non-HTTP schemes, and unsafe DNS rebinding. It would also need bounded response size, connect/read timeouts, redirect limits, authentication policy, and a controlled HTTP client boundary. Those concerns are deliberately outside the outbound feed PR.
