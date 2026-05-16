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

# Install Scipion
ENV SCIPION_HOME=/opt/scipion
RUN pip3 install --no-cache-dir scipion-installer && \
    mkdir -p ${SCIPION_HOME} && \
    python3 -m scipioninstaller ${SCIPION_HOME} -noAsk

# Install EMAN2 plugin with binaries (conda-based)
RUN ${SCIPION_HOME}/scipion3 installp -p scipion-em-eman2

# Patch _libNone.Image (avoids AttributeError in container)
COPY patch_libnone.py /tmp/patch_libnone.py
RUN python3 /tmp/patch_libnone.py && rm /tmp/patch_libnone.py

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
