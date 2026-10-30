# Base image for DockerSandbox: bash, git, sqlite and Python with pytest. Task images can build on it.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git sqlite3 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "pytest>=9,<10"
WORKDIR /workspace
