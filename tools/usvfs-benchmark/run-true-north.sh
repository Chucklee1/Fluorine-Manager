#!/usr/bin/env bash
set -euo pipefail

# Repeatable warm-cache True North smoke/benchmark run for Fluorine's USVFS
# backend. See docs/usvfs-optimization-lab.md before changing this procedure.

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
portable_dir="${repo_root}/build/fluorine-manager"
portable_launcher="${portable_dir}/fluorine-manager"
installed_dir="/home/luke/.local/share/fluorine/bin"
instance_dir="/home/luke/Games/Skyrim Modded"
instance_logs="${instance_dir}/logs"
prefix_dir="/home/luke/.local/share/fluorine/Prefix/pfx"
game_launcher="/home/luke/Desktop/Skyrim-Modded-Play-True-North.sh"
run_seconds=90
deploy=true
launch_game=true
label="baseline"
preserve_focus=false
allow_concurrent_load=false
profile_usvfs=false
shared_context=false
exact_query_exhaustion=false

usage()
{
  printf '%s\n' \
    "Usage: $0 [--label NAME] [--duration SECONDS] [--preserve-focus]" \
    "          [--allow-concurrent-load] [--profile-usvfs] [--shared-context]" \
    "          [--exact-query-exhaustion]" \
    "          [--deploy-only|--run-only]" \
    "" \
    "The script deploys the existing build/fluorine-manager bundle. It does" \
    "not invoke build.sh itself. Build and test the selected candidate first."
}

while (($# > 0)); do
  case "$1" in
  --label)
    label="${2:?missing label}"
    shift 2
    ;;
  --duration)
    run_seconds="${2:?missing duration}"
    shift 2
    ;;
  --deploy-only)
    launch_game=false
    shift
    ;;
  --run-only)
    deploy=false
    shift
    ;;
  --preserve-focus)
    preserve_focus=true
    shift
    ;;
  --allow-concurrent-load)
    allow_concurrent_load=true
    shift
    ;;
  --profile-usvfs)
    profile_usvfs=true
    shift
    ;;
  --shared-context)
    shared_context=true
    shift
    ;;
  --exact-query-exhaustion)
    exact_query_exhaustion=true
    shift
    ;;
  --help|-h)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
  esac
done

if [[ ! "${run_seconds}" =~ ^[0-9]+$ ]] || ((run_seconds < 15)); then
  printf 'Duration must be an integer of at least 15 seconds.\n' >&2
  exit 2
fi

for required in "${portable_launcher}" "${game_launcher}"; do
  if [[ ! -x "${required}" ]]; then
    printf 'Required executable is missing: %s\n' "${required}" >&2
    exit 1
  fi
done

mkdir -p "${instance_logs}/benchmarks"
run_id="$(date -u +'%Y%m%dT%H%M%SZ')-${label//[^A-Za-z0-9_.-]/_}"
result_dir="${instance_logs}/benchmarks/${run_id}"
mkdir -p "${result_dir}"
runner_log="${result_dir}/runner.log"
marker="${result_dir}/started.marker"
: >"${marker}"

exec > >(tee -a "${runner_log}") 2>&1

prefix_canonical="$(readlink -f "${prefix_dir}")"

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

proc_comm()
{
  local pid="$1"
  local comm_fd value
  if ! exec 2>/dev/null {comm_fd}<"/proc/${pid}/comm"; then
    return 1
  fi
  IFS= read -r value <&"${comm_fd}" || true
  exec {comm_fd}<&-
  printf '%s\n' "${value}"
}

prefix_pids()
{
  local proc_path pid candidate candidate_canonical
  for proc_path in /proc/[0-9]*; do
    pid="${proc_path##*/}"
    candidate="$(proc_env_value "${pid}" WINEPREFIX || true)"
    [[ -n "${candidate}" ]] || continue
    candidate_canonical="$(readlink -f "${candidate}" 2>/dev/null || true)"
    if [[ "${candidate_canonical}" == "${prefix_canonical}" ]]; then
      printf '%s\n' "${pid}"
    fi
  done
}

