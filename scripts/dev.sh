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
  notebook=0
  while [ "$#" -gt 0 ]; do
    case "${1:-}" in
      --notebook)
        notebook=1
        shift
        ;;
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

  if [ "$notebook" -eq 0 ]; then load_local_dotenv; fi

  workspace_overlay_args=""
  if [ "$isolate_generated" -eq 1 ]; then
    # Hardware tests must be able to start from a repository with no generated
    # state or build output. Anonymous Docker volumes hide any host copies and
    # are removed automatically with docker run --rm.
    workspace_overlay_args="--mount type=volume,target=/workspace/.pqc-generated-state,volume-nocopy --mount type=volume,target=/workspace/build,volume-nocopy"
  fi

  if [ -z "${PQC_PROGRESS_TTY+x}" ]; then
    if [ -t 1 ]; then PQC_PROGRESS_TTY=1; else PQC_PROGRESS_TTY=0; fi
  fi
  if [ -z "${PQC_PROGRESS_COLUMNS+x}" ]; then
    PQC_PROGRESS_COLUMNS=$(tput cols 2>/dev/null || printf '120')
  fi
  export PQC_PROGRESS_TTY PQC_PROGRESS_COLUMNS

  campaign_env_args=""
  if [ -n "${PQC_CAMPAIGN_HW:-}" ]; then
    campaign_env_args="$campaign_env_args -e PQC_CAMPAIGN_HW"
  fi
  if [ -n "${PQC_CAMPAIGN_HW_CONFIG:-}" ]; then
    campaign_env_args="$campaign_env_args -e PQC_CAMPAIGN_HW_CONFIG"
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

  # One runtime path for every workload. The installed, isolated bootstrap
  # creates container-only account/home state then drops to these host IDs.
  # Explicitly naming it makes an old image fail, rather than run as root.
  PQC_RUNTIME_UID=$(id -u)
  PQC_RUNTIME_GID=$(id -g)
  PQC_RUNTIME_GROUPS=$(id -G)
  PQC_RUNTIME_UMASK=$(umask)
  PQC_RUNTIME_ISOLATED=$isolate_generated
  export PQC_RUNTIME_UID PQC_RUNTIME_GID PQC_RUNTIME_GROUPS
  export PQC_RUNTIME_UMASK PQC_RUNTIME_ISOLATED

  if [ "$PQC_RUNTIME_UID" -eq 0 ] || [ "$PQC_RUNTIME_GID" -eq 0 ]; then
    echo "Run scripts/dev.sh from your normal non-root user shell, without sudo." >&2
    exit 2
  fi

  # Keep the image's maintained default for `dev.sh run` with no command.
  if [ "$#" -eq 0 ]; then set -- python -m pytest tests/unit; fi
  set -- "$image_name" -I /usr/local/libexec/pqc-container-runtime.py "$@"
  if [ "$notebook" -eq 1 ]; then
    set -- -p 127.0.0.1:8888:8888 "$@"
  fi
  if [ "$gateway" -eq 1 ]; then
    if [ ! -d "$ssh_source" ]; then
      echo "Gateway mode requires an SSH directory. Set PQC_DOCKER_SSH_DIR or create $ssh_source." >&2
      exit 2
    fi
    set -- -e PQC_CONTAINER_ENABLE_GATEWAY=1 -v "$ssh_source:/host-ssh:ro" "$@"
  fi
  set -- -e PQC_PROGRESS_TTY -e PQC_PROGRESS_COLUMNS -e PQC_PROGRESS_TIMEZONE -e PQC_CAMPAIGN_OPERATION_TIMEOUT_SECONDS -e NO_COLOR "$@"
  # Secret values are inherited by NAME, never interpolated into arguments.
  if [ -n "${PQC_WIFI_SSID:-}" ]; then set -- -e PQC_WIFI_SSID "$@"; fi
  if [ -n "${PQC_WIFI_PSK:-}" ]; then set -- -e PQC_WIFI_PSK "$@"; fi
  docker run --rm --user 0:0 --security-opt no-new-privileges \
    --entrypoint /usr/local/bin/python3 \
    -e PQC_RUNTIME_UID -e PQC_RUNTIME_GID -e PQC_RUNTIME_GROUPS \
    -e PQC_RUNTIME_UMASK -e PQC_RUNTIME_ISOLATED \
    -v "$repo_root:/workspace" $workspace_overlay_args -w /workspace \
    $campaign_env_args $ota_env_args "$@"

)

if [ "$#" -eq 0 ]; then
  echo "Usage: scripts/dev.sh <gateway-lock|build-image|check-host-user|pytest|pytest-gateway|pytest-hardware|experiment|experiment-gateway|campaign|campaign-gateway|notebook|python|python-gateway|cmake|shell|run> [args...]" >&2
  exit 2
fi

command=$1
shift

# Refuse root before the gateway lock launcher can perform any operation.
case "$command" in
  build-image|gateway-lock) ;;
  *)
    if [ "$(id -u)" -eq 0 ] || [ "$(id -g)" -eq 0 ]; then
      echo "Run scripts/dev.sh from your normal non-root user shell, without sudo." >&2
      exit 2
    fi
    ;;
esac

# Wrap gateway-capable commands before Docker starts. Keep the lease across
# child processes launched by an entire hardware test or campaign.
# The marker prevents recursion when the lock launcher re-enters dev.sh.
if [ "${PQC_GATEWAY_LOCK_HELD:-}" != 1 ]; then
  case "$command" in
    pytest-gateway|pytest-hardware|experiment-gateway|campaign-gateway|python-gateway)
      PQC_GATEWAY_LOCK_HELD=1
      export PQC_GATEWAY_LOCK_HELD
      exec python3 "$repo_root/scripts/gateway_lock.py" run -- "$repo_root/scripts/dev.sh" "$command" "$@"
      ;;
  esac
fi

case "$command" in
  gateway-lock)
    exec python3 "$repo_root/scripts/gateway_lock.py" "$@"
    ;;
  build-image)
    docker build -f docker/python/Dockerfile -t "$image_name" .
    ;;
  check-host-user)
    exec python3 "$repo_root/scripts/check_container_host_user.py" "$@"
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
  notebook)
    if [ "$#" -ne 0 ]; then
      echo "notebook accepts no server overrides; edit the notebook configuration instead." >&2
      exit 2
    fi
    run_container --notebook python -m jupyterlab --ip=0.0.0.0 --port=8888 --no-browser --ServerApp.port_retries=0
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
