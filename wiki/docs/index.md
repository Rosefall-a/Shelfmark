# Unnamed Tracking App documentation

Unnamed Tracking App is a self-hosted library for games, movies, TV shows, anime, collections, activity, calendars, and related media. This documentation follows the checked-in application and the Plugin Manager implementation on this branch.

## Start here

- New deployment: [Setup overview](setup/index.md) and [Installation](setup/installation.md)
- Using the library: [User guide](user-guide/index.md)
- Operating a server: [Administration](administration/index.md) and [Deployment](deployment/index.md)
- Building integrations or plugins: [Development](development/index.md)

## Security boundaries

The application is multi-user. Library records, uploaded files, notifications, sessions, plugin grants, and provider settings are evaluated against the authenticated user. Administrators can manage deployment-wide settings and plugins, but plugin manifests never grant access by themselves.

Back up both PostgreSQL data and persistent media/plugin volumes. Never publish database, backend, or plugin-runtime service ports directly to the internet; place the application behind an HTTPS reverse proxy and use unique deployment secrets.
This wiki is built with [MkDocs](https://www.mkdocs.org/) and the Material for MkDocs theme.
