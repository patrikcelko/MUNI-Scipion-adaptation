# Scipion Controller image (FastAPI + Kubernetes client)

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl tini && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -ms /bin/bash app
WORKDIR /app

# Install dependencies
COPY container_controller/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir /app

# Tools config
COPY docker/config/tools.yaml /config/tools.yaml

COPY container_controller/controller/ /app/controller/

RUN chown -R app:app /app
USER app
EXPOSE 5000

ENTRYPOINT ["/usr/bin/tini","-g","--"]
CMD ["python","-m","controller"]
