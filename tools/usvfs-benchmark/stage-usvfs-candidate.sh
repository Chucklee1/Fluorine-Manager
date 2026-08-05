#!/usr/bin/env bash
set -euo pipefail

# Replace only the x64 Release USVFS DLL in an already-created portable
# Fluorine bundle. Run ./build.sh first. The True North harness subsequently
# deploys and hash-verifies this bundle.

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
portable_usvfs="${repo_root}/build/fluorine-manager/usvfs"
portable_core="${repo_root}/build/fluorine-manager/ModOrganizer-core"
portable_root="${repo_root}/build/fluorine-manager"
bundle_version="${portable_root}/fluorine-bundle-version.txt"
source_dll="${1:-}"
source_commit="${2:-}"
workflow_run="${3:-}"

if [[ -z "${source_dll}" || -z "${source_commit}" || -z "${workflow_run}" ]]; then
  printf 'Usage: %s DLL SOURCE_COMMIT WORKFLOW_RUN_URL\n' "$0" >&2
  exit 2
fi

if [[ ! -f "${source_dll}" ]]; then
  printf 'Candidate DLL does not exist: %s\n' "${source_dll}" >&2
  exit 1
fi
if [[ ! "${source_commit}" =~ ^[0-9a-fA-F]{40}$ ]]; then
  printf 'SOURCE_COMMIT must be a full 40-character Git object ID.\n' >&2
  exit 2
fi
if [[ "${workflow_run}" != https://github.com/*/actions/runs/* ]]; then
  printf 'WORKFLOW_RUN_URL is not a GitHub Actions run URL.\n' >&2
  exit 2
fi
if [[ ! -d "${portable_usvfs}" ]]; then
  printf 'Portable USVFS directory is missing; run ./build.sh first.\n' >&2
  exit 1
fi
if [[ ! -f "${portable_core}" ]]; then
  printf 'Portable core is missing; run ./build.sh first.\n' >&2
  exit 1
fi

pe_description="$(file -b "${source_dll}")"
if [[ "${pe_description}" != *"PE32+ executable"* ||
      "${pe_description}" != *"x86-64"* ]]; then
  printf 'Candidate is not an x64 PE DLL: %s\n' "${pe_description}" >&2
  exit 1
fi

source_sha="$(sha256sum "${source_dll}" | cut -d' ' -f1)"
install -m 0644 "${source_dll}" "${portable_usvfs}/usvfs_x64.dll"
cmp -s "${source_dll}" "${portable_usvfs}/usvfs_x64.dll"

metadata="${portable_usvfs}/fluorine-candidate-build.txt"
{
  printf 'format=1\n'
  printf 'source_commit=%s\n' "${source_commit,,}"
  printf 'workflow_run=%s\n' "${workflow_run}"
  printf 'usvfs_x64_sha256=%s\n' "${source_sha}"
  printf 'pe_description=%s\n' "${pe_description}"
  printf 'staged_utc=%s\n' "$(date -u --iso-8601=seconds)"
} >"${metadata}"

# Current bundles use a content-derived identity so a DLL-only candidate cannot
# be mistaken for the previously deployed bundle. Recompute it after writing
# both the DLL and provenance. Keep the core-mtime nudge only for compatibility
# with an already-built older portable bundle.
if [[ -f "${bundle_version}" ]]; then
  bundle_sha="$({
    cd "${portable_root}"
    find . -type f \
      ! -path './fluorine-bundle-version.txt' \
      ! -path './fluorine-manifest.txt' -print0 \
      | LC_ALL=C sort -z \
      | xargs -0 sha256sum \
      | sha256sum \
      | cut -d' ' -f1
  })"
  {
    printf 'format=1\n'
    printf 'payload_sha256=%s\n' "${bundle_sha}"
  } >"${bundle_version}"
else
  touch "${portable_core}"
fi

printf 'Staged USVFS x64 candidate: %s\n' "${source_sha}"
printf 'Metadata: %s\n' "${metadata}"
