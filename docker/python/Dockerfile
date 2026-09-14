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

WORKDIR /workspace

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        git \
        openssh-client \
        openssl \
        build-essential \
        cmake \
        ninja-build \
        gcc-arm-none-eabi \
        binutils-arm-none-eabi \
        libnewlib-arm-none-eabi \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-dev.txt /tmp/pqc-framework-requirements-dev.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/pqc-framework-requirements-dev.txt

CMD ["python", "-m", "pytest", "tests/unit"]
