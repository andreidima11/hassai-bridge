ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20

FROM node:22-alpine AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN mkdir -p /src/app/static && npm run build

FROM $BUILD_FROM

# Bumped by scripts/sync_version.sh. Changing this ARG invalidates every
# layer below so Supervisor cannot reuse a cached COPY of an old app/.
ARG HASSAI_VERSION=0.2.34-beta

ENV LANG=C.UTF-8

RUN echo "hassai-bridge ${HASSAI_VERSION}" > /etc/hassai-bridge-build

# Supervisor builds with THIS folder as context. Do not git-clone the repo.
COPY app/ /opt/hassai-bridge/
COPY --from=web /src/app/static/index.html /opt/hassai-bridge/static/index.html
COPY --from=web /src/app/static/assets /opt/hassai-bridge/static/assets
COPY run.sh /
RUN chmod a+x /run.sh \
    && apk add --no-cache ca-certificates \
    && update-ca-certificates \
    && pip3 install --no-cache-dir --break-system-packages --upgrade pip \
    && pip3 install --no-cache-dir --break-system-packages \
        -r /opt/hassai-bridge/requirements.txt \
    && rm -rf /root/.cache \
    && test "$(tr -d '[:space:]' < /opt/hassai-bridge/VERSION)" = "${HASSAI_VERSION}" \
    && test -f /opt/hassai-bridge/static/index.html \
    && test -d /opt/hassai-bridge/static/assets/chat

WORKDIR /opt/hassai-bridge
CMD [ "/run.sh" ]
