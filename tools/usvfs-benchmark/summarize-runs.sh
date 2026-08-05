#!/usr/bin/env bash
set -euo pipefail

# Emit one comparable TSV row per run-true-north.sh result directory. Feed the
# output to a spreadsheet/statistics tool only after filtering validity=PASS.

if (($# == 0)); then
  printf 'Usage: %s RESULT_DIR [RESULT_DIR ...]\n' "$0" >&2
  exit 2
fi

metadata_value()
{
  local file="$1"
  local key="$2"
  sed -n "s/^${key}=//p" "${file}" | head -n 1
}

benchmark_value()
{
  local file="$1"
  local phase="$2"
  local key="$3"
  local line
  line="$(rg -m 1 "phase=${phase}( |$)" "${file}" || true)"
  tr -d '\r' <<<"${line}" | tr ' ' '\n' | sed -n "s/^${key}=//p"
}

to_epoch()
{
  local timestamp="$1"
  local zone="${2:-}"
  [[ -n "${timestamp}" ]] || return 0
  date -d "${timestamp}${zone:+ ${zone}}" +%s.%N
}

delta_ms()
{
  local start="$1"
  local finish="$2"
  if [[ -z "${start}" || -z "${finish}" ]]; then
    return 0
  fi
  awk -v start="${start}" -v finish="${finish}" \
    'BEGIN { printf "%.3f", (finish - start) * 1000 }'
}

printf '%s\n' \
  $'run_id\tvalidity\tusvfs_x64_sha256\tmappings\tmapping_install_ms\tdll_load_ms\ttarget_inject_ms\tbefore_to_skyrim_ms\tbefore_to_actor_ms\tbefore_to_menu_ms\tdbvo_c000000f'

for result_dir in "$@"; do
  metadata="${result_dir}/metadata.txt"
  benchmark="${result_dir}/benchmark.txt"
  validity_file="${result_dir}/validity.txt"
  if [[ ! -f "${metadata}" || ! -f "${benchmark}" ]]; then
    printf 'Not a benchmark result directory: %s\n' "${result_dir}" >&2
    exit 1
  fi

  run_id="$(metadata_value "${metadata}" run_id)"
  validity="$(metadata_value "${validity_file}" result 2>/dev/null || true)"
  [[ -n "${validity}" ]] || validity="LEGACY"
  dll_sha="$(awk '/usvfs_x64\.dll$/ { print $1; exit }' "${metadata}")"
  mappings="$(benchmark_value "${benchmark}" mapping_install mappings)"
  mapping_ms="$(benchmark_value "${benchmark}" mapping_install elapsed_ms)"
  dll_ms="$(benchmark_value "${benchmark}" dll_load elapsed_ms)"
  inject_ms="$(benchmark_value "${benchmark}" target_inject elapsed_ms)"

  before_timestamp="$(metadata_value "${metadata}" before_run_utc)"
  captured_timeline="${result_dir}/interface-timeline.txt"
  if [[ -z "${before_timestamp}" && -f "${captured_timeline}" ]]; then
    before_timestamp="$(sed -nE \
      's/^[0-9]+:\[([^]]+) [A-Z]\] beforeRun: using.*/\1/p' \
      "${captured_timeline}" | head -n 1)"
  fi
  interface_log="$(metadata_value "${metadata}" interface_log)"
  if [[ -z "${before_timestamp}" && -f "${interface_log}" ]]; then
    before_timestamp="$(rg -m 1 'beforeRun: using' "${interface_log}" |
      sed -nE 's/^\[([^]]+) [A-Z]\].*/\1/p')"
  fi
  before_epoch="$(to_epoch "${before_timestamp}" UTC)"
  skyrim_timestamp="$(metadata_value "${metadata}" skyrim_observed_utc)"
  skyrim_epoch="$(to_epoch "${skyrim_timestamp}")"

  actor_timestamp="$(awk -F'\t' '$3 ~ /ActorLimitFix\.log$/ {print $1; exit}' \
    "${result_dir}/skse-logs.txt" 2>/dev/null || true)"
  menu_timestamp="$(awk -F'\t' '$3 ~ /MainMenuRandomizer\.log$/ {print $1; exit}' \
    "${result_dir}/skse-logs.txt" 2>/dev/null || true)"
  actor_epoch="$(to_epoch "${actor_timestamp}")"
  menu_epoch="$(to_epoch "${menu_timestamp}")"
  dbvo="$(metadata_value "${validity_file}" 'metric dbvo_c000000f' \
    2>/dev/null || true)"
  if [[ -z "${dbvo}" ]]; then
    usvfs_log="$(metadata_value "${metadata}" usvfs_log)"
    dbvo="$(rg -c 'c000000f' "${usvfs_log}" 2>/dev/null || true)"
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "${run_id}" "${validity}" "${dll_sha}" "${mappings}" "${mapping_ms}" \
    "${dll_ms}" "${inject_ms}" \
    "$(delta_ms "${before_epoch}" "${skyrim_epoch}")" \
    "$(delta_ms "${before_epoch}" "${actor_epoch}")" \
    "$(delta_ms "${before_epoch}" "${menu_epoch}")" "${dbvo:-0}"
done
