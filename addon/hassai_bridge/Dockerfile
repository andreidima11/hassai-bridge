ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM $BUILD_FROM

ENV LANG=C.UTF-8

RUN apk add --no-cache \
        git \
    && pip3 install --no-cache-dir --break-system-packages --upgrade pip

# Clone the app into the image (add-on build context is this folder only)
ARG HASSAI_REF=main
RUN git clone --depth 1 --branch "${HASSAI_REF}" \
        https://github.com/andreidima11/hassai-bridge.git /opt/hassai-bridge \
    && pip3 install --no-cache-dir --break-system-packages \
        -r /opt/hassai-bridge/requirements.txt \
    && rm -rf /opt/hassai-bridge/.git /opt/hassai-bridge/addon /opt/hassai-bridge/venv \
    && rm -rf /root/.cache

COPY run.sh /
RUN chmod a+x /run.sh

WORKDIR /opt/hassai-bridge
CMD [ "/run.sh" ]
