# Scipion3 + TurboVNC + VirtualGL + noVNC on CUDA/OpenGL

ARG CUDA_TAG=12.4.0-runtime-ubuntu22.04
# It can be cudaGL, depends on GPU type!
FROM nvidia/cuda:${CUDA_TAG}

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    USER=scipion UID=1000 HOME=/home/scipion \
    VNC_DISPLAY=1 VNC_GEOMETRY=1920x1080 VNC_DEPTH=24

# Install basic packages
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget git gnupg \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install GUI and system stuff
RUN apt-get update && apt-get install -y --no-install-recommends \
      tini xauth xterm xfce4 xfce4-terminal dbus-x11 supervisor \
      libglvnd0 libgl1 libglx0 libxext6 libx11-6 libglu1-mesa mesa-utils \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install VNC and development packages
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential python3 python3-pip python3-venv openjdk-11-jre libopenmpi-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install VNC software from repositories
RUN apt-get update && apt-get install -y --no-install-recommends \
      novnc websockify \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install TurboVNC and VirtualGL (be careful about version!)
ARG VNC_VER=3.0.3
ARG VGL_VER=3.1

RUN set -eux; \
    apt-get update; apt-get install -y --no-install-recommends ca-certificates wget; \
    cd /tmp; \
    wget -nv -O turbovnc.deb "https://github.com/TurboVNC/turbovnc/releases/download/${VNC_VER}/turbovnc_${VNC_VER}_amd64.deb"; \
    wget -nv -O virtualgl.deb "https://github.com/VirtualGL/virtualgl/releases/download/${VGL_VER}/virtualgl_${VGL_VER}_amd64.deb"; \
    dpkg -i turbovnc.deb virtualgl.deb || { apt-get -y -f install; dpkg -i turbovnc.deb virtualgl.deb; }; \
    rm -f /tmp/*.deb; \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Based on https://scipion-em.github.io/docs/release-3.0.0/docs/scipion-modes/install-from-sources
ENV SCIPION_HOME=/opt/scipion

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-tk tk \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir scipion-installer \
    && mkdir -p ${SCIPION_HOME} \
    && python3 -m scipioninstaller ${SCIPION_HOME} -noAsk

ENV PATH="/opt/TurboVNC/bin:/opt/VirtualGL/bin:${PATH}"

RUN useradd -m -u ${UID} -s /bin/bash ${USER} \
    && mkdir -p /opt/startup /data /projects ${SCIPION_HOME} \
    && chown -R ${USER}:${USER} /opt/startup /data /projects ${SCIPION_HOME} /home/${USER} \
    && install -d -m 700 -o ${UID} -g ${UID} /home/${USER}/.vnc

COPY scripts/entrypoint.sh /opt/startup/entrypoint.sh
COPY scripts/xstartup.sh /opt/startup/xstartup.sh
COPY scripts/scipion3-gpu /usr/local/bin/scipion3-gpu

RUN ln -sf /opt/startup/entrypoint.sh /entrypoint.sh \
    && chmod +x /opt/startup/entrypoint.sh /entrypoint.sh /opt/startup/xstartup.sh \
      /usr/local/bin/scipion3-gpu

RUN chown -R ${UID}:${UID} /opt/startup /home/${USER}

USER ${USER}
WORKDIR ${HOME}

EXPOSE 5801 5901

ENTRYPOINT ["/usr/bin/tini","-g","--"]
CMD ["/opt/startup/entrypoint.sh"]
