#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
image_name=${PQC_DOCKER_IMAGE:-pqc-framework-stm32-build}
ssh_source=${PQC_DOCKER_SSH_DIR:-${HOME}/.ssh}

run_container() {
  gateway=0
  if [ "${1:-}" = "--gateway" ]; then
    gateway=1
    shift
  fi

  if [ "$gateway" -eq 1 ]; then
    if [ ! -d "$ssh_source" ]; then
      echo "Gateway mode requires an SSH directory. Set PQC_DOCKER_SSH_DIR or create $ssh_source." >&2
      exit 2
    fi
    docker run --rm \
      -v "$repo_root:/workspace" \
      -w /workspace \
      -e PQC_CONTAINER_ENABLE_GATEWAY=1 \
      -v "$ssh_source:/host-ssh:ro" \
      "$image_name" \
      sh -lc 'mkdir -p /root/.ssh && cp -r /host-ssh/. /root/.ssh/ && chmod 700 /root/.ssh && find /root/.ssh -type f -exec chmod 600 {} \; && find /root/.ssh -type d -exec chmod 700 {} \; && exec "$@"' sh "$@"
  else
    docker run --rm \
      -v "$repo_root:/workspace" \
      -w /workspace \
      "$image_name" \
      "$@"
  fi
}

if [ "$#" -eq 0 ]; then
  echo "Usage: scripts/dev.sh <build-image|pytest|pytest-gateway|pytest-hardware|experiment|experiment-gateway|python|cmake|shell|run> [args...]" >&2
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
    run_container --gateway python -m pytest "$@"
    ;;
  experiment)
    run_container python scripts/experiment.py "$@"
    ;;
  experiment-gateway)
    run_container --gateway python scripts/experiment.py "$@"
    ;;
  python)
    run_container python "$@"
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
