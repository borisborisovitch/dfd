#!/bin/sh
set -eu

cleanup() {
    kill "${xvfb_pid:-}" "${pulse_pid:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

XDG_RUNTIME_DIR=/tmp/runtime-researcher
export XDG_RUNTIME_DIR
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
pulseaudio --daemonize=no --exit-idle-time=-1 --log-target=stderr --log-level=error &
pulse_pid=$!
audio_ready=0
for _ in $(seq 1 50); do
    if pactl info >/dev/null 2>&1; then
        audio_ready=1
        break
    fi
    if ! kill -0 "$pulse_pid" 2>/dev/null; then
        break
    fi
    sleep 0.2
done
if [ "$audio_ready" -ne 1 ]; then
    echo "Virtual audio server did not start" >&2
    exit 1
fi
pactl load-module module-null-sink sink_name=virtual_audio >/dev/null
pactl set-default-sink virtual_audio
echo "Virtual audio output ready"

Xvfb :99 -screen 0 1440x900x24 -nolisten tcp &
xvfb_pid=$!

until [ -S /tmp/.X11-unix/X99 ]; do
    if ! kill -0 "$xvfb_pid" 2>/dev/null; then
        echo "Xvfb exited before the display was ready" >&2
        exit 1
    fi
    sleep 0.2
done

echo "Media output: ${CONTENT_DIR}"
echo "Hook logs: ${PWD}"

# Selenium launches Firefox through the researchers' RUN.sh, which applies
# LD_PRELOAD to the browser and its Widevine process.
RUN_AS_WEBDRIVER=1 HOOK_LIBRARY=/opt/processor/libhook.so \
    uv run --offline --locked --script /opt/docker/udio_bulk.py
