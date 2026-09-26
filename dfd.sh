#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 --url=PUBLIC_UDIO_URL [--output-path=PATH] [--parallelism=N] [--format=FORMAT]

Build and run the Firefox experiment. Use a public Udio song, playlist,
or creator URL. Files and index.yml/index.md appear in PATH as they finish.

  --url=URL          Required public Udio URL
  --output-path=PATH Output folder (default: ./output)
  --parallelism=N    Concurrent Firefox workers (default: 4)
  --format=FORMAT    Audio format (default: mp3; m4a copies the original AAC)
  -h, --help         Show this help

On Windows, run this Bash script from WSL2 with Docker Desktop integration.
EOF
}

output_path=./output
target_url=
parallelism=4
output_format=mp3
while (($#)); do
  case "$1" in
    --output-path=*) output_path=${1#*=}; shift ;;
    --output-path)
      if (($# < 2)); then
        echo 'Missing value for --output-path' >&2
        exit 2
      fi
      output_path=$2
      shift 2
      ;;
    --url=*) target_url=${1#*=}; shift ;;
    --url)
      if (($# < 2)); then
        echo 'Missing value for --url' >&2
        exit 2
      fi
      target_url=$2
      shift 2
      ;;
    --parallelism=*) parallelism=${1#*=}; shift ;;
    --parallelism)
      if (($# < 2)); then
        echo 'Missing value for --parallelism' >&2
        exit 2
      fi
      parallelism=$2
      shift 2
      ;;
    --format=*) output_format=${1#*=}; shift ;;
    --format)
      if (($# < 2)); then
        echo 'Missing value for --format' >&2
        exit 2
      fi
      output_format=$2
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$target_url" ]]; then
  echo 'Missing required --url (public Udio song, playlist, or creator URL)' >&2
  usage >&2
  exit 2
fi
if [[ -z "$output_path" ]]; then
  echo 'The output path cannot be empty' >&2
  exit 2
fi
if [[ ! "$parallelism" =~ ^[1-9][0-9]*$ ]]; then
  echo '--parallelism must be a positive integer' >&2
  exit 2
fi
if [[ -z "$output_format" ]]; then
  echo '--format cannot be empty' >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo 'Docker with Compose is required and must be running.' >&2
  exit 1
fi
if ! docker_os=$(docker info --format '{{.OSType}}'); then
  echo 'The Docker daemon is unavailable. Start Docker before running this script.' >&2
  exit 1
fi
if [[ "$docker_os" != linux ]]; then
  echo 'Docker must be configured to run Linux containers.' >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo 'The Docker Compose plugin is required.' >&2
  exit 1
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
mkdir -p -- "$output_path"
MEDIA_OUTPUT_PATH=$(cd -- "$output_path" && pwd -P)
LOG_OUTPUT_PATH="$MEDIA_OUTPUT_PATH/.widevine-logs"
mkdir -p -- "$LOG_OUTPUT_PATH"
TARGET_URL=$target_url
PARALLELISM=$parallelism
OUTPUT_FORMAT=$output_format
export MEDIA_OUTPUT_PATH LOG_OUTPUT_PATH TARGET_URL PARALLELISM OUTPUT_FORMAT

echo "Media files and song index will appear in: $MEDIA_OUTPUT_PATH"
echo "Processor logs will appear in: $LOG_OUTPUT_PATH"
echo "Input URL: $TARGET_URL"
echo "Concurrent Firefox workers: $PARALLELISM"
echo "Output format: $OUTPUT_FORMAT"
echo 'Docker image platform: linux/amd64'
echo 'Docker build, browser, and processor output follows.'

run_log="$LOG_OUTPUT_PATH/last-run.log"
set +e
docker compose --progress=plain -f "$script_dir/compose.yaml" up --build --exit-code-from reproduction 2>&1 | tee "$run_log"
compose_status=${PIPESTATUS[0]}
set -e

summary=$(sed -n 's/.*\[catalog\] Run summary: //p' "$run_log" | tail -n 1)
if ((compose_status == 0)); then
  echo 'Run: success'
else
  echo "Run: failed (exit code $compose_status)"
fi
if [[ "$summary" =~ exported=([0-9]+)[[:space:]]already_present=([0-9]+)[[:space:]]failed=([0-9]+)[[:space:]]total=([0-9]+) ]]; then
  printf 'Results: %s exported, %s already present, %s failed (%s total)\n' \
    "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}" "${BASH_REMATCH[4]}"
elif ((compose_status != 0)); then
  echo 'Results: song counts unavailable.'
fi
echo "Media files available in: $MEDIA_OUTPUT_PATH"
exit "$compose_status"
