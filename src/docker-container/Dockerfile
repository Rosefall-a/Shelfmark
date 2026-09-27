# syntax=docker/dockerfile:1.7

FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY src/frontend/package*.json ./
RUN npm ci
COPY src/frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/opt/java/bin:${PATH}"
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx curl gcc postgresql-client unzip ca-certificates gettext-base openssl \
    && rm -rf /var/lib/apt/lists/*

COPY src/backend/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY src/backend/src /app/src
COPY src/backend/tests /app/tests
COPY src/backend/pyproject.toml /app/pyproject.toml
COPY src/backend/alembic.ini /app/alembic.ini

COPY --from=frontend-build /frontend/dist /srv/frontend
COPY src/docker-container/nginx/nginx.conf /etc/nginx/nginx.conf
COPY src/docker-container/nginx/startup.conf /etc/nginx/startup.conf
COPY src/docker-container/nginx/ready.conf /etc/nginx/ready.conf
COPY src/docker-container/startup /srv/startup
COPY src/docker-container/tests /opt/production-tests
COPY src/docker-container/entrypoint.sh ./entrypoint.sh
COPY src/docker-container/nginx/render-config.sh /usr/local/bin/render-production-nginx

RUN mkdir -p /run/unnamed-tracking /var/log/nginx \
    && chmod +x ./entrypoint.sh /usr/local/bin/render-production-nginx \
    && chmod 0755 /run/unnamed-tracking

EXPOSE 80 443
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD if [ "${NGINX_TLS_ENABLED:-false}" = "true" ]; then curl -kfsS https://127.0.0.1/_startup/status.json; else curl -fsS http://127.0.0.1/_startup/status.json; fi | grep -q '"overall":"ready"'

STOPSIGNAL SIGTERM
ENTRYPOINT ["./entrypoint.sh"]
