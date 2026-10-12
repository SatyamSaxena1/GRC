# GRC's reviewer as a ReviewBench agent (review-bench/ReviewBench AGENT_CONTRACT.md).
# Build from the repository root:  docker build -f bench/reviewbench/Dockerfile -t grc-reviewer:dev .
#
# Model: any OpenAI-compatible server, given by RB_MODEL_BASE_URL (LM Studio on the host:
# http://host.docker.internal:1234/v1) and RB_CONFIG_MODEL (default qwen/qwen3.8-27b).
# No credentials are baked in; the image has no network tools of its own.
FROM python:3.11-slim

WORKDIR /grc
COPY pyproject.toml ./
COPY app ./app
COPY evaluation ./evaluation
COPY demo ./demo
RUN pip install --no-cache-dir -e .

ENTRYPOINT ["python", "-m", "app.review.bench"]
