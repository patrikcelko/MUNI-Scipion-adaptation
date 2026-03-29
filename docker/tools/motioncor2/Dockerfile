# MotionCor2 Tool

FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive
LABEL maintainer="Patrik Čelko <patrik@celko.cz>"
LABEL description="MotionCor2 with Scipion integration for Kubernetes"

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

WORKDIR /opt

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget curl unzip \
    libtiff5 \
    python3 python3-pip python3-venv \
    python3-tk tk \
 && rm -rf /var/lib/apt/lists/*

# Copy MotionCor2 binary if available (must be downloaded separately due to license)
COPY . /tmp/mc2-context/

# Extract and install MotionCor2
RUN mc2="$(ls -1 /tmp/mc2-context/MotionCor2_* 2>/dev/null | head -n1)"; \
    if [ -n "$mc2" ]; then \
      mkdir -p /opt/mc2; \
      case "$mc2" in \
        *.zip) unzip -q "$mc2" -d /opt/mc2 ;; \
        *.tar.gz|*.tgz) tar xzf "$mc2" -C /opt/mc2 ;; \
        *) cp "$mc2" /opt/mc2/MotionCor2 && chmod +x /opt/mc2/MotionCor2 ;; \
      esac; \
      bin="$(find /opt/mc2 -maxdepth 3 -type f -perm -111 -name 'MotionCor2*' | head -n1)"; \
      if [ -n "$bin" ]; then \
        install -m 0755 "$bin" /usr/local/bin/MotionCor2; \
      fi; \
      rm -rf /opt/mc2; \
    else \
      echo "WARNING: MotionCor2 binary not found. Creating stub." >&2; \
      printf '#!/bin/bash\necho "MotionCor2 binary not installed. Download from https://msg.ucsf.edu/" >&2; exit 1\n' \
        > /usr/local/bin/MotionCor2; \
      chmod +x /usr/local/bin/MotionCor2; \
    fi && \
    rm -rf /tmp/mc2-context

# Install Scipion with MotionCor2 plugin
ENV SCIPION_HOME=/opt/scipion
RUN pip3 install --no-cache-dir scipion-installer && \
    mkdir -p ${SCIPION_HOME} && \
    python3 -m scipioninstaller ${SCIPION_HOME} -noAsk

# Install MotionCor2 plugin
RUN ${SCIPION_HOME}/scipion3 installp -p scipion-em-motioncorr --noBin

# Verify installation
RUN ${SCIPION_HOME}/scipion3 printenv | grep MOTIONCOR || true

# Create directories
RUN mkdir -p /projects /data /datasets && \
    chmod 777 /projects /data /datasets

WORKDIR /projects

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD MotionCor2 -h 2>&1 | head -1 || exit 1

SHELL ["/bin/bash", "-lc"]
ENTRYPOINT ["/bin/bash", "-lc"]