prefix_pids_matching()
{
  local expression="$1"
  local pid comm cmdline
  while IFS= read -r pid; do
    [[ -r "/proc/${pid}/comm" ]] || continue
    comm="$(proc_comm "${pid}" || true)"
    cmdline="$(tr '\0' ' ' <"/proc/${pid}/cmdline" 2>/dev/null || true)"
    if [[ "${comm}" =~ ${expression} || "${cmdline}" =~ ${expression} ]]; then
      printf '%s\n' "${pid}"
    fi
  done < <(prefix_pids)
}

other_prefixes_active()
{
  local proc_path pid candidate candidate_canonical
  for proc_path in /proc/[0-9]*; do
    pid="${proc_path##*/}"
    candidate="$(proc_env_value "${pid}" WINEPREFIX || true)"
    [[ -n "${candidate}" ]] || continue
    candidate_canonical="$(readlink -f "${candidate}" 2>/dev/null || true)"
    if [[ -n "${candidate_canonical}" &&
          "${candidate_canonical}" != "${prefix_canonical}" ]]; then
      printf '%s\t%s\t%s\n' "${pid}" \
        "$(proc_comm "${pid}" || true)" "${candidate_canonical}"
    fi
  done
}

process_snapshot()
{
  local destination="$1"
  ps -eo pid,ppid,pgid,sid,etimes,pcpu,pmem,comm,args --sort=pid \
    >"${destination}"
}

visible_wait()
{
  local duration="$1"
  local label="$2"
  local elapsed=0 step
  while ((elapsed < duration)); do
    step=15
    if ((duration - elapsed < step)); then
      step=$((duration - elapsed))
    fi
    sleep "${step}"
    elapsed=$((elapsed + step))
    printf '%s: %s/%s seconds elapsed\n' "${label}" "${elapsed}" "${duration}"
  done
}

capture_root_builder_state()
{
  local manifest="${instance_dir}/rootbuilder/manifest.json"
  local destination backup hash
  root_builder_manifest_captured=false
  root_builder_deployed_count=0
  : >"${result_dir}/rootbuilder-running.tsv"

  if [[ ! -f "${manifest}" ]]; then
    return 0
  fi
  if ! jq -e '.deployed | type == "array"' "${manifest}" >/dev/null; then
    printf 'Root Builder manifest is not valid JSON: %s\n' "${manifest}" >&2
    return 1
  fi

  cp -- "${manifest}" "${result_dir}/rootbuilder-manifest-running.json"
  root_builder_manifest_captured=true
  root_builder_deployed_count="$(jq '.deployed | length' "${manifest}")"

  while IFS= read -r destination; do
    if [[ -f "${destination}" ]]; then
      hash="$(sha256sum "${destination}" | cut -d' ' -f1)"
      printf 'DEPLOYED\t%s\t%s\n' "${destination}" "${hash}" \
        >>"${result_dir}/rootbuilder-running.tsv"
    else
      printf 'MISSING_DEPLOYED\t%s\t-\n' "${destination}" \
        >>"${result_dir}/rootbuilder-running.tsv"
    fi
  done < <(jq -r '.deployed[]' "${manifest}")

  while IFS=$'\t' read -r destination backup; do
    if [[ -f "${backup}" ]]; then
      hash="$(sha256sum "${backup}" | cut -d' ' -f1)"
      printf 'BACKUP\t%s\t%s\t%s\n' "${destination}" "${backup}" "${hash}" \
        >>"${result_dir}/rootbuilder-running.tsv"
    else
      printf 'MISSING_BACKUP\t%s\t%s\t-\n' "${destination}" "${backup}" \
        >>"${result_dir}/rootbuilder-running.tsv"
    fi
  done < <(jq -r '.backups | to_entries[] | [.key, .value] | @tsv' "${manifest}")
}

validate_root_builder_cleanup()
{
  local manifest="${instance_dir}/rootbuilder/manifest.json"
  local kind destination backup expected actual
  local restored=true

  [[ "${root_builder_manifest_captured:-false}" == true ]] || return 1
  [[ "${root_builder_deployed_count:-0}" =~ ^[0-9]+$ ]] || return 1
  ((root_builder_deployed_count > 0)) || return 1
  [[ ! -e "${manifest}" ]] || restored=false

  while IFS=$'\t' read -r kind destination backup expected; do
    case "${kind}" in
    DEPLOYED)
      if ! jq -e --arg path "${destination}" \
          '.backups | has($path)' \
          "${result_dir}/rootbuilder-manifest-running.json" >/dev/null; then
        [[ ! -e "${destination}" ]] || restored=false
      fi
      ;;
    MISSING_DEPLOYED|MISSING_BACKUP)
      restored=false
      ;;
    BACKUP)
      if [[ ! -f "${destination}" ]]; then
        restored=false
      else
        actual="$(sha256sum "${destination}" | cut -d' ' -f1)"
        [[ "${actual}" == "${expected}" ]] || restored=false
      fi
      [[ ! -e "${backup}" ]] || restored=false
      ;;
    esac
  done <"${result_dir}/rootbuilder-running.tsv"

  [[ "${restored}" == true ]]
}

