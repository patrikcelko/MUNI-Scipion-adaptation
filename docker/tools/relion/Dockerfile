# Relion Tool (CPU-only)

FROM ubuntu:22.04 AS builder

ARG DEBIAN_FRONTEND=noninteractive
ARG RELION_VERSION=4.0.1

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git cmake build-essential g++ gfortran \
    libfftw3-dev libtiff-dev zlib1g-dev \
    libxext-dev libx11-dev libxft-dev libxmu-dev \
    openmpi-bin libopenmpi-dev \
    wget pkg-config \
 && rm -rf /var/lib/apt/lists/*

# Build Relion from source (CPU-only)
RUN git clone --depth=1 --branch ${RELION_VERSION} https://github.com/3dem/relion.git /build/relion

RUN mkdir -p /build/relion/build && cd /build/relion/build && \
    cmake .. \
      -DCMAKE_INSTALL_PREFIX=/usr/local \
      -DCUDA=OFF \
      -DMPI=ON \
      -DGUI=OFF \
      -DAMDFFTW=OFF && \
    make -j"$(nproc)" && \
    make install

# Runtime stage

FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
LABEL maintainer="Patrik Čelko <patrik@celko.cz>"
LABEL description="Relion (CPU-only) with Scipion integration for Kubernetes"

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1

# Install runtime dependencies and Scipion requirements
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget curl \
    libfftw3-3 libtiff5 zlib1g \
    libxext6 libx11-6 libxft2 libxmu6 \
    openmpi-bin libopenmpi3 \
    python3 python3-pip python3-venv \
    python3-tk tk \
 && rm -rf /var/lib/apt/lists/*

# Copy Relion binaries from builder
COPY --from=builder /usr/local /usr/local

ENV LD_LIBRARY_PATH=/usr/local/lib:${LD_LIBRARY_PATH}

# Install Scipion with Relion plugin
ENV SCIPION_HOME=/opt/scipion
RUN pip3 install --no-cache-dir scipion-installer && \
    mkdir -p ${SCIPION_HOME} && \
    python3 -m scipioninstaller ${SCIPION_HOME} -noAsk

# Install Relion plugin (no binaries - we built from source)
RUN ${SCIPION_HOME}/scipion3 installp -p scipion-em-relion --noBin

# Verify installation
RUN relion_refine --version 2>&1 | head -1 && \
    echo "Relion CPU build verified"

# Create directories for data
RUN mkdir -p /projects /data /datasets && \
    chmod 777 /projects /data /datasets

COPY scripts/relion-wrapper.sh /usr/local/bin/relion-wrapper.sh
RUN chmod +x /usr/local/bin/relion-wrapper.sh

WORKDIR /projects

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD relion_refine --version || exit 1

SHELL ["/bin/bash", "-lc"]
ENTRYPOINT ["/bin/bash", "-lc"]
