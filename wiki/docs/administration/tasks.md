# Scheduled tasks

The backend job loop wakes every minute. Administrators configure jobs through Settings and can enable/disable them, choose an interval within each job's bounds, and request a manual run.

Current deployment-wide jobs are:

- **Airing episode check** — enabled by default, normally every 30 minutes; checks TV/anime airing data and can be manually forced.
- **Media refresh** — disabled by default, normally daily; fills missing episode metadata and corrects stale media data.

Per-user scheduled AniList imports are also processed in bounded batches when enabled in user preferences. External notification deliveries use the same loop, but their retry schedule is owned by the notification delivery coordinator rather than the task settings page.

The task view shows running state, last run, and a bounded summary. A failed iteration is logged and retried by a later loop; it does not stop the API server.
