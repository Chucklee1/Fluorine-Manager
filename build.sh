#!/usr/bin/env bash
set -euo pipefail

# Build Fluorine Manager using Docker.
#
# Usage:
#   ./build.sh              # Build portable .tar.gz (default)
#   ./build.sh tarball      # Build portable .tar.gz only
#   ./build.sh installer    # Build self-extracting .bin installer only
#   ./build.sh all          # Build tarball + installer
#   ./build.sh test         # Build and run the standalone test suite
#   ./build.sh shell        # Drop into the build container for debugging
#
# Prerequisites: Docker or Podman

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Auto-detect container runtime
if command -v podman >/dev/null 2>&1; then
    DOCKER=podman
    VOLUME_SUFFIX=",Z"
elif command -v docker >/dev/null 2>&1; then
    DOCKER=docker
    VOLUME_SUFFIX=""
else
    echo "ERROR: Neither podman nor docker found in PATH"
    exit 1
fi
IMAGE_NAME="fluorine-builder"
CONTAINER_NAME="fluorine-build-$$"

cd "${SCRIPT_DIR}"

# Determine build mode from first argument
BUILD_MODE="${1:-tarball}"
case "${BUILD_MODE}" in
    tarball|installer|all|test|shell) ;;
    *)
        echo "Usage: ./build.sh [tarball|installer|all|shell]"
        echo ""
        echo "  tarball    Build portable .tar.gz"
        echo "  installer  Build self-extracting .bin installer"
        echo "  all        Build tarball + installer"
        echo "  test       Build and run the standalone test suite"
        echo "  shell      Drop into build container"
        exit 1
        ;;
esac

echo "=== Ensuring build image is up to date ==="
${DOCKER} build -t "${IMAGE_NAME}" docker/

# Persistent ccache directory for faster rebuilds.
CCACHE_DIR="${HOME}/.cache/fluorine-ccache"
mkdir -p "${CCACHE_DIR}"

if [ "${BUILD_MODE}" = "shell" ]; then
    echo "=== Dropping into build container shell ==="
    exec ${DOCKER} run --rm -it \
        -v "${SCRIPT_DIR}:/src:rw${VOLUME_SUFFIX}" \
        -v "${CCACHE_DIR}:/ccache:rw${VOLUME_SUFFIX}" \
        -e CCACHE_DIR=/ccache \
        -w /src \
        --device /dev/fuse \
        --cap-add SYS_ADMIN \
        "${IMAGE_NAME}" \
        bash
fi

echo "=== Starting build (mode: ${BUILD_MODE}) ==="
# BUILD_JOBS controls parallelism (override with `BUILD_JOBS=N ./build.sh`).
# Defaults to all available cores.
BUILD_JOBS="${BUILD_JOBS:-$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)}"
${DOCKER} run --rm \
    -v "${SCRIPT_DIR}:/src:rw${VOLUME_SUFFIX}" \
    -v "${CCACHE_DIR}:/ccache:rw${VOLUME_SUFFIX}" \
    -e CCACHE_DIR=/ccache \
    -e BUILD_MODE="${BUILD_MODE}" \
    -e BUILD_JOBS="${BUILD_JOBS}" \
    -e FLUORINE_BUILD_CHANNEL="${FLUORINE_BUILD_CHANNEL:-dev}" \
    -e FLUORINE_BUILD_NUMBER="${FLUORINE_BUILD_NUMBER:-}" \
    -e FLUORINE_BUILD_TIMESTAMP="${FLUORINE_BUILD_TIMESTAMP:-}" \
    -e FLUORINE_BUILD_COMMIT="${FLUORINE_BUILD_COMMIT:-}" \
    -w /src \
    --device /dev/fuse \
    --cap-add SYS_ADMIN \
    --name "${CONTAINER_NAME}" \
    "${IMAGE_NAME}" \
    bash /src/docker/build-inner.sh

echo ""
echo "=== Done ==="
echo "Build outputs:"
ls -ldh build/fluorine-manager build/fluorine-manager.bin 2>/dev/null || echo "  (none found)"
echo "Staging: build/staging/"
