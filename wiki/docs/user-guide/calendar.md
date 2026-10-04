# Calendar & ICS

## Subscribe to your calendar

Unnamed Tracking App provides a per-user iCalendar (`.ics`) feed. Calendar applications can subscribe to the URL without an application login because the URL contains a secret calendar token.

In the **Calendar** view, choose **Subscribe** to generate or display your feed URL. Copy that URL into your calendar application's subscription/calendar-by-URL feature.

### Regenerating the feed URL

The feed URL is a bearer secret. Anyone who has it can read the calendar for that user. If it has been exposed, use the Calendar view's **Regenerate** action. The previous URL immediately stops working and a new token is generated.

Do not paste a feed URL into public issue reports, screenshots, chat rooms, or source control. Prefer HTTPS when the application is accessed over an untrusted network.

## What the feed contains

- upcoming movie releases for movies in **Plan to Watch**;
- upcoming first-air dates for TV and anime in **Plan to Watch**;
- upcoming episode airings for TV and anime in the selected calendar airing statuses;
- optional upcoming game releases, controlled by **Game releases** and **Hide games** calendar preferences;
- user-created manual calendar events.

Provider-backed media entries use the same **90-day forward window** as the application calendar. The calendar query also keeps a one-day look-back for recently aired/released media. User-created manual events are exported independently of that media window, so a reminder can remain in a subscription even when it is outside the provider-backed 90-day range.

Projected future episodes are estimates based on the stored airing cadence. They are included when **Show estimated** is enabled; disabling that preference removes only projected episodes from the feed. The provider-confirmed next episode remains included. This matches the application calendar's distinction between confirmed and dashed estimated entries.

## Dates and time zones

Provider-supplied episode times are exported as UTC iCalendar timestamps (`Z`). Calendar applications convert those instants to the viewer's local time zone.

Release/premiere dates are date-only events. They do not have a real time-of-day. The application internally anchors these dates at noon UTC when constructing its calendar data, while the ICS feed emits them as `VALUE=DATE`, so subscribers receive an all-day event on the intended calendar date.

Manual all-day entries are exported as all-day `VALUE=DATE` events. Manual timed entries are stored as the user's local clock time and exported as a floating iCalendar time without a time-zone identifier.

## Importing another ICS feed

External `.ics` importing is **not implemented by this feature**. A separate design issue, **#243**, tracks the future importer architecture. The current calendar model is designed around application-owned events and per-user manual entries, while an external importer would require a separate source/synchronization model.

A safe server-side importer would need persistent source ownership, credentials, refresh scheduling, ETag/Last-Modified handling, UID/upsert rules, cancellation/deletion semantics, timezone conversion, malformed-feed behavior, request timeouts/size limits, and SSRF protection for user-supplied URLs. The application currently does not have a shared outbound-calendar-fetching security boundary for those requests, so remote ICS fetching is intentionally deferred rather than accepting arbitrary URLs.
