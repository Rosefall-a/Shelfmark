# Wiki page https://rosefall-a.github.io/unnamed_tracking_app/


# Running the API

docker compose down -v 
docker compose up --build
docker compose -f example-docker-compose.yaml up --build

Use -v on the down to remove database and reconfigure app, use the bottom compose for production container, and standard for dev containers.

docker compose run --rm backend


# checks
## Backend checks
cd src/backend
mypy --config-file pyproject.toml src
pylint --rcfile=pyproject.toml src

## Backend tests
The tests use the running database, so start the stack first.

```bash
docker compose exec -e PYTHONPATH=/app backend python -m pytest tests -q
```

## Frontend checks
cd /src/frontend
npm run lint
npm run format # if this fails run npm run format:fix
npm run typecheck
npx vitest run

# running the wiki
run `mkdocs serve -a 0.0.0.0:999` inside the wiki folder (requires sudo on linux)


# Recommended VS Code extensions
- Ruff by charliermarsh

# Database updates

```bash
docker compose exec backend alembic -c alembic.ini revision --autogenerate -m "your changes here eg add playtime to game table"
```

The backend brings the database up to date every time it starts, including
databases made by an older migration history. Write new migrations so they are
safe to run twice, and keep the history a single line. See
[docs/migrations.md](docs/migrations.md).

# Metadata keys

Movie and TV details come from TMDB and OMDb, games from IGDB. Enter the keys
as an administrator under Settings > Metadata Sources, or set them in `.env`
(`TMDB_API_KEY`, `OMDB_API_KEY`, `TVDB_API_KEY`, `IGDB_CLIENT_ID`,
`IGDB_CLIENT_SECRET`). A key saved in Settings wins over `.env`, and nothing
ships with the app.

# Importing and exporting

Settings > Export / Import can bring in a MyAnimeList export (anime), a
Letterboxd export (movies) and an IMDb ratings or watchlist CSV (movies and TV
shows). Each import shows what it would add or change first, and for a title
you already have you choose between keeping it as it is and using the file's
data. It can also restore movies, TV shows and anime from the app's own export,
and export everything as a CSV.

# Scheduled jobs

Recurring work is listed under Settings > Tasks. Each job can be switched on or
off, given its own interval (any whole number of minutes within the range shown
there) and run by hand. There are two:

- **Airing episode check** starts on, every 30 minutes. It adds a numbered row
  for each newly aired episode of a show you follow. It only asks a provider
  about a show once its next episode is due (plus a daily look for a moved
  schedule), and asks AniList about up to 50 shows in one request, so most runs
  do almost nothing.
- **Media refresh** starts off. It fills in missing episode titles and images
  and corrects a show whose episode count is wrong.

Jobs are registered in `src/backend/src/features/jobs.py`.
     
## Security

This project is not currently hardened for direct public-internet exposure. Keep the API behind an appropriate network boundary and do not expose it directly to the public internet.
