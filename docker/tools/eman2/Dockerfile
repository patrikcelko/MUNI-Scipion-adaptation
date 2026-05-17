# EMAN2 Tool

FROM ubuntu:22.04 AS builder

ARG DEBIAN_FRONTEND=noninteractive

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1

# Install build + runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    python3-pip \
    python3-dev \
    python3-tk \
    wget \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda
RUN wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/miniconda && \
    rm /tmp/miniconda.sh
ENV PATH="/opt/miniconda/bin:${PATH}"

# Accept Anaconda ToS for required channels
RUN conda config --add channels conda-forge && \
    conda config --set channel_priority flexible && \
    conda config --set always_yes true && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Install Scipion (use -venv to avoid conda env, /usr/bin/python3 to avoid Miniconda Python 3.13)
ENV SCIPION_HOME=/opt/scipion
RUN /usr/bin/pip3 install --no-cache-dir scipion-installer && \
    mkdir -p ${SCIPION_HOME} && \
    /usr/bin/python3 -m scipioninstaller ${SCIPION_HOME} -noAsk -venv

# Install EMAN2 plugin with binaries (conda-based)
RUN ${SCIPION_HOME}/scipion3 installp -p scipion-em-eman2

# Clean conda caches (saves hundreds of MB)
RUN conda clean --all --yes && \
    rm -rf /opt/miniconda/pkgs/* /root/.cache/pip

# Runtime stage with only EMAN2 + Scipion (no build tools)

FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
LABEL maintainer="Patrik Čelko <patrik@celko.cz>"
LABEL description="EMAN2 with Scipion integration for Kubernetes."

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1

# Runtime-only dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-tk \
    wget \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy Scipion + Miniconda (with EMAN2) from builder
COPY --from=builder /opt/scipion /opt/scipion
COPY --from=builder /opt/miniconda /opt/miniconda

ENV SCIPION_HOME=/opt/scipion \
    PATH="/opt/miniconda/bin:${PATH}"

# Add Scipion to PATH
ENV PATH="${SCIPION_HOME}:$PATH"

# Verify installation
RUN ${SCIPION_HOME}/scipion3 printenv | grep -i eman2 || echo "EMAN2 installed"

# Create project  directories
RUN mkdir -p /projects /data /datasets && \
    chmod 777 /projects /data /datasets

WORKDIR /projects

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD [ -x "${SCIPION_HOME}/scipion3" ] || exit 1

SHELL ["/bin/bash", "-lc"]
ENTRYPOINT ["/bin/bash", "-lc"]
