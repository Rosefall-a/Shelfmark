FROM docker:29-cli

RUN apk add --no-cache python3 py3-pip \
    && pip install --no-cache-dir --break-system-packages "mkdocs-material==9.7.7"

WORKDIR /opt/devcontainer
COPY control.py index.html style.css app.js ./
COPY tests ./tests

ENV DEVCONTAINER_WORKSPACE=/workspace \
    DEVCONTAINER_CONTROL_HOST=0.0.0.0 \
    DEVCONTAINER_CONTROL_PORT=9000 \
    DEVCONTAINER_DOCS_HOST=0.0.0.0 \
    DEVCONTAINER_DOCS_PORT=999

EXPOSE 9000 999
ENTRYPOINT ["python3", "/opt/devcontainer/control.py"]
