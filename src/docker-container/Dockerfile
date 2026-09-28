# syntax=docker/dockerfile:1.7
FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY src/frontend/package*.json ./
RUN npm ci
COPY src/frontend/ ./
RUN npm run build

FROM python:3.12-slim AS docs-build
WORKDIR /docs
RUN pip install --no-cache-dir mkdocs-material
COPY wiki /docs/wiki
RUN mkdocs build --config-file /docs/wiki/mkdocs.yml --site-dir /docs/site

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/opt/java/bin:${PATH}"
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends nginx curl gcc postgresql-client unzip ca-certificates && rm -rf /var/lib/apt/lists/*
COPY src/backend/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY src/backend/src /app/src
COPY src/backend/tests /app/tests
COPY src/backend/pyproject.toml /app/pyproject.toml
COPY src/backend/alembic.ini /app/alembic.ini
COPY --from=frontend-build /frontend/dist /srv/frontend
COPY --from=docs-build /docs/site /srv/frontend/docs
COPY src/docker-container/nginx/nginx.conf /etc/nginx/nginx.conf
COPY src/docker-container/nginx/startup.conf /etc/nginx/startup.conf
COPY src/docker-container/nginx/ready.conf /etc/nginx/ready.conf
COPY src/docker-container/startup /srv/startup
COPY src/docker-container/entrypoint.sh ./entrypoint.sh
RUN mkdir -p /run/unnamed-tracking /var/log/nginx && chmod +x ./entrypoint.sh
EXPOSE 80
ENTRYPOINT ["./entrypoint.sh"]
