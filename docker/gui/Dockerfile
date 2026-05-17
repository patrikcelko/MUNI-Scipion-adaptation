# Scipion3 GUI

# Stage 1: Install Scipion in a builder with full dev tools
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    SCIPION_HOME=/opt/scipion

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-tk tk \
    build-essential wget ca-certificates git curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir scipion-installer \
    && mkdir -p ${SCIPION_HOME} \
    && python3 -m scipioninstaller ${SCIPION_HOME} -noAsk

# Stage 2: Runtime, only what the GUI needs
FROM ubuntu:22.04

ARG UID=1000
ARG GID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    USER=scipion UID=${UID} GID=${GID} HOME=/home/scipion \
    VNC_DISPLAY=1 VNC_GEOMETRY=1920x1080 VNC_DEPTH=24 \
    SCIPION_HOME=/opt/scipion

# Core packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget tini \
    python3 python3-pip python3-venv python3-tk tk \
    openjdk-11-jre-headless \
    xauth xterm xfce4 xfce4-terminal dbus-x11 \
    libglvnd0 libgl1 libglx0 libxext6 libx11-6 libglu1-mesa \
    libegl1-mesa mesa-utils \
    novnc websockify \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# TurboVNC + VirtualGL
ARG VNC_VER=3.0.3
ARG VGL_VER=3.1

RUN cd /tmp \
    && wget -nv -O turbovnc.deb \
    "https://github.com/TurboVNC/turbovnc/releases/download/${VNC_VER}/turbovnc_${VNC_VER}_amd64.deb" \
    && wget -nv -O virtualgl.deb \
    "https://github.com/VirtualGL/virtualgl/releases/download/${VGL_VER}/virtualgl_${VGL_VER}_amd64.deb" \
    && apt-get update \
    && dpkg -i turbovnc.deb virtualgl.deb || true \
    && apt-get -y -f install \
    && rm -f /tmp/*.deb \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy pre-built Scipion from builder stage (no build tools in runtime)
COPY --from=builder /opt/scipion /opt/scipion

ENV PATH="/opt/TurboVNC/bin:/opt/VirtualGL/bin:${PATH}"

RUN groupadd -g ${GID} ${USER} \
    && useradd -m -u ${UID} -g ${GID} -s /bin/bash ${USER} \
    && mkdir -p /opt/startup /data /projects ${SCIPION_HOME} \
    && chown -R ${USER}:${USER} /opt/startup /data /projects ${SCIPION_HOME} /home/${USER} \
    && install -d -m 700 -o ${UID} -g ${UID} /home/${USER}/.vnc

# GUI container scripts
COPY docker/gui/scripts/entrypoint.sh /opt/startup/entrypoint.sh
COPY docker/gui/scripts/xstartup.sh /opt/startup/xstartup.sh
COPY docker/gui/scripts/scipion3-gpu /usr/local/bin/scipion3-gpu
COPY task_monitor/monitor/ /opt/startup/monitor/

# Queue proxy script
COPY docker/gui/scripts/task-submit.sh /usr/local/bin/task-submit.sh

# Example project auto-setup script
COPY examples/setup_example.py /opt/startup/setup_example.py

# Scipion configuration files
COPY docker/config/scipion.conf /opt/startup/scipion.conf
COPY docker/config/hosts.conf /opt/startup/hosts.conf

# Xmipp patches
COPY docker/tools/xmipp/patches/patch_xmipp_init.py /opt/startup/patch_xmipp_init.py
COPY docker/tools/xmipp/patches/xmippLib_stub.py /opt/startup/xmippLib_stub.py
COPY docker/tools/xmipp/patches/wrap_xmipp_imports.py /opt/startup/wrap_xmipp_imports.py
COPY docker/tools/xmipp/patches/xmipp3_robustness.py /opt/startup/xmipp3_robustness.py

# Example pipelines
COPY examples/pipelines/ /opt/startup/pipelines/

# Install Scipion plugins
RUN ${SCIPION_HOME}/.scipion3/bin/python3 -m pip install --no-cache-dir --no-deps \
    scipion-em-xmipp==23.3.0.3 \
    scipion-em-cistem==3.10.1 \
    scipion-em-relion==5.0.2 \
    scipion-em-gctf==3.2.2 \
    && ${SCIPION_HOME}/.scipion3/bin/python3 -m pip install --no-cache-dir \
    emtools xmltodict

# Build xmippLib / xmipp_base stubs and patch fragile imports
RUN SITE_PKG="${SCIPION_HOME}/.scipion3/lib/python3.10/site-packages" \
    && python3 /opt/startup/patch_xmipp_init.py "${SITE_PKG}" /opt/startup/xmippLib_stub.py \
    && python3 /opt/startup/wrap_xmipp_imports.py "${SITE_PKG}/xmipp3/protocols/__init__.py"

# Apply xmipp3 robustness patches
RUN SCIPION_HOME="${SCIPION_HOME}" python3 /opt/startup/xmipp3_robustness.py

# Create stub directories for tool HOME paths so the GUI scheduler's
# validate() passes. Actual binaries run in job pod containers.
# The scipion3 launcher sets SCIPION_HOME=/opt/scipion/.scipion3, so we
# symlink .scipion3/software/em -> software/em to cover both paths.
RUN mkdir -p ${SCIPION_HOME}/software/em/xmipp/bin \
    ${SCIPION_HOME}/software/em/cistem-1.0.0-beta \
    ${SCIPION_HOME}/software/em/ctffind-5.0.2 \
    ${SCIPION_HOME}/software/em/relion-5.0 \
    ${SCIPION_HOME}/software/em/gctf-1.18 \
    && touch ${SCIPION_HOME}/software/em/xmipp/bin/xmipp_movie_alignment_correlation \
    && touch ${SCIPION_HOME}/software/em/xmipp/bin/xmipp_cuda_movie_alignment_correlation \
    && chmod +x ${SCIPION_HOME}/software/em/xmipp/bin/xmipp_movie_alignment_correlation \
    && chmod +x ${SCIPION_HOME}/software/em/xmipp/bin/xmipp_cuda_movie_alignment_correlation \
    && mkdir -p ${SCIPION_HOME}/.scipion3/software \
    && ln -sf ${SCIPION_HOME}/software/em ${SCIPION_HOME}/.scipion3/software/em

RUN ln -sf /opt/startup/entrypoint.sh /entrypoint.sh \
    && chmod +x /opt/startup/entrypoint.sh /entrypoint.sh /opt/startup/xstartup.sh \
    /usr/local/bin/scipion3-gpu /usr/local/bin/task-submit.sh \
    && ln -sf /usr/local/bin/task-submit.sh /usr/local/bin/qsub \
    && ln -sf /usr/local/bin/task-submit.sh /usr/local/bin/qstat \
    && ln -sf /usr/local/bin/task-submit.sh /usr/local/bin/qdel

RUN chown -R ${UID}:${UID} /opt/startup /home/${USER}

USER ${USER}
WORKDIR ${HOME}

EXPOSE 5801 5901

ENTRYPOINT ["/usr/bin/tini","-g","--"]
CMD ["/opt/startup/entrypoint.sh"]