installed_organizer_pids()
{
  pgrep -f '^/home/luke/.local/share/fluorine/bin/ModOrganizer-core'
}

setup_focus_containment()
{
  if [[ "${preserve_focus}" != true ]]; then
    return 0
  fi
  if ! command -v gamescope >/dev/null 2>&1; then
    printf '%s\n' '--preserve-focus requires gamescope.' >&2
    return 1
  fi
  printf '%s\n' \
    'Focus preservation: using Gamescope headless backend (no host window).'
}

terminate_exact_pids()
{
  local signal="$1"
  shift
  local pid
  for pid in "$@"; do
    [[ "${pid}" =~ ^[0-9]+$ ]] || continue
    if [[ -d "/proc/${pid}" ]]; then
      kill "-${signal}" "${pid}" 2>/dev/null || true
    fi
  done
}

wait_for_exit()
{
  local seconds="$1"
  shift
  local deadline=$((SECONDS + seconds))
  local pid alive
  while ((SECONDS < deadline)); do
    alive=false
    for pid in "$@"; do
      if [[ -d "/proc/${pid}" ]]; then
        alive=true
        break
      fi
    done
    if [[ "${alive}" == false ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

cleanup_run()
{
  local launcher_pid="${1:-}"
  local helper_deadline launcher_pgid
  local -a target_pids scoped_pids helper_pids

  # Stop the game first and leave the USVFS controller alive. It must observe
  # child removal, flush child_drain/helper_total, disconnect and return before
  # Fluorine performs post-run synchronization.
  mapfile -t target_pids < <(
    prefix_pids_matching '([Ss]kyrim[Ss][Ee]\.exe|skse64_loader\.exe)'
  )
  if ((${#target_pids[@]} > 0)); then
    printf 'Sending SIGTERM to Skyrim/SKSE processes: %s\n' "${target_pids[*]}"
    terminate_exact_pids TERM "${target_pids[@]}"
    if ! wait_for_exit 10 "${target_pids[@]}"; then
      printf 'Escalating Skyrim/SKSE survivors to SIGKILL.\n'
      terminate_exact_pids KILL "${target_pids[@]}"
    fi
  fi

  helper_deadline=$((SECONDS + 30))
  while ((SECONDS < helper_deadline)); do
    mapfile -t helper_pids < <(
      prefix_pids_matching 'fluorine-usvfs-launcher\.exe|fluorine-usvfs'
    )
    ((${#helper_pids[@]} == 0)) && break
    sleep 1
  done

  # Give the queued afterRun callback time to sync the prefix after the helper
  # exits, then stop prefix service processes that Proton may keep idle.
  sleep 2
  mapfile -t scoped_pids < <(prefix_pids)

  if ((${#scoped_pids[@]} > 0)); then
    printf 'Sending SIGTERM to remaining exact-prefix processes: %s\n' \
      "${scoped_pids[*]}"
    terminate_exact_pids TERM "${scoped_pids[@]}"
    if ! wait_for_exit 10 "${scoped_pids[@]}"; then
      mapfile -t scoped_pids < <(prefix_pids)
      if ((${#scoped_pids[@]} > 0)); then
        printf 'Escalating exact-prefix survivors to SIGKILL: %s\n' \
          "${scoped_pids[*]}"
        terminate_exact_pids KILL "${scoped_pids[@]}"
      fi
    fi
  fi

  if [[ "${launcher_pid}" =~ ^[0-9]+$ && -d "/proc/${launcher_pid}" ]]; then
    launcher_pgid="$(ps -o pgid= -p "${launcher_pid}" | tr -d ' ')"
    if [[ "${launcher_pgid}" =~ ^[0-9]+$ ]]; then
      kill -TERM -- "-${launcher_pgid}" 2>/dev/null || true
      sleep 2
      kill -KILL -- "-${launcher_pgid}" 2>/dev/null || true
    else
      kill -TERM "${launcher_pid}" 2>/dev/null || true
    fi
  fi
}

cleanup_all()
{
  cleanup_run "${game_root_pid:-}"
}

trap cleanup_all EXIT INT TERM

printf 'Run ID: %s\n' "${run_id}"
printf 'Result directory: %s\n' "${result_dir}"
printf 'Warm-cache dwell after Skyrim detection: %s seconds\n' "${run_seconds}"

other_active="$(other_prefixes_active || true)"
if [[ -n "${other_active}" ]]; then
  printf '%s\n' "${other_active}" >"${result_dir}/concurrent-prefixes.txt"
  if [[ "${allow_concurrent_load}" != true ]]; then
    printf 'Refusing benchmark because other Wine prefixes are active:\n%s\n' \
      "${other_active}" >&2
    exit 1
  fi
  printf '%s\n' \
    'Concurrent Wine/Proton load accepted; timing result is exploratory.'
  printf '%s\n' "${other_active}"
fi

mapfile -t stale_prefix_pids < <(prefix_pids)
if ((${#stale_prefix_pids[@]} > 0)); then
  printf 'Refusing benchmark because the Fluorine prefix is already active: %s\n' \
    "${stale_prefix_pids[*]}" >&2
  exit 1
fi

mapfile -t stale_organizer_pids < <(installed_organizer_pids)
if ((${#stale_organizer_pids[@]} > 0)); then
  printf 'Refusing benchmark because Fluorine is already active: %s\n' \
    "${stale_organizer_pids[*]}" >&2
  exit 1
fi

setup_focus_containment

process_snapshot "${result_dir}/processes-before.txt"

{
  printf 'run_id=%s\n' "${run_id}"
  printf 'utc_started=%s\n' "$(date -u --iso-8601=ns)"
  printf 'repo_commit=%s\n' "$(git -C "${repo_root}" rev-parse HEAD)"
  printf 'repo_branch=%s\n' "$(git -C "${repo_root}" branch --show-current)"
  printf 'kernel=%s\n' "$(uname -srvm)"
  printf 'duration_seconds=%s\n' "${run_seconds}"
  printf 'preserve_focus=%s\n' "${preserve_focus}"
  printf 'allow_concurrent_load=%s\n' "${allow_concurrent_load}"
  printf 'profile_usvfs=%s\n' "${profile_usvfs}"
  printf 'shared_context=%s\n' "${shared_context}"
  printf 'exact_query_exhaustion=%s\n' "${exact_query_exhaustion}"
  if [[ "${allow_concurrent_load}" == true ]]; then
    printf 'timing_eligibility=EXPLORATORY_CONCURRENT_LOAD\n'
  else
    printf 'timing_eligibility=CONTROLLED\n'
  fi
  printf 'logical_cpu_count=%s\n' "$(nproc)"
  printf 'load_average=%s\n' "$(</proc/loadavg)"
  sha256sum "${portable_dir}/ModOrganizer-core" \
    "${portable_dir}/usvfs/fluorine-usvfs-launcher.exe" \
    "${portable_dir}/usvfs/usvfs_x64.dll" \
    "${portable_dir}/usvfs/usvfs_x86.dll"
  if [[ -f "${portable_dir}/fluorine-bundle-version.txt" ]]; then
    sha256sum "${portable_dir}/fluorine-bundle-version.txt"
  fi
  if [[ -f "${portable_dir}/usvfs/fluorine-candidate-build.txt" ]]; then
    printf '[candidate]\n'
    sed 's/^/candidate_/' \
      "${portable_dir}/usvfs/fluorine-candidate-build.txt"
  fi
} >"${result_dir}/metadata.txt"
git -C "${repo_root}" status --short >"${result_dir}/git-status.txt"

if [[ "${deploy}" == true ]]; then
  portable_candidate_metadata="${portable_dir}/usvfs/fluorine-candidate-build.txt"
  installed_candidate_metadata="${installed_dir}/usvfs/fluorine-candidate-build.txt"
  if [[ ! -f "${portable_candidate_metadata}" &&
        -f "${installed_candidate_metadata}" ]]; then
    # This is lab provenance, not an application-owned/user file. The portable
    # updater deliberately preserves unknown installed files, so a reference
    # restore must remove this one exact marker explicitly.
    rm -- "${installed_candidate_metadata}"
    printf 'Removed stale installed USVFS candidate provenance marker.\n'
  fi
  printf 'Deploying portable Fluorine bundle through its launcher...\n'
  if [[ "${preserve_focus}" == true ]]; then
    setsid nice -n 10 ionice -c 3 gamescope \
      --backend headless -W 1280 -H 720 -- \
      "${portable_launcher}" >"${result_dir}/deploy.log" 2>&1 &
  else
    setsid "${portable_launcher}" >"${result_dir}/deploy.log" 2>&1 &
  fi
  deploy_pid=$!
  sleep 5
  deploy_pgid="$(ps -o pgid= -p "${deploy_pid}" | tr -d ' ' || true)"
  if [[ "${deploy_pgid}" =~ ^[0-9]+$ ]]; then
    kill -TERM -- "-${deploy_pgid}" 2>/dev/null || true
    sleep 2
    kill -KILL -- "-${deploy_pgid}" 2>/dev/null || true
  fi
  wait "${deploy_pid}" 2>/dev/null || true
  mapfile -t deployed_organizer_pids < <(installed_organizer_pids)
  if ((${#deployed_organizer_pids[@]} > 0)); then
    printf 'Stopping detached deployed organizer process: %s\n' \
      "${deployed_organizer_pids[*]}"
    terminate_exact_pids TERM "${deployed_organizer_pids[@]}"
    if ! wait_for_exit 5 "${deployed_organizer_pids[@]}"; then
      terminate_exact_pids KILL "${deployed_organizer_pids[@]}"
    fi
  fi
  if installed_organizer_pids \
      >"${result_dir}/unexpected-organizer-pids.txt"; then
    printf 'Installed ModOrganizer-core survived deployment shutdown.\n' >&2
    exit 1
  fi

  sha256sum "${installed_dir}/ModOrganizer-core" \
    "${installed_dir}/usvfs/fluorine-usvfs-launcher.exe" \
    "${installed_dir}/usvfs/usvfs_x64.dll" \
    "${installed_dir}/usvfs/usvfs_x86.dll" \
    >"${result_dir}/installed-hashes.txt"
  if [[ -f "${installed_dir}/fluorine-bundle-version.txt" ]]; then
    sha256sum "${installed_dir}/fluorine-bundle-version.txt" \
      >>"${result_dir}/installed-hashes.txt"
  fi
  if [[ -f "${installed_candidate_metadata}" ]]; then
    sha256sum "${installed_candidate_metadata}" \
      >>"${result_dir}/installed-hashes.txt"
  fi
  if ! cmp -s "${portable_dir}/ModOrganizer-core" \
      "${installed_dir}/ModOrganizer-core" ||
     ! cmp -s "${portable_dir}/usvfs/fluorine-usvfs-launcher.exe" \
      "${installed_dir}/usvfs/fluorine-usvfs-launcher.exe" ||
     ! cmp -s "${portable_dir}/usvfs/usvfs_x64.dll" \
      "${installed_dir}/usvfs/usvfs_x64.dll" ||
     ! cmp -s "${portable_dir}/usvfs/usvfs_x86.dll" \
      "${installed_dir}/usvfs/usvfs_x86.dll"; then
    printf 'Installed bundle does not match the selected portable build.\n' >&2
    exit 1
  fi
  if [[ -f "${portable_dir}/fluorine-bundle-version.txt" ]]; then
    installed_bundle_version="${installed_dir}/fluorine-bundle-version.txt"
    expected_marker="bundle:$(sha256sum \
      "${portable_dir}/fluorine-bundle-version.txt" | cut -d' ' -f1)"
    if ! cmp -s "${portable_dir}/fluorine-bundle-version.txt" \
        "${installed_bundle_version}" ||
       [[ ! -f "${installed_dir}/.version" ]] ||
       [[ "$(<"${installed_dir}/.version")" != "${expected_marker}" ]]; then
      printf 'Installed bundle identity does not match the portable build.\n' >&2
      exit 1
    fi
  fi
  if [[ -f "${portable_candidate_metadata}" ]]; then
    if ! cmp -s "${portable_candidate_metadata}" \
        "${installed_candidate_metadata}"; then
      printf 'Installed candidate provenance does not match portable build.\n' >&2
      exit 1
    fi
  elif [[ -e "${installed_candidate_metadata}" ]]; then
    printf 'Installed candidate provenance survived reference restore.\n' >&2
    exit 1
  fi
  printf 'Deployment verified.\n'
fi

if [[ "${launch_game}" != true ]]; then
  trap - EXIT INT TERM
  printf 'Deploy-only run complete.\n'
  exit 0
fi

touch "${marker}"
printf 'Launching True North...\n'
if [[ "${profile_usvfs}" == true ]]; then
  export FLUORINE_USVFS_PROFILE=1
  printf '%s\n' 'USVFS process-local profiling enabled for this run.'
fi
if [[ "${shared_context}" == true ]]; then
  export FLUORINE_USVFS_SHARED_CONTEXT=1
  printf '%s\n' 'Experimental recursive shared context lock enabled for this run.'
else
  export FLUORINE_USVFS_SHARED_CONTEXT=0
fi
if [[ "${exact_query_exhaustion}" == true ]]; then
  export FLUORINE_USVFS_EXACT_QUERY_EXHAUSTION=1
  printf '%s\n' 'Experimental exact-query exhaustion shortcut enabled for this run.'
else
  export FLUORINE_USVFS_EXACT_QUERY_EXHAUSTION=0
fi
if [[ "${preserve_focus}" == true ]]; then
  setsid nice -n 10 ionice -c 3 gamescope \
    --backend headless -W 1920 -H 1080 -r 60 -- \
    "${game_launcher}" >"${result_dir}/game-launch.log" 2>&1 &
else
  setsid "${game_launcher}" >"${result_dir}/game-launch.log" 2>&1 &
fi
game_root_pid=$!
printf '%s\n' "${game_root_pid}" >"${result_dir}/game-root-pid.txt"

skyrim_pid=""
deadline=$((SECONDS + 90))
while ((SECONDS < deadline)); do
  while IFS= read -r pid; do
    [[ -r "/proc/${pid}/comm" ]] || continue
    comm="$(proc_comm "${pid}" || true)"
    cmdline="$(tr '\0' ' ' <"/proc/${pid}/cmdline" 2>/dev/null || true)"
    if [[ "${comm,,}" == skyrimse.exe* || "${cmdline,,}" == *skyrimse.exe* ]]; then
      skyrim_pid="${pid}"
      break 2
    fi
  done < <(prefix_pids)
  sleep 1
done

if [[ -z "${skyrim_pid}" ]]; then
  printf 'SkyrimSE.exe was not observed within 90 seconds.\n' >&2
  process_snapshot "${result_dir}/processes-launch-failed.txt"
  exit 1
fi

printf 'Observed SkyrimSE.exe as PID %s.\n' "${skyrim_pid}"
printf 'skyrim_pid=%s\n' "${skyrim_pid}" >>"${result_dir}/metadata.txt"
printf 'skyrim_observed_utc=%s\n' "$(date -u --iso-8601=ns)" \
  >>"${result_dir}/metadata.txt"

if [[ "${preserve_focus}" == true ]]; then
  deadline=$((SECONDS + 90))
  while ((SECONDS < deadline)); do
    if rg -q 'pApplicationName: SkyrimSE\.exe' \
        "${result_dir}/game-launch.log" 2>/dev/null &&
       rg -q 'Made gamescope surface for xid:' \
        "${result_dir}/game-launch.log" 2>/dev/null; then
      break
    fi
    if [[ ! -d "/proc/${skyrim_pid}" ]]; then
      printf 'Skyrim exited before creating a Gamescope render surface.\n' >&2
      exit 1
    fi
    sleep 1
  done
  if ! rg -q 'pApplicationName: SkyrimSE\.exe' \
      "${result_dir}/game-launch.log" 2>/dev/null ||
     ! rg -q 'Made gamescope surface for xid:' \
      "${result_dir}/game-launch.log" 2>/dev/null; then
    printf 'Skyrim did not create a Gamescope render surface within 90 seconds.\n' >&2
    exit 1
  fi
  printf 'Observed Skyrim DXVK initialization and Gamescope render surface.\n'
  printf 'graphics_surface_observed_utc=%s\n' "$(date -u --iso-8601=ns)" \
    >>"${result_dir}/metadata.txt"
fi

printf 'Beginning fixed dwell.\n'
process_snapshot "${result_dir}/processes-running.txt"
capture_root_builder_state

visible_wait "${run_seconds}" 'True North fixed dwell'
printf 'Fixed dwell complete; cleaning the exact Fluorine prefix.\n'
cleanup_run "${game_root_pid}"
game_root_pid=""

deadline=$((SECONDS + 30))
usvfs_log=""
while ((SECONDS < deadline)); do
  usvfs_log="$(find "${instance_logs}" -maxdepth 1 -type f \
    -name 'usvfs-*.log' -newer "${marker}" -print | sort | tail -n 1)"
  if [[ -n "${usvfs_log}" ]] && rg -q 'phase=helper_total' "${usvfs_log}"; then
    break
  fi
  sleep 1
done

interface_log="$(find "${instance_logs}" -maxdepth 1 -type f \
  -name 'mo_interface_*.log' -newer "${marker}" -print | sort | tail -n 1)"

if [[ -n "${usvfs_log}" ]]; then
  printf 'usvfs_log=%s\n' "${usvfs_log}" >>"${result_dir}/metadata.txt"
  sha256sum "${usvfs_log}" >"${result_dir}/usvfs-log.sha256"
  rg '^\[benchmark\]' "${usvfs_log}" >"${result_dir}/benchmark.txt" || true
  rg '\[profile\]' "${usvfs_log}" >"${result_dir}/profile.txt" || true
  rg -n -i 'failed|error|warn|STATUS_|c000000f|inithooks|Process registered' \
    "${usvfs_log}" >"${result_dir}/usvfs-diagnostics.txt" || true
else
  printf 'No new USVFS log was found.\n' >&2
fi

if [[ -n "${interface_log}" ]]; then
  printf 'interface_log=%s\n' "${interface_log}" >>"${result_dir}/metadata.txt"
  sha256sum "${interface_log}" >"${result_dir}/interface-log.sha256"
  rg -n 'beforeRun: using|tracking game process|INI sync|syncPluginsBack|failed|error|warn' \
    "${interface_log}" >"${result_dir}/interface-timeline.txt" || true
  before_run_utc="$(sed -nE \
    's/^[0-9]+:\[([^]]+) [A-Z]\] beforeRun: using.*/\1/p' \
    "${result_dir}/interface-timeline.txt" | head -n 1)"
  if [[ -n "${before_run_utc}" ]]; then
    printf 'before_run_utc=%s\n' "${before_run_utc}" \
      >>"${result_dir}/metadata.txt"
  fi
fi

find "${instance_dir}/overwrite/SKSE/Plugins" -maxdepth 1 -type f -name '*.log' \
  -newer "${marker}" -printf '%TY-%Tm-%TdT%TH:%TM:%TS\t%s\t%p\n' \
  | sort >"${result_dir}/skse-logs.txt" || true
find "${instance_dir}" -type f \( -iname '*crash*.log' -o -iname '*.dmp' \) \
  -newer "${marker}" -printf '%TY-%Tm-%TdT%TH:%TM:%TS\t%s\t%p\n' \
  | sort >"${result_dir}/new-crash-files.txt" || true
process_snapshot "${result_dir}/processes-after.txt"

validity_file="${result_dir}/validity.txt"
valid=true
{
  printf 'format=1\n'
  if [[ -n "${usvfs_log}" ]] &&
     rg -q 'phase=helper_total .*exit_code=0' "${usvfs_log}"; then
    printf 'PASS helper_total\n'
  else
    printf 'FAIL helper_total\n'
    valid=false
  fi

  if [[ -n "${usvfs_log}" ]] &&
     rg -q 'phase=child_drain .*observed_child=1' "${usvfs_log}"; then
    printf 'PASS child_registration_and_drain\n'
  else
    printf 'FAIL child_registration_and_drain\n'
    valid=false
  fi

  successful_hooks=0
  registered_processes=0
  dbvo_misses=0
  if [[ -n "${usvfs_log}" ]]; then
    successful_hooks="$(rg -c 'inithooks in process [0-9]+ successful' \
      "${usvfs_log}" || true)"
    registered_processes="$(rg -c 'Process registered in shared process list' \
      "${usvfs_log}" || true)"
    dbvo_misses="$(rg -c 'c000000f' "${usvfs_log}" || true)"
  fi
  printf 'metric successful_hook_initializations=%s\n' "${successful_hooks:-0}"
  printf 'metric registered_processes=%s\n' "${registered_processes:-0}"
  printf 'metric dbvo_c000000f=%s\n' "${dbvo_misses:-0}"
  if (( ${successful_hooks:-0} >= 2 && ${registered_processes:-0} >= 2 )); then
    printf 'PASS skse_and_skyrim_hooks\n'
  else
    printf 'FAIL skse_and_skyrim_hooks\n'
    valid=false
  fi

  if [[ "${preserve_focus}" != true ]]; then
    printf 'SKIP gamescope_render_surface preserve_focus=false\n'
  elif rg -q 'pApplicationName: SkyrimSE\.exe' \
      "${result_dir}/game-launch.log" 2>/dev/null &&
       rg -q 'Made gamescope surface for xid:' \
        "${result_dir}/game-launch.log" 2>/dev/null; then
    printf 'PASS gamescope_render_surface\n'
  else
    printf 'FAIL gamescope_render_surface\n'
    valid=false
  fi

  request_path=""
  if [[ -n "${interface_log}" ]]; then
    request_path="$(rg -o "request='[^']+'" "${interface_log}" | head -n 1 |
      cut -d"'" -f2 || true)"
  fi
  if [[ -n "${request_path}" && ! -e "${request_path}" ]]; then
    printf 'PASS request_removed path=%s\n' "${request_path}"
  else
    printf 'FAIL request_removed path=%s\n' "${request_path:-<unknown>}"
    valid=false
  fi

  if [[ -n "${interface_log}" ]] && rg -q 'INI sync target:' "${interface_log}" &&
     rg -q 'syncPluginsBack:' "${interface_log}"; then
    printf 'PASS post_run_sync_observed\n'
  else
    printf 'FAIL post_run_sync_observed\n'
    valid=false
  fi

  if [[ ! -s "${result_dir}/new-crash-files.txt" ]]; then
    printf 'PASS no_new_crash_files\n'
  else
    printf 'FAIL no_new_crash_files\n'
    valid=false
  fi

  printf 'metric root_builder_deployed=%s\n' \
    "${root_builder_deployed_count:-0}"
  if validate_root_builder_cleanup; then
    printf 'PASS root_builder_deployed_and_restored\n'
  else
    printf 'FAIL root_builder_deployed_and_restored\n'
    valid=false
  fi

  if [[ "${profile_usvfs}" == true ]]; then
    if [[ -s "${result_dir}/profile.txt" ]] &&
       rg -q 'kind=context_lock .*acquisitions=[1-9][0-9]*' \
         "${result_dir}/profile.txt" &&
       rg -q 'kind=directory_query .*total=[1-9][0-9]*' \
         "${result_dir}/profile.txt" &&
       rg -q 'kind=directory_work .*parent_opens=[1-9][0-9]*' \
         "${result_dir}/profile.txt"; then
      printf 'PASS usvfs_profile_summary\n'
    else
      printf 'FAIL usvfs_profile_summary\n'
      valid=false
    fi
  fi

  mapfile -t final_prefix_pids < <(prefix_pids)
  if ((${#final_prefix_pids[@]} == 0)); then
    printf 'PASS no_exact_prefix_processes_remaining\n'
  else
    printf 'FAIL no_exact_prefix_processes_remaining pids=%s\n' \
      "${final_prefix_pids[*]}"
    valid=false
  fi

  printf 'result=%s\n' "$([[ "${valid}" == true ]] && printf PASS || printf FAIL)"
} >"${validity_file}"

printf 'utc_finished=%s\n' "$(date -u --iso-8601=ns)" \
  >>"${result_dir}/metadata.txt"
trap - EXIT INT TERM
if [[ "${valid}" != true ]]; then
  printf 'Benchmark capture failed one or more validity gates: %s\n' \
    "${validity_file}" >&2
  exit 1
fi
printf 'Benchmark capture complete: %s\n' "${result_dir}"
