#!/usr/bin/env bash
set -euo pipefail

runtime_dir=""
corpus_dir="/home/luke/Games/VFS Benchmarks/usvfs-100k-v1"
results_root="/home/luke/Games/VFS Benchmarks/results"
compat_data="/home/luke/.local/share/fluorine/VFSBenchmarkPrefix"
proton="/home/luke/.local/share/Steam/compatibilitytools.d/Proton-GE Latest/proton"
steam_root="/home/luke/.local/share/Steam"
files=100000
directories=4096
layers=8
iterations=3
threads=8
seed=6148352776335410510
require_profile=true
shared_context=false
exact_query_exhaustion=false
cleanup_grace_attempts=40
cleanup_grace_interval=0.25

usage()
{
  printf '%s\n' \
    "Usage: $0 --runtime DIR [options]" \
    "" \
    "Required runtime files: usvfs_benchmark_x64.exe and usvfs_x64.dll" \
    "Options:" \
    "  --corpus DIR       Generated/reused corpus directory" \
    "  --results DIR      Capture parent directory" \
    "  --compat-data DIR  Dedicated Proton compatibility-data directory" \
    "  --proton FILE      Proton launcher" \
    "  --files N          Logical unique files (default: 100000)" \
    "  --directories N    Virtual buckets (default: 4096)" \
    "  --layers N         Overlapping mod layers (default: 8)" \
    "  --iterations N     First/repeated passes (default: 3)" \
    "  --threads N        Mixed-workload threads (default: 8)" \
    "  --seed N           Reproducible access seed" \
    "  --allow-missing-profile  Permit a non-instrumented reference DLL" \
    "  --shared-context   Enable the experimental recursive shared context lock" \
    "  --exact-query-exhaustion  Skip a completed exact backing query"
}

while (($# > 0)); do
  case "$1" in
  --runtime) runtime_dir="${2:?missing runtime directory}"; shift 2 ;;
  --corpus) corpus_dir="${2:?missing corpus directory}"; shift 2 ;;
  --results) results_root="${2:?missing results directory}"; shift 2 ;;
  --compat-data) compat_data="${2:?missing compatibility-data directory}"; shift 2 ;;
  --proton) proton="${2:?missing Proton path}"; shift 2 ;;
  --files) files="${2:?missing file count}"; shift 2 ;;
  --directories) directories="${2:?missing directory count}"; shift 2 ;;
  --layers) layers="${2:?missing layer count}"; shift 2 ;;
  --iterations) iterations="${2:?missing iteration count}"; shift 2 ;;
  --threads) threads="${2:?missing thread count}"; shift 2 ;;
  --seed) seed="${2:?missing seed}"; shift 2 ;;
  --allow-missing-profile) require_profile=false; shift ;;
  --shared-context) shared_context=true; shift ;;
  --exact-query-exhaustion) exact_query_exhaustion=true; shift ;;
  --help|-h) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
  esac
done

if [[ -z "${runtime_dir}" ]]; then
  usage >&2
  exit 2
fi
for value in "${files}" "${directories}" "${layers}" "${iterations}" \
  "${threads}" "${seed}"; do
  if [[ ! "${value}" =~ ^[0-9]+$ ]] || [[ "${value}" == 0 ]]; then
    printf 'Counts and seed must be positive decimal integers.\n' >&2
    exit 2
  fi
done

runtime_dir="$(readlink -f "${runtime_dir}")"
benchmark_exe="${runtime_dir}/usvfs_benchmark_x64.exe"
benchmark_dll="${runtime_dir}/usvfs_x64.dll"
for required in "${benchmark_exe}" "${benchmark_dll}" "${proton}"; do
  if [[ ! -f "${required}" ]]; then
    printf 'Required file is missing: %s\n' "${required}" >&2
    exit 1
  fi
done
if [[ ! -x "${proton}" ]]; then
  printf 'Proton launcher is not executable: %s\n' "${proton}" >&2
  exit 1
fi

mkdir -p "$(dirname "${corpus_dir}")" "${results_root}" "${compat_data}"
corpus_dir="$(readlink -m "${corpus_dir}")"
compat_data="$(readlink -m "${compat_data}")"
prefix_dir="${compat_data}/pfx"

proc_env_value()
{
  local pid="$1"
  local key="$2"
  local entry env_fd
  if ! exec 2>/dev/null {env_fd}<"/proc/${pid}/environ"; then
    return 1
  fi
  while IFS= read -r -d '' entry; do
    if [[ "${entry}" == "${key}="* ]]; then
      printf '%s\n' "${entry#*=}"
      exec {env_fd}<&-
      return 0
    fi
  done <&"${env_fd}"
  exec {env_fd}<&-
  return 1
}

