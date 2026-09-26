FROM debian:trixie-slim AS build

ARG DEBIAN_FRONTEND=noninteractive
ARG REENCODE=OFF

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        cmake g++ make zip \
        libavcodec-dev libavformat-dev libavutil-dev libswscale-dev \
    && rm -rf /var/lib/apt/lists/*

COPY Processor /src/Processor
COPY Web-Extension /src/Web-Extension

RUN cmake -S /src/Processor -B /src/Processor/build -DREENCODE="${REENCODE}" \
    && cmake --build /src/Processor/build --parallel "$(nproc)" \
    && cd /src/Web-Extension \
    && zip -q -r /tmp/widevine-downloader.xpi .

FROM debian:trixie-slim AS driver

ARG DEBIAN_FRONTEND=noninteractive
ARG GECKODRIVER_VERSION=0.37.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl --fail --location --silent --show-error \
        "https://github.com/mozilla/geckodriver/releases/download/v${GECKODRIVER_VERSION}/geckodriver-v${GECKODRIVER_VERSION}-linux64.tar.gz" \
        --output /tmp/geckodriver.tar.gz \
    && tar -xzf /tmp/geckodriver.tar.gz -C /usr/local/bin geckodriver

FROM debian:trixie-slim

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        firefox-esr xvfb ffmpeg \
        pulseaudio pulseaudio-utils \
        libavcodec61 libavformat61 libavutil59 libswscale8 \
        ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /bin/bash researcher \
    && mkdir -p /home/researcher/profile /home/researcher/logs \
        /home/researcher/Downloads/WidevineMedia /etc/firefox/policies \
    && chown -R researcher:researcher /home/researcher

COPY --from=build /src/Processor/build/libhook.so /opt/processor/libhook.so
COPY Processor/RUN.sh /opt/processor/RUN.sh
COPY --from=build /tmp/widevine-downloader.xpi /opt/widevine-downloader.xpi
COPY --from=driver /usr/local/bin/geckodriver /usr/local/bin/geckodriver
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /uvx /usr/local/bin/
COPY docker/ /opt/docker/

ENV UV_CACHE_DIR=/home/researcher/.cache/uv \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python

RUN chmod +x /opt/docker/entrypoint.sh \
    && ln -s /opt/docker/policies.json /etc/firefox/policies/policies.json \
    && mkdir -p "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR" \
    && uv python install 3.10 \
    && uv sync --script /opt/docker/udio_bulk.py --locked --python 3.10 \
    && chown -R researcher:researcher /home/researcher/.cache "$UV_PYTHON_INSTALL_DIR"

USER researcher
ENV HOME=/home/researcher \
    DISPLAY=:99 \
    CONTENT_DIR=/home/researcher/Downloads/WidevineMedia \
    AUDIO_MAX_SECONDS=0 \
    MOZ_DISABLE_GMP_SANDBOX=1
WORKDIR /home/researcher/logs
ENTRYPOINT ["/opt/docker/entrypoint.sh"]
