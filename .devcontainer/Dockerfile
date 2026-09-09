ARG VARIANT=ubuntu-24.04
FROM mcr.microsoft.com/vscode/devcontainers/base:${VARIANT}

ENV DEBIAN_FRONTEND=noninteractive
ENV PDK_ROOT=/home/vscode/ttsetup/pdk
ENV PDK=ihp-sg13g2
ARG TT_SUPPORT_TOOLS_BRANCH=main
# ngspice / OpenVAF pins for the extracted RO transient validation
# (docs/ro-spice-validation.md).  ngspice must be built from source: the
# Ubuntu 24.04 package is 42, whose OSDI loader accepts only OSDI v0.3 while
# OpenVAF-Reloaded emits v0.4 (see docs/ro-spice-validation.md).
ARG NGSPICE_VERSION=45
ARG OPENVAF_VERSION=v24.0.2mob

RUN apt-get update
RUN apt-get install -y -o Acquire::Retries=10 iverilog gtkwave python3 python3-pip python3-venv python3-tk python-is-python3 libcairo2 verilator libpng-dev libqhull-dev

# Clone tt-support-tools
RUN mkdir -p /ttsetup
RUN git clone -b ${TT_SUPPORT_TOOLS_BRANCH} https://github.com/TinyTapeout/tt-support-tools /ttsetup/tt-support-tools

COPY test/requirements.txt /ttsetup/test_requirements.txt
COPY .devcontainer/copy_tt_support_tools.sh /ttsetup

RUN python -m venv /ttsetup/venv
RUN /ttsetup/venv/bin/python -m pip install --upgrade pip setuptools wheel && \
    /ttsetup/venv/bin/python -m pip install \
        --only-binary=klayout \
        -r /ttsetup/test_requirements.txt \
        -r /ttsetup/tt-support-tools/requirements.txt

# Install verible (for formatting)
RUN umask 022 && \
    curl -L --retry 10 --retry-delay 5 --retry-all-errors --continue-at - \
    https://github.com/chipsalliance/verible/releases/download/v0.0-4023-gc1271a00/verible-v0.0-4023-gc1271a00-linux-static-x86_64.tar.gz | \
    tar zxf - -C /usr/local --strip-components=1 && \
    chmod 755 /usr/local/bin

# Install LibreLane
RUN /ttsetup/venv/bin/pip install librelane==3.0.0.dev44

# ---------------------------------------------------------------------------
# ngspice (extracted RO transient validation, docs/ro-spice-validation.md).
# Built from source with OSDI support so the IHP SG13G2 PSP103 Verilog-A
# models (compiled by OpenVAF-Reloaded) can be loaded; KLU is enabled by
# default and used for the RO transient decks.
# ---------------------------------------------------------------------------
RUN apt-get install -y -o Acquire::Retries=10 \
        build-essential automake autoconf bison flex \
        libx11-dev libxaw7-dev libreadline-dev libfftw3-dev \
        libsuitesparse-dev pkg-config && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN cd /ttsetup && \
    curl -L --retry 10 --retry-delay 5 --retry-all-errors -o ngspice.tar.gz \
      "https://downloads.sourceforge.net/project/ngspice/ng-spice-rework/old-releases/${NGSPICE_VERSION}/ngspice-${NGSPICE_VERSION}.tar.gz" && \
    tar xzf ngspice.tar.gz && \
    cd ngspice-${NGSPICE_VERSION} && \
    ./configure --enable-osdi --enable-openmp --disable-debug \
        --prefix=/usr/local >/ttsetup/ngspice-configure.log 2>&1 && \
    make -j"$(nproc)" >/ttsetup/ngspice-build.log 2>&1 && \
    make install >/ttsetup/ngspice-install.log 2>&1 && \
    cd /ttsetup && rm -rf ngspice-${NGSPICE_VERSION} ngspice.tar.gz && \
    ngspice --version

# ---------------------------------------------------------------------------
# OpenVAF-Reloaded: compiles the PDK's PSP103 Verilog-A models to OSDI.
# Needs libLLVM 18 (Ubuntu 24.04 ships 18.1.3).
# ---------------------------------------------------------------------------
RUN apt-get install -y -o Acquire::Retries=10 libllvm18 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN cd /tmp && \
    curl -L --retry 10 --retry-delay 5 --retry-all-errors -o openvaf.tar.gz \
      "https://github.com/OpenVAF/OpenVAF-Reloaded/releases/download/${OPENVAF_VERSION}/openvaf-r-${OPENVAF_VERSION}-linux-x86_64.tar.gz" && \
    tar xzf openvaf.tar.gz && \
    install -m 0755 openvaf-r-${OPENVAF_VERSION}-linux-x86_64/bin/openvaf-r \
        /usr/local/bin/openvaf-r && \
    rm -rf /tmp/openvaf.tar.gz /tmp/openvaf-r-${OPENVAF_VERSION}-linux-x86_64 && \
    openvaf-r --version

# Compile the PDK PSP models to OSDI at container start (the PDK is downloaded
# by CIEL on first use, so it is not present at image build time).
COPY .devcontainer/compile_pdk_osdi.sh /ttsetup/compile_pdk_osdi.sh
RUN chmod +x /ttsetup/compile_pdk_osdi.sh
