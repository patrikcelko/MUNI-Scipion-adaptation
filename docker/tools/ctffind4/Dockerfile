# CTFFind Tool

FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG CTFFIND_VERSION=5.0.2
LABEL maintainer="Patrik Celko <patrik.celko@muni.cz>"
LABEL description="CTFFind ${CTFFIND_VERSION} with Scipion integration for Kubernetes"

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget curl \
    libfftw3-3 libtiff5 libpng16-16 zlib1g libjpeg-turbo8 \
    python3 python3-pip python3-venv \
    python3-tk tk \
    && rm -rf /var/lib/apt/lists/*

# Download pre-built CTFFind binary from Scipion servers
RUN wget -q "https://scipion.cnb.csic.es/downloads/scipion/software/em/ctffind-${CTFFIND_VERSION}.tgz" \
    -O /tmp/ctffind.tgz && \
    tar xzf /tmp/ctffind.tgz -C /tmp && \
    cp /tmp/ctffind-${CTFFIND_VERSION}/bin/ctffind /usr/local/bin/ctffind && \
    chmod +x /usr/local/bin/ctffind && \
    rm -rf /tmp/ctffind* && \
    ln -sf /usr/local/bin/ctffind /usr/local/bin/ctffind4

# Install Scipion with CTFFind plugin
ENV SCIPION_HOME=/opt/scipion
RUN pip3 install --no-cache-dir scipion-installer && \
    mkdir -p ${SCIPION_HOME} && \
    python3 -m scipioninstaller ${SCIPION_HOME} -noAsk

# Install CTFFind plugin
RUN ${SCIPION_HOME}/scipion3 installp -p scipion-em-cistem --noBin

# Create project directories
RUN mkdir -p /projects /data /datasets && \
    chmod 777 /projects /data /datasets

WORKDIR /projects

SHELL ["/bin/bash", "-lc"]
ENTRYPOINT ["/bin/bash", "-lc"]
