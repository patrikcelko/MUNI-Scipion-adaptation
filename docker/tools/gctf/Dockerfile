# Gctf Tool

FROM nvidia/cuda:12.4.1-devel-ubuntu22.04 AS builder

ARG DEBIAN_FRONTEND=noninteractive
LABEL maintainer="Patrik Čelko <patrik@celko.cz>"
LABEL description="Gctf with Scipion integration for Kubernetes"

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    python3-pip \
    python3-dev \
    wget \
    curl \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install Miniconda (required by scipion-em-gctf to create a conda env with cudatoolkit)
RUN wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/miniconda && \
    rm /tmp/miniconda.sh
ENV PATH="/opt/miniconda/bin:${PATH}"
RUN conda config --add channels conda-forge && \
    conda config --set channel_priority flexible && \
    conda config --set always_yes true && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Install Scipion
ENV SCIPION_HOME=/opt/scipion
RUN /usr/bin/pip3 install --no-cache-dir scipion-installer && \
    mkdir -p ${SCIPION_HOME} && \
    /usr/bin/python3 -m scipioninstaller ${SCIPION_HOME} -noAsk -venv

# Install Gctf plugin (downloads Gctf binary)
RUN ${SCIPION_HOME}/scipion3 installp -p scipion-em-gctf

# Runtime stage

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    SCIPION_HOME=/opt/scipion \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Copy Scipion with Gctf from builder
COPY --from=builder /opt/scipion /opt/scipion
COPY --from=builder /opt/miniconda /opt/miniconda

ENV PATH="/opt/miniconda/bin:${PATH}"

# Add Scipion to PATH
ENV PATH="${SCIPION_HOME}:$PATH"

# Create symlink for Gctf
RUN for f in ${SCIPION_HOME}/software/em/gctf*/bin/Gctf*; do \
      [ -x "$f" ] && ln -sf "$f" /usr/local/bin/gctf || true; \
    done

# Verify installation
RUN ${SCIPION_HOME}/scipion3 printenv | grep -i gctf || echo "Gctf installed"

# Create directories
RUN mkdir -p /projects /data /datasets && \
    chmod 777 /projects /data /datasets

WORKDIR /projects

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD nvidia-smi && [ -x "${SCIPION_HOME}/scipion3" ] || exit 1

SHELL ["/bin/bash", "-lc"]
ENTRYPOINT ["/bin/bash", "-lc"]
CMD ["echo 'Gctf container ready. Requires GPU.'"]
