# Non-hardware development image for Python framework validation, STM32 local builds,
# wolfBoot builds, and local application-signing workflows.
# This image intentionally omits hardware/gateway access packages and contains no secret material.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG DEBIAN_FRONTEND=noninteractive

WORKDIR /workspace

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        git \
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
