ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM $BUILD_FROM

# Bumped by scripts/sync_version.sh. Changing this ARG invalidates every
# layer below so Supervisor cannot reuse a cached COPY of an old app/.
ARG HASSAI_VERSION=0.2.17-beta

ENV LANG=C.UTF-8

RUN echo "hassai-bridge ${HASSAI_VERSION}" > /etc/hassai-bridge-build

# Supervisor builds with THIS folder as context. Do not git-clone the repo.
COPY app/ /opt/hassai-bridge/
COPY run.sh /
RUN chmod a+x /run.sh \
    && apk add --no-cache ca-certificates \
    && update-ca-certificates \
    && pip3 install --no-cache-dir --break-system-packages --upgrade pip \
    && pip3 install --no-cache-dir --break-system-packages \
        -r /opt/hassai-bridge/requirements.txt \
    && rm -rf /root/.cache \
    && test "$(tr -d '[:space:]' < /opt/hassai-bridge/VERSION)" = "${HASSAI_VERSION}"

WORKDIR /opt/hassai-bridge
CMD [ "/run.sh" ]
