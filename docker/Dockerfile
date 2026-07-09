FROM ubuntu:25.10

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV RUSTUP_HOME=/opt/rust/rustup
ENV CARGO_HOME=/opt/rust/cargo
ENV PATH="/opt/rust/cargo/bin:${PATH}"

# ── System build tools + all library dependencies ──
# Python comes from uv (python-build-standalone), not apt.
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build essentials
    build-essential cmake meson ninja-build ccache \
    git curl wget file binutils patchelf pkg-config ca-certificates \
    fonts-dejavu-core \
    # Library dependencies
    libboost-all-dev \
    libsqlite3-dev \
    libtinyxml2-dev \
    libfontconfig1-dev \
    libspdlog-dev \
    libfuse3-dev fuse3 libcap-dev libnuma-dev \
    liblz4-dev zlib1g-dev libzstd-dev libbz2-dev liblzma-dev \
    libssl-dev libcurl4-openssl-dev \
    libtomlplusplus-dev \
    # Qt 6 runtime deps (aqtinstall provides Qt 6.11 headers/tools/libs for build)
    kde-style-breeze \
    libgl-dev libopengl-dev libvulkan-dev libxkbcommon-dev libfontconfig1-dev \
    libfreetype-dev libx11-dev libxext-dev libxfixes-dev \
    libxi-dev libxrender-dev libxcb1-dev libxcb-cursor-dev \
    libxcb-glx0-dev libxcb-keysyms1-dev libxcb-image0-dev \
    libxcb-shm0-dev libxcb-icccm4-dev libxcb-sync-dev \
    libxcb-xfixes0-dev libxcb-shape0-dev libxcb-randr0-dev \
    libxcb-render-util0-dev libxcb-xinerama0-dev \
    libxcb-xkb-dev libxkbcommon-x11-dev libatspi2.0-dev \
    libwayland-dev \
    # Misc
    zip unzip \
    # Static analysis
    clang-tidy \
    # WebP support for Qt image format plugin
    libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

# Build a pinned upstream libfuse so Fluorine compiles and bundles matching
# headers/runtime across supported build images.
ARG LIBFUSE_VERSION=3.18.2
RUN curl -L --fail \
      "https://github.com/libfuse/libfuse/releases/download/fuse-${LIBFUSE_VERSION}/fuse-${LIBFUSE_VERSION}.tar.gz" \
      -o /tmp/libfuse.tar.gz && \
    tar -xf /tmp/libfuse.tar.gz -C /tmp && \
    meson setup /tmp/libfuse-build "/tmp/fuse-${LIBFUSE_VERSION}" \
      --prefix=/usr \
      --libdir=lib/x86_64-linux-gnu \
      -Dexamples=false \
      -Dutils=true \
      -Dtests=false \
      -Duseroot=false && \
    meson compile -C /tmp/libfuse-build && \
    meson install -C /tmp/libfuse-build && \
    ldconfig && \
    test "$(pkg-config --modversion fuse3)" = "${LIBFUSE_VERSION}" && \
    rm -rf /tmp/libfuse.tar.gz "/tmp/fuse-${LIBFUSE_VERSION}" /tmp/libfuse-build

# ── uv (Astral) ──
# Single static binary; manages Python interpreters and packages.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ── python-build-standalone 3.12 via uv (build-time + bundled runtime) ──
# uv pulls the same PBS tarballs we used to curl by hand.  We install into
# a scratch dir and `mv` the cpython-* tree to /opt/python-bundled so the
# downstream build can rely on a stable, non-symlink path.
ARG PYTHON_VERSION=3.12.13
RUN uv python install --install-dir /opt/uv-tmp "${PYTHON_VERSION}" && \
    PY_DIR="$(find /opt/uv-tmp -maxdepth 1 -type d -name 'cpython-*' | head -n1)" && \
    test -n "${PY_DIR}" && \
    mv "${PY_DIR}" /opt/python-bundled && \
    rm -rf /opt/uv-tmp && \
    /opt/python-bundled/bin/python3 --version
ENV BUILD_PYTHON=/opt/python-bundled/bin/python3
ENV PATH="/opt/python-bundled/bin:${PATH}"

# ── Qt 6.11 via aqtinstall (one-off via uv tool run) ──
RUN uv tool run --from aqtinstall aqt install-qt linux desktop 6.11.1 linux_gcc_64 \
      -m qtwebsockets qtwaylandcompositor qtnetworkauth qttasktree qtimageformats \
      --outputdir /opt/qt6 && \
    ls /opt/qt6/6.11.1/gcc_64/bin/qmake
ENV Qt6_DIR=/opt/qt6/6.11.1/gcc_64
ENV CMAKE_PREFIX_PATH="/opt/qt6/6.11.1/gcc_64:${CMAKE_PREFIX_PATH}"
ENV PATH="/opt/qt6/6.11.1/gcc_64/bin:${PATH}"
ENV LD_LIBRARY_PATH="/opt/qt6/6.11.1/gcc_64/lib:${LD_LIBRARY_PATH}"

# ── Build-time Python packages ──
# pybind11/sip/etc. for compiling mobase.so; PyQt6 is staged into the distribution.
RUN uv pip install --system --break-system-packages \
      --python /opt/python-bundled/bin/python3 --no-cache \
      pybind11==2.13.6 sip psutil larian-formats==0.8.1 vdf "PyQt6>=6.11,<6.12"

# ── Rust toolchain ──
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain stable --profile minimal

WORKDIR /build
