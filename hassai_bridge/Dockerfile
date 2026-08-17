ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM $BUILD_FROM

ENV LANG=C.UTF-8

# Supervisor builds with THIS folder as context. Do not git-clone the repo:
# that layer was cached and shipped stale app code (UI showed v0.2.0-beta
# while the store listed 0.2.3-beta). Sources are vendored in ./app.
COPY app/ /opt/hassai-bridge/
COPY run.sh /

RUN chmod a+x /run.sh \
    && pip3 install --no-cache-dir --break-system-packages --upgrade pip \
    && pip3 install --no-cache-dir --break-system-packages \
        -r /opt/hassai-bridge/requirements.txt \
    && rm -rf /root/.cache \
    && test -f /opt/hassai-bridge/VERSION

WORKDIR /opt/hassai-bridge
CMD [ "/run.sh" ]