prefix_pids()
{
  local proc_path pid candidate candidate_canonical prefix_canonical
  prefix_canonical="$(readlink -m "${prefix_dir}")"
  for proc_path in /proc/[0-9]*; do
    pid="${proc_path##*/}"
    candidate="$(proc_env_value "${pid}" WINEPREFIX || true)"
    [[ -n "${candidate}" ]] || continue
    candidate_canonical="$(readlink -m "${candidate}")"
    if [[ "${candidate_canonical}" == "${prefix_canonical}" ]]; then
      printf '%s\n' "${pid}"
    fi
  done
}

mapfile -t active_prefix_pids < <(prefix_pids)
if ((${#active_prefix_pids[@]} > 0)); then
  printf 'Dedicated benchmark prefix is already active: %s\n' \
    "${active_prefix_pids[*]}" >&2
  exit 1
fi

wine_path()
{
  local host_path="$1"
  printf 'Z:%s' "${host_path//\//\\}"
}

exact_mode=off
shared_mode=off
[[ "${exact_query_exhaustion}" == true ]] && exact_mode=on
[[ "${shared_context}" == true ]] && shared_mode=on
run_id="$(date -u +'%Y%m%dT%H%M%SZ')-files${files}-layers${layers}-threads${threads}-exact${exact_mode}-shared${shared_mode}"
result_dir="${results_root}/${run_id}"
mkdir -p "${result_dir}"
output="${result_dir}/workload.jsonl"
console_log="${result_dir}/console.log"

{
  printf 'run_id=%s\n' "${run_id}"
  printf 'utc_started=%s\n' "$(date -u --iso-8601=ns)"
  printf 'runtime_dir=%s\n' "${runtime_dir}"
  printf 'corpus_dir=%s\n' "${corpus_dir}"
  printf 'compat_data=%s\n' "${compat_data}"
  printf 'proton=%s\n' "${proton}"
  printf 'files=%s\n' "${files}"
  printf 'directories=%s\n' "${directories}"
  printf 'layers=%s\n' "${layers}"
  printf 'iterations=%s\n' "${iterations}"
  printf 'threads=%s\n' "${threads}"
  printf 'seed=%s\n' "${seed}"
  printf 'require_profile=%s\n' "${require_profile}"
  printf 'shared_context=%s\n' "${shared_context}"
  printf 'exact_query_exhaustion=%s\n' "${exact_query_exhaustion}"
  sha256sum "${benchmark_exe}" "${benchmark_dll}"
} >"${result_dir}/metadata.txt"

generate=()
if [[ ! -f "${corpus_dir}/.usvfs-benchmark-corpus" ]]; then
  generate=(--generate)
fi

printf 'Generated workload capture: %s\n' "${result_dir}"
printf 'Corpus: %s\n' "${corpus_dir}"
benchmark_environment=(FLUORINE_USVFS_PROFILE=1)
if [[ "${shared_context}" == true ]]; then
  benchmark_environment+=(FLUORINE_USVFS_SHARED_CONTEXT=1)
else
  benchmark_environment+=(FLUORINE_USVFS_SHARED_CONTEXT=0)
fi
if [[ "${exact_query_exhaustion}" == true ]]; then
  benchmark_environment+=(FLUORINE_USVFS_EXACT_QUERY_EXHAUSTION=1)
else
  benchmark_environment+=(FLUORINE_USVFS_EXACT_QUERY_EXHAUSTION=0)
fi
set +e
(
  env \
    "${benchmark_environment[@]}" \
    STEAM_COMPAT_DATA_PATH="${compat_data}" \
    STEAM_COMPAT_CLIENT_INSTALL_PATH="${steam_root}" \
    STEAM_COMPAT_APP_ID=489830 \
    SteamAppId=489830 \
    SteamGameId=489830 \
    nice -n 10 ionice -c 3 \
    "${proton}" waitforexitandrun "$(wine_path "${benchmark_exe}")" \
      "${generate[@]}" \
      --root "$(wine_path "${corpus_dir}")" \
      --output "$(wine_path "${output}")" \
      --files "${files}" \
      --directories "${directories}" \
      --layers "${layers}" \
      --iterations "${iterations}" \
      --threads "${threads}" \
      --seed "${seed}" \
      > >(tee "${console_log}") 2>&1
) &
benchmark_pid=$!
heartbeat_started=${SECONDS}
while kill -0 "${benchmark_pid}" 2>/dev/null; do
  for ((heartbeat_wait = 0; heartbeat_wait < 15; ++heartbeat_wait)); do
    sleep 1
    if ! kill -0 "${benchmark_pid}" 2>/dev/null; then
      break 2
    fi
  done
  printf 'Benchmark still running: %s seconds elapsed\n' \
    "$((SECONDS - heartbeat_started))" | tee -a "${console_log}"
done
wait "${benchmark_pid}"
benchmark_exit=$?
set -e

printf 'benchmark_exit=%s\n' "${benchmark_exit}" \
  >>"${result_dir}/metadata.txt"
printf 'utc_finished=%s\n' "$(date -u --iso-8601=ns)" \
  >>"${result_dir}/metadata.txt"

valid=true
if ((benchmark_exit != 0)); then
  printf 'Benchmark executable returned %s.\n' "${benchmark_exit}" >&2
  valid=false
fi
expected_warm_iterations=$((iterations - 1))
if [[ ! -s "${output}" ]] ||
   ! jq -e -s \
     --argjson files "${files}" \
     --argjson directories "${directories}" \
     --argjson layers "${layers}" \
     --argjson iterations "${iterations}" \
     --argjson threads "${threads}" \
     --argjson seed "${seed}" \
     --argjson warm "${expected_warm_iterations}" '
       def opcount($name): map(select(.operation? == $name)) | length;
       (map(select(
         .kind? == "configuration" and
         .files == $files and
         .directories == $directories and
         .layers == $layers and
         .iterations == $iterations and
         .threads == $threads and
         .seed == $seed)) | length) == 1 and
       all(.[]; ((.errors // 0) == 0)) and
       opcount("mapping_build") == 1 and
       opcount("attributes_existing_cold") == 1 and
       opcount("attributes_missing_cold") == 1 and
       opcount("open_existing_cold") == 1 and
       opcount("find_exact_cold") == 1 and
       opcount("enumerate_directories_cold") == 1 and
       opcount("attributes_existing_warm") == $warm and
       opcount("attributes_missing_warm") == $warm and
       opcount("open_existing_warm") == $warm and
       opcount("find_exact_warm") == $warm and
       opcount("enumerate_directories_warm") == $warm and
       opcount("mixed_concurrent") == 1
     ' "${output}" >/dev/null; then
  printf '%s\n' \
    'JSON results are missing, malformed, incomplete or contain correctness errors.' >&2
  valid=false
fi

profile_log="${output}.usvfs.log"
if [[ -s "${profile_log}" ]]; then
  "$(dirname "${BASH_SOURCE[0]}")/summarize-profile.py" "${profile_log}" \
    >"${result_dir}/profile-summary.tsv" || valid=false
elif [[ "${require_profile}" == false ]]; then
  printf 'USVFS profiler log absent as permitted for reference DLL.\n' \
    >"${result_dir}/profile-summary.tsv"
else
  printf 'USVFS profiler log is missing: %s\n' "${profile_log}" >&2
  valid=false
fi

mapfile -t initial_remaining_prefix_pids < <(prefix_pids)
printf 'cleanup_initial_prefix_pids=%s\n' \
  "${initial_remaining_prefix_pids[*]:-}" >>"${result_dir}/metadata.txt"

remaining_prefix_pids=("${initial_remaining_prefix_pids[@]}")
cleanup_attempts=0
while ((${#remaining_prefix_pids[@]} > 0)) && \
      ((cleanup_attempts < cleanup_grace_attempts)); do
  sleep "${cleanup_grace_interval}"
  ((cleanup_attempts += 1))
  mapfile -t remaining_prefix_pids < <(prefix_pids)
done
printf 'cleanup_wait_attempts=%s\n' "${cleanup_attempts}" \
  >>"${result_dir}/metadata.txt"
printf 'cleanup_final_prefix_pids=%s\n' \
  "${remaining_prefix_pids[*]:-}" >>"${result_dir}/metadata.txt"

if ((${#remaining_prefix_pids[@]} > 0)); then
  printf 'Dedicated benchmark prefix still has processes: %s\n' \
    "${remaining_prefix_pids[*]}" >&2
  valid=false
fi

if [[ "${valid}" != true ]]; then
  exit 1
fi
printf 'Generated workload passed: %s\n' "${result_dir}"
