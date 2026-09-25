# Default development/runtime image for Python framework validation, STM32 builds,
# wolfBoot builds, application-signing workflows, pytest, and gateway-mediated
# hardware experiments and gateway-capable integration checks. It contains tools only.
# The image contains no secret material; SSH access and any other credentials are provided at container runtime.
FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PQC_CONTAINER=1

ARG DEBIAN_FRONTEND=noninteractive
# Freeze Debian package resolution to the repository state used for the validated
# Trixie toolchain capture. Exact package versions below are part of the build
# environment contract; update the snapshot and versions together.
ARG DEBIAN_SNAPSHOT=20260914T040000Z

WORKDIR /workspace

RUN printf '%s\n' \
        'Types: deb' \
        "URIs: http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}/" \
        'Suites: trixie trixie-updates' \
        'Components: main' \
        'Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp' \
        'Check-Valid-Until: no' \
        '' \
        'Types: deb' \
        "URIs: http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}/" \
        'Suites: trixie-security' \
        'Components: main' \
        'Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp' \
        'Check-Valid-Until: no' \
        > /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates=20250419 \
        git=1:2.47.3-0+deb13u1 \
        openssh-client=1:10.0p1-7+deb13u4 \
        openssl=3.5.7-1~deb13u2 \
        tshark=4.4.18-0+deb13u1 \
        build-essential=12.12 \
        cmake=3.31.6-2 \
        ninja-build=1.12.1-1 \
        gcc-arm-none-eabi=15:14.2.rel1-1 \
        binutils-arm-none-eabi=2.44-3+23+b1 \
        libnewlib-arm-none-eabi=4.5.0.20241231-1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-dev.txt /tmp/pqc-framework-requirements-dev.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/pqc-framework-requirements-dev.txt

CMD ["python", "-m", "pytest", "tests/unit"]
