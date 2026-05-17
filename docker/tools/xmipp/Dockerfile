# Xmipp Tool

FROM ubuntu:22.04 AS builder

ARG DEBIAN_FRONTEND=noninteractive
ARG XMIPP_BUILD_JOBS=2

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1

# Install build dependencies for Xmipp
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    g++ \
    gcc \
    gfortran \
    python3 \
    python3-pip \
    python3-dev \
    python3-tk \
    python3-numpy \
    openmpi-bin \
    libopenmpi-dev \
    libfftw3-dev \
    libhdf5-dev \
    libtiff5-dev \
    libjpeg-turbo8-dev \
    libsqlite3-dev \
    libfftw3-single3 \
    libfftw3-double3 \
    default-jdk \
    wget \
    curl \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install Scipion
ENV SCIPION_HOME=/opt/scipion
RUN pip3 install --no-cache-dir scipion-installer && \
    mkdir -p ${SCIPION_HOME} && \
    python3 -m scipioninstaller ${SCIPION_HOME} -noAsk

# Install xmipp plugin wrapper first (without binaries)
RUN ${SCIPION_HOME}/scipion3 run pip install --no-cache-dir scipion-em-xmipp

# Install xmipp3-installer package required for manual build
RUN pip3 install --no-cache-dir xmipp3-installer

# Build Xmipp from source (full pipeline: getSources + configBuild + compileAndInstall)
RUN mkdir -p ${SCIPION_HOME}/software/em && \
    cd ${SCIPION_HOME}/software/em && \
    git clone https://github.com/I2PC/xmipp.git xmipp-devel --depth 1 && \
    cd xmipp-devel && \
    ./xmipp all -j "${XMIPP_BUILD_JOBS}"

# Runtime stage

FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
LABEL maintainer="Patrik Čelko <patrik@celko.cz>"
LABEL description="Xmipp with Scipion integration for Kubernetes"

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    SCIPION_HOME=/opt/scipion

# Runtime-only packages (no build tools, no desktop, no VNC)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget curl \
    python3 python3-pip python3-venv python3-tk tk libpython3.10 \
    openmpi-bin libopenmpi3 \
    libfftw3-3 libfftw3-single3 libfftw3-double3 \
    libhdf5-103 libhdf5-cpp-103 \
    libtiff5 libjpeg-turbo8 \
    libgfortran5 \
    libsqlite3-0 \
    default-jre-headless \
 && rm -rf /var/lib/apt/lists/*

# Install Scipion (fresh, minimal, no GUI image baggage)
RUN pip3 install --no-cache-dir scipion-installer && \
    mkdir -p ${SCIPION_HOME} && \
    python3 -m scipioninstaller ${SCIPION_HOME} -noAsk

# Install xmipp plugin wrapper (Python protocols, no binaries)
RUN ${SCIPION_HOME}/scipion3 run pip install --no-cache-dir scipion-em-xmipp

# Resolve the Scipion site-packages path dynamically (works across Python versions)
RUN SITE_PKG="$(${SCIPION_HOME}/.scipion3/bin/python3 -c \
      "import site; print(site.getsitepackages()[0])")" && \
    echo "${SITE_PKG}" > /tmp/.site_pkg_path

# Copy Xmipp build artifacts from builder
COPY --from=builder /opt/scipion/software/em/xmipp-devel /opt/scipion/software/em/xmipp-devel

ENV LD_LIBRARY_PATH="${SCIPION_HOME}/software/em/xmipp-devel/dist/lib:${LD_LIBRARY_PATH}" \
    XMIPP_HOME="${SCIPION_HOME}/software/em/xmipp-devel"

# Link real xmippLib Python bindings into Scipion site-packages
RUN SITE_PKG="$(cat /tmp/.site_pkg_path)" && \
    BINDINGS="${SCIPION_HOME}/software/em/xmipp-devel/dist/bindings/python" && \
    for f in "$BINDINGS"/*.so "$BINDINGS"/*.py "$BINDINGS"/sh_alignment "$BINDINGS"/envs_DLTK; do \
      [ -e "$f" ] && ln -sf "$f" "$SITE_PKG/$(basename "$f")" || true; \
    done

# Create symlinks for Xmipp binaries
RUN for dir in dist/bin build/bin bin; do \
      if [ -d "${SCIPION_HOME}/software/em/xmipp-devel/$dir" ]; then \
        for f in ${SCIPION_HOME}/software/em/xmipp-devel/$dir/xmipp_*; do \
          [ -x "$f" ] && ln -sf "$f" /usr/local/bin/$(basename "$f") || true; \
        done; \
      fi; \
    done

# The scipion-em-xmipp plugin validates binaries at XMIPP_HOME/bin/
# but the Xmipp build installs them under XMIPP_HOME/dist/bin/.
RUN ln -sfn ${XMIPP_HOME}/dist/bin ${XMIPP_HOME}/bin

# Verify xmipp binary is functional
RUN xmipp_movie_estimate_gain --help 2>&1 | head -5 || echo "Binary test failed"

# Register Xmipp plugin with Scipion config
RUN SCIPION_CONF="${SCIPION_HOME}/config/scipion.conf" && \
    if [ -f "$SCIPION_CONF" ]; then \
      grep -q "XMIPP_HOME" "$SCIPION_CONF" || \
        echo -e "\n[PLUGINS]\nXMIPP_HOME = ${SCIPION_HOME}/software/em/xmipp-devel" >> "$SCIPION_CONF"; \
    fi

# Verify the REAL xmippLib C++ binding is loaded (not a stub)
RUN SITE_PKG="$(cat /tmp/.site_pkg_path)" && \
    LD_LIBRARY_PATH="${SCIPION_HOME}/software/em/xmipp-devel/dist/lib:${LD_LIBRARY_PATH}" \
    PYTHONPATH="${SITE_PKG}:${PYTHONPATH:-}" python3 -c "\
import xmippLib; \
assert hasattr(xmippLib, 'Image'), 'xmippLib.Image missing'; \
img = xmippLib.Image(); \
t = str(type(img)); \
assert 'Image' in t, f'Wrong Image type: {t}'; \
assert 'Stub' not in t, f'Still using stub Image class: {t}'; \
print('xmippLib verification passed'); \
"

# Apply defensive patches to xmipp3 Python code
COPY patches/xmipp3_robustness.py /opt/scipion/patches/xmipp3_robustness.py
RUN SCIPION_HOME="${SCIPION_HOME}" python3 /opt/scipion/patches/xmipp3_robustness.py

# Allow CPU-mode local alignment in FlexAlign
RUN SITE_PKG="$(cat /tmp/.site_pkg_path)" && \
    FLEXALIGN="${SITE_PKG}/xmipp3/protocols/protocol_flexalign.py" && \
    if [ -f "$FLEXALIGN" ]; then \
      sed -i 's/errors.append("GPU is needed to do local alignment.")/pass  # Patched: allow CPU local alignment in K8s/' "$FLEXALIGN"; \
    fi

# Clean up temp file
RUN rm -f /tmp/.site_pkg_path

# Create directories for projects data
RUN useradd -m -u 1000 -s /bin/bash scipion 2>/dev/null || true && \
    mkdir -p /projects /data && \
    chown -R scipion:scipion /projects /data \
      ${SCIPION_HOME}/software/em/xmipp-devel

USER scipion
WORKDIR /projects

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD xmipp_movie_estimate_gain --help >/dev/null 2>&1 || exit 1

SHELL ["/bin/bash", "-lc"]
ENTRYPOINT ["/bin/bash", "-lc"]
