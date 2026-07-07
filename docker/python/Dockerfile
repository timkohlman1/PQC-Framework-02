# Python-only development image for non-hardware framework validation.
# This image intentionally omits non-Python framework tooling and hardware access packages.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

COPY requirements-dev.txt /tmp/pqc-framework-requirements-dev.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/pqc-framework-requirements-dev.txt

CMD ["python", "-m", "pytest", "tests/unit"]
