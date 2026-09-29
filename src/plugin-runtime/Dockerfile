# syntax=docker/dockerfile:1.7

FROM python:3.12-alpine

RUN apk add --no-cache bubblewrap \
    && addgroup -S pluginruntime \
    && adduser -S -G pluginruntime pluginruntime

WORKDIR /opt/plugin-runtime
COPY src/plugin-runtime/runtime.py ./runtime.py
COPY src/plugin-runtime/storage.py ./storage.py

USER pluginruntime:pluginruntime

ENV PLUGIN_RUNTIME_HOST=0.0.0.0
ENV PLUGIN_RUNTIME_PORT=8000
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=2s --retries=3 \
  CMD wget -q -O - http://127.0.0.1:8000/health >/dev/null || exit 1

ENTRYPOINT ["python", "/opt/plugin-runtime/runtime.py"]
