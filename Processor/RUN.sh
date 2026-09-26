#!/bin/bash

CONTENT_DIR=${CONTENT_DIR:-"$HOME/Downloads/WidevineMedia/"}
export CONTENT_DIR

MOZ_DISABLE_GMP_SANDBOX=${MOZ_DISABLE_GMP_SANDBOX:-1}
export MOZ_DISABLE_GMP_SANDBOX

HOOK_LIBRARY=${HOOK_LIBRARY:-build/libhook.so}

if [ "${RUN_AS_WEBDRIVER:-0}" = 1 ]; then
  exec env LD_PRELOAD="$HOOK_LIBRARY" firefox-esr "$@"
fi

if [ "$#" -eq 0 ]; then
  set -- --url about:debugging#/runtime/this-firefox \
    --url https://integration.widevine.com/player/
fi

echo "[RUN.sh][INFO] Decrypted content will be stored in: ${CONTENT_DIR}"

echo "[RUN.sh][INFO] Starting Firefox..."
echo ""
LD_PRELOAD="$HOOK_LIBRARY" firefox-esr "$@"
