#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
image_name=${PQC_DOCKER_IMAGE:-pqc-framework-stm32-build}
ssh_source=${PQC_DOCKER_SSH_DIR:-${HOME}/.ssh}

strip_optional_quotes() {
  value=$1
  case "$value" in
    \"*\") value=${value#\"}; value=${value%\"} ;;
    \'*\') value=${value#\'}; value=${value%\'} ;;
  esac
  printf '%s' "$value"
}

load_local_dotenv() {
  env_path="$repo_root/.env"
  [ -f "$env_path" ] || return 0

  # Only the two supported local Wi-Fi values are imported. Existing caller
  # environment variables take precedence. run_container executes in a
  # subshell, so values imported here cannot persist after the invocation.
  while IFS= read -r raw_line || [ -n "$raw_line" ]; do
    line=$(printf '%s' "$raw_line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    case "$line" in
      ''|'#'*) continue ;;
    esac

    case "$line" in
      *=*) ;;
      *)
        echo "Invalid .env entry. Expected NAME=value." >&2
        exit 2
        ;;
    esac

    name=$(printf '%s' "${line%%=*}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    value=$(printf '%s' "${line#*=}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    value=$(strip_optional_quotes "$value")

    case "$name" in
      PQC_WIFI_SSID)
        if [ -z "${PQC_WIFI_SSID+x}" ]; then
          PQC_WIFI_SSID=$value
          export PQC_WIFI_SSID
        fi
        ;;
      PQC_WIFI_PSK)
        if [ -z "${PQC_WIFI_PSK+x}" ]; then
          PQC_WIFI_PSK=$value
          export PQC_WIFI_PSK
        fi
        ;;
      *)
        # Ignore unsupported names rather than sourcing arbitrary shell content.
        ;;
    esac
  done < "$env_path"
}

