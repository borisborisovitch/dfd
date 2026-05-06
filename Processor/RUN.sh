#!/bin/bash

CONTENT_DIR=~/Downloads/WidevineMedia/
export CONTENT_DIR

MOZ_DISABLE_GMP_SANDBOX=1
export MOZ_DISABLE_GMP_SANDBOX

echo "[RUN.sh][INFO] Decrypted content will be stored in: ${CONTENT_DIR}"

echo "[RUN.sh][INFO] Starting Firefox..."
echo ""
LD_PRELOAD=build/libhook.so firefox-esr \
  --url about:debugging#/runtime/this-firefox \
  --url https://integration.widevine.com/player/
