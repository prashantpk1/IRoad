# Build recipe for the iroad-web image (Django app). Run the app with:
#   docker compose up -d --build
# Python runtime version is chosen here; Django and other Python packages
# are pinned in req.txt (single source of truth for app dependencies).
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY req.txt /app/req.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /app/req.txt

COPY . /app

EXPOSE 8000