run_container() (
  gateway=0
  isolate_generated=0
  while [ "$#" -gt 0 ]; do
    case "${1:-}" in
      --gateway)
        gateway=1
        shift
        ;;
      --isolated-generated)
        isolate_generated=1
        shift
        ;;
      *)
        break
        ;;
    esac
  done

  load_local_dotenv

  workspace_overlay_args=""
  if [ "$isolate_generated" -eq 1 ]; then
    # Hardware tests must be able to start from a repository with no generated
    # state or build output. Anonymous Docker volumes hide any host copies and
    # are removed automatically with docker run --rm.
    workspace_overlay_args="--mount type=volume,target=/workspace/.pqc-generated-state --mount type=volume,target=/workspace/build"
  fi

  wifi_args=""
  if [ -n "${PQC_WIFI_SSID:-}" ]; then
    wifi_args="$wifi_args PQC_WIFI_SSID"
  fi
  if [ -n "${PQC_WIFI_PSK:-}" ]; then
    wifi_args="$wifi_args PQC_WIFI_PSK"
  fi

  campaign_env_args=""
  if [ -n "${PQC_CAMPAIGN_HW:-}" ]; then
    campaign_env_args="$campaign_env_args -e PQC_CAMPAIGN_HW"
  fi
  if [ -n "${PQC_CAMPAIGN_HW_CONFIG:-}" ]; then
    campaign_env_args="$campaign_env_args -e PQC_CAMPAIGN_HW_CONFIG"
  fi

  timebase_env_args=""
  if [ -n "${PQC_TIMEBASE_UART_LOG:-}" ]; then
    timebase_env_args="$timebase_env_args -e PQC_TIMEBASE_UART_LOG"
  fi

  ota_env_args=""
  for ota_env_name in \
    PQC_OTA_HW \
    PQC_OTA_HW_CASE \
    PQC_OTA_HW_APP_PLAN \
    PQC_OTA_HW_ROLLBACK_PLAN \
    PQC_OTA_HW_MIGRATION_PLAN \
    PQC_OTA_HW_INTERRUPTED_PLAN \
    PQC_OTA_HW_CORRUPT_APP_PLAN \
    PQC_OTA_HW_INVALID_MANIFEST_PLAN
  do
    eval "ota_env_value=\${$ota_env_name:-}"
    if [ -n "$ota_env_value" ]; then
      ota_env_args="$ota_env_args -e $ota_env_name"
    fi
  done

  # Build the docker invocation explicitly so secret values are inherited from
  # this temporary process environment (-e NAME), not exposed on the command
  # line as -e NAME=value.
  if [ "$gateway" -eq 1 ]; then
    if [ ! -d "$ssh_source" ]; then
      echo "Gateway mode requires an SSH directory. Set PQC_DOCKER_SSH_DIR or create $ssh_source." >&2
      exit 2
    fi

    if [ -n "${PQC_WIFI_SSID:-}" ] && [ -n "${PQC_WIFI_PSK:-}" ]; then
      docker run --rm \
        -v "$repo_root:/workspace" \
        $workspace_overlay_args \
        -w /workspace \
        $campaign_env_args $timebase_env_args $ota_env_args \
        -e PQC_WIFI_SSID \
        -e PQC_WIFI_PSK \
        -e PQC_CONTAINER_ENABLE_GATEWAY=1 \
        -v "$ssh_source:/host-ssh:ro" \
        "$image_name" \
        sh -lc 'mkdir -p /root/.ssh && cp -r /host-ssh/. /root/.ssh/ && chmod 700 /root/.ssh && find /root/.ssh -type f -exec chmod 600 {} \; && find /root/.ssh -type d -exec chmod 700 {} \; && exec "$@"' sh "$@"
    elif [ -n "${PQC_WIFI_SSID:-}" ]; then
      docker run --rm \
        -v "$repo_root:/workspace" \
        $workspace_overlay_args \
        -w /workspace \
        $campaign_env_args $timebase_env_args $ota_env_args \
        -e PQC_WIFI_SSID \
        -e PQC_CONTAINER_ENABLE_GATEWAY=1 \
        -v "$ssh_source:/host-ssh:ro" \
        "$image_name" \
        sh -lc 'mkdir -p /root/.ssh && cp -r /host-ssh/. /root/.ssh/ && chmod 700 /root/.ssh && find /root/.ssh -type f -exec chmod 600 {} \; && find /root/.ssh -type d -exec chmod 700 {} \; && exec "$@"' sh "$@"
    elif [ -n "${PQC_WIFI_PSK:-}" ]; then
      docker run --rm \
        -v "$repo_root:/workspace" \
        $workspace_overlay_args \
        -w /workspace \
        $campaign_env_args $timebase_env_args $ota_env_args \
        -e PQC_WIFI_PSK \
        -e PQC_CONTAINER_ENABLE_GATEWAY=1 \
        -v "$ssh_source:/host-ssh:ro" \
        "$image_name" \
        sh -lc 'mkdir -p /root/.ssh && cp -r /host-ssh/. /root/.ssh/ && chmod 700 /root/.ssh && find /root/.ssh -type f -exec chmod 600 {} \; && find /root/.ssh -type d -exec chmod 700 {} \; && exec "$@"' sh "$@"
    else
      docker run --rm \
        -v "$repo_root:/workspace" \
        $workspace_overlay_args \
        -w /workspace \
        $campaign_env_args $timebase_env_args $ota_env_args \
        -e PQC_CONTAINER_ENABLE_GATEWAY=1 \
        -v "$ssh_source:/host-ssh:ro" \
        "$image_name" \
        sh -lc 'mkdir -p /root/.ssh && cp -r /host-ssh/. /root/.ssh/ && chmod 700 /root/.ssh && find /root/.ssh -type f -exec chmod 600 {} \; && find /root/.ssh -type d -exec chmod 700 {} \; && exec "$@"' sh "$@"
    fi
  else
    if [ -n "${PQC_WIFI_SSID:-}" ] && [ -n "${PQC_WIFI_PSK:-}" ]; then
      docker run --rm -v "$repo_root:/workspace" $workspace_overlay_args -w /workspace $campaign_env_args $timebase_env_args $ota_env_args -e PQC_WIFI_SSID -e PQC_WIFI_PSK "$image_name" "$@"
    elif [ -n "${PQC_WIFI_SSID:-}" ]; then
      docker run --rm -v "$repo_root:/workspace" $workspace_overlay_args -w /workspace $campaign_env_args $timebase_env_args $ota_env_args -e PQC_WIFI_SSID "$image_name" "$@"
    elif [ -n "${PQC_WIFI_PSK:-}" ]; then
      docker run --rm -v "$repo_root:/workspace" $workspace_overlay_args -w /workspace $campaign_env_args $timebase_env_args $ota_env_args -e PQC_WIFI_PSK "$image_name" "$@"
    else
      docker run --rm -v "$repo_root:/workspace" $workspace_overlay_args -w /workspace $campaign_env_args $timebase_env_args $ota_env_args "$image_name" "$@"
    fi
  fi
)

if [ "$#" -eq 0 ]; then
  echo "Usage: scripts/dev.sh <build-image|pytest|pytest-gateway|pytest-hardware|experiment|experiment-gateway|campaign|campaign-gateway|python|python-gateway|cmake|shell|run> [args...]" >&2
  exit 2
fi

command=$1
shift

case "$command" in
  build-image)
    docker build -f docker/python/Dockerfile -t "$image_name" .
    ;;
  pytest)
    run_container python -m pytest "$@"
    ;;
  pytest-gateway)
    run_container --gateway python -m pytest "$@"
    ;;
  pytest-hardware)
    if [ "$#" -eq 0 ]; then
      set -- tests/hardware -m hardware --pqc-require-hardware
    fi
    run_container --gateway --isolated-generated python -m pytest "$@"
    ;;
  experiment)
    run_container python scripts/experiment.py "$@"
    ;;
  experiment-gateway)
    run_container --gateway python scripts/experiment.py "$@"
    ;;
  campaign)
    run_container python scripts/run_campaign.py "$@"
    ;;
  campaign-gateway)
    run_container --gateway python scripts/run_campaign.py "$@"
    ;;
  python)
    run_container python "$@"
    ;;
  python-gateway)
    run_container --gateway python "$@"
    ;;
  cmake)
    run_container cmake "$@"
    ;;
  shell)
    run_container sh "$@"
    ;;
  run)
    run_container "$@"
    ;;
  *)
    echo "Unknown dev command '$command'." >&2
    exit 2
    ;;
esac
