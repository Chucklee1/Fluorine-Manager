# USVFS benchmark tools

This directory contains the reproducible Fluorine/True North benchmark harness.
The experiment design, candidate ledger and all decisions live in
[`docs/usvfs-optimization-lab.md`](../../docs/usvfs-optimization-lab.md); this
file is the operator runbook.

## Required order

Run from the Fluorine repository root:

```bash
./build.sh test
./build.sh
```

For the exact committed head of the sibling `../usvfs` checkout, the integrated
candidate path performs both commands and the Windows-artifact checks in one
invocation:

```bash
./build.sh usvfs [GITHUB_ACTIONS_RUN_ID]
```

The run ID is optional; when omitted, the script selects the newest Build USVFS
run whose head SHA exactly matches the checkout. It refuses a dirty checkout,
a commit absent from all `origin` branches and tags, a non-green or partial
x86/x64 Debug/Release
matrix, an architecture mismatch, or a workflow for another commit. It then
downloads the merged Release artifact, packages both architectures through the
normal Podman/Docker build, embeds commit/workflow/hash provenance, and
byte-compares the packaged DLLs. This is the preferred packaging path for a
fork candidate; it does not replace the generated workload, True North, Root
Builder, or final reference-restore gates.

For an experimental USVFS x64 DLL, stage it only after that full build:

```bash
tools/usvfs-benchmark/stage-usvfs-candidate.sh \
  /absolute/path/to/usvfs_x64.dll \
  FULL_40_CHARACTER_SOURCE_COMMIT \
  https://github.com/OWNER/usvfs/actions/runs/RUN_ID
```

The staging helper validates that the file is an x64 PE DLL, records source and
workflow provenance, byte-checks the staged file, and recomputes Fluorine's
content-derived bundle identity. It does not replace the required build.

## True North run

```bash
tools/usvfs-benchmark/run-true-north.sh \
  --label descriptive-candidate-name \
  --duration 90 \
  --preserve-focus \
  --profile-usvfs
```

The harness implements the manual procedure used during development: launch
the portable manager for five seconds so it updates the stable installation,
stop that exact manager process group, run
`/home/luke/Desktop/Skyrim-Modded-Play-True-North.sh`, wait 90 seconds after
`SkyrimSE.exe` is observed, then perform prefix-scoped cleanup. Use
`--deploy-only` to verify an installation without starting the game and
`--run-only` only when the desired portable payload is already deployed.

`--preserve-focus` runs both the temporary manager deployment and the game
inside Gamescope's headless backend. It creates no host window, so KWin has
nothing that can take focus or move the user to another workspace. The
contained workload runs at lower CPU and idle I/O priority to reduce impact on
interactive applications.

`--profile-usvfs` exports `FLUORINE_USVFS_PROFILE=1` only to the benchmark
launch tree. A profiling-capable candidate DLL then records atomic counters for
context-lock waits/holds and directory-query shapes and emits compact
`[profile]` summaries periodically and during normal process teardown. Periodic
records are cumulative and sequence-numbered because controlled game
termination does not guarantee DLL teardown; the summarizer retains the latest
snapshot per process and category. The harness saves those records as
`profile.txt` and fails the run if nonzero lock and directory summaries are
missing. The reference Omni DLL safely ignores the variable.

By default, another active Wine/Proton prefix still blocks a run. An explicitly
approved background correctness run may use `--allow-concurrent-load`; the
harness records those prefixes, process CPU/memory snapshots, CPU count and
load average, and marks the capture `EXPLORATORY_CONCURRENT_LOAD`. Such a run
can detect correctness regressions but cannot support a performance claim.

Before launch it refuses to continue if the configured Fluorine prefix is
active. Cleanup records exact PIDs, sends `SIGTERM` first, waits for graceful
exit and escalates only recorded survivors. It never uses broad `pkill wine` or
`killall wine` commands.

Each capture is written under:

```text
/home/luke/Games/Skyrim Modded/logs/benchmarks/<UTC>-<label>/
```

Important files are:

- `metadata.txt`: repository/build/DLL identity and candidate provenance;
- `benchmark.txt`: structured helper phase timings;
- `interface-timeline.txt`: immutable Fluorine timing anchors;
- `usvfs-diagnostics.txt`: captured hook/helper diagnostics;
- `profile.txt`: opt-in process-local USVFS profiler summaries;
- `rootbuilder-manifest-running.json` and `rootbuilder-running.tsv`: Root
  Builder files/backups observed while Skyrim was running;
- `validity.txt`: machine-readable pass/fail gates;
- `processes-before.txt`, `processes-running.txt`, and `processes-after.txt`:
  process-scope evidence;
- `new-crash-files.txt`: crash artifacts created during the run.

The ephemeral binary request remains under `/tmp` only until the Wine helper
parses it. This is IPC containing mapping paths, not a benchmark record. The
harness requires its removal; durable measurements and diagnostics are kept in
the instance log directories above.

The True North validity gates also require a nonempty Root Builder deployment,
verify every deployed path while the game is running, then require the manifest
and unbacked files to disappear and every backed destination to match its
pre-launch SHA-256 after cleanup. This catches the class of failure where the
game happens to launch only because a script extender was copied permanently
into the physical game directory.

## Generated loose-file workload

The USVFS fork also builds an opt-in `usvfs_benchmark_{x64,x86}.exe` under its
test output. It generates a seeded corpus of 100K–1M logical loose files across
configurable directories and mod layers, including priority collisions, then
launches its worker through USVFS. It records mapping construction, existing
and missing probes, opens, exact searches, directory walks and concurrent mixed
lookups as JSON Lines while checking every expected result. Full invocation and
corpus safety rules are in the fork's `test/usvfs_benchmark/README.md`.

After downloading a green GitHub artifact, place
`usvfs_benchmark_x64.exe` and its matching `usvfs_x64.dll` in one directory,
then run it through an isolated Proton prefix with:

```bash
tools/usvfs-benchmark/run-generated-workload.sh \
  --runtime /absolute/path/to/runtime \
  --files 100000 --directories 4096 --layers 8 \
  --iterations 3 --threads 8
```

The wrapper refuses an already-active benchmark prefix, never uses a game
prefix, generates a corpus only when its marker is absent, records exact binary
hashes and parameters, validates every JSON result has zero correctness errors,
summarizes the profiler log, and fails if any process remains in that exact
prefix. After Proton returns it records the initial prefix PID set and allows
up to ten seconds for those exact-prefix service processes to exit naturally,
recording the number of 250 ms polling intervals and the final PID set. It
never kills a broad Wine/Proton process set. It does not delete the corpus;
repeated candidate runs reuse identical loose files.

While the benchmark is active, the wrapper prints a heartbeat every 15 seconds.
Validation requires the exact configuration record and complete cold, warm,
mapping and mixed-operation phase counts, so closing an otherwise silent Proton
worker cannot be mistaken for a successful partial run even if Proton returns
zero. The True North fixed dwell prints the same 15-second progress cadence.

For an A run using Omni's non-instrumented reference DLL, add
`--allow-missing-profile`. This relaxes only the profiler-file gate; JSON
correctness, process cleanup and every workload result remain mandatory. Do not
use the option for an instrumented candidate.

`--shared-context` enables the experimental recursive reader/writer context
lock only for that launch tree. `--exact-query-exhaustion` independently
enables the exact-name directory-query shortcut. Both variables are explicitly
set to `0` when their option is absent, so a shell environment cannot
accidentally contaminate a control run.

Use the same artifact and corpus for the four-way isolation matrix:

```bash
# Both experiments off (control)
tools/usvfs-benchmark/run-generated-workload.sh --runtime "$RUNTIME"

# Exact-query shortcut only
tools/usvfs-benchmark/run-generated-workload.sh --runtime "$RUNTIME" \
  --exact-query-exhaustion

# Shared-context lock only
tools/usvfs-benchmark/run-generated-workload.sh --runtime "$RUNTIME" \
  --shared-context

# Both experiments on (interaction check)
tools/usvfs-benchmark/run-generated-workload.sh --runtime "$RUNTIME" \
  --exact-query-exhaustion --shared-context
```

The exact-query option is off by default after the reported mixed-season asset
regression. Synthetic correctness is necessary but cannot clear that report:
compare the same save, camera position, weather/season state, profile and load
order with the control and then each option separately.

Use that executable for repeatable microbenchmarks after the game profiler
identifies a dominant request shape. Continue using alternating True North runs
as the end-to-end acceptance test; a synthetic improvement alone is not enough
to promote a DLL.

Summarize one or more profiler captures with:

```bash
tools/usvfs-benchmark/summarize-profile.py \
  "/home/luke/Games/Skyrim Modded/logs/benchmarks/<run>/profile.txt"
```

The output converts QPC ticks to milliseconds per process, calculates lock
contention percentage, preserves directory request-shape/information-class
totals, separates parent-open, regular-query and virtual-query time, and ranks
lock call sites by cumulative wait time. Instrumented builds also report
bounded observation-only redirection-tree and negative-attribute cache repeat
rates. Those observers never serve a result or change filesystem behavior.

## Validity and summaries

A game capture passes only when the helper completes, a child is registered and
drained, both SKSE and Skyrim hooks initialize, the request disappears,
post-run INI/plugin sync occurs, no new crash appears and no process remains in
the exact prefix. Mapping count and known DBVO miss counts must also be compared
with the reference.

With `--preserve-focus`, the harness additionally waits for Skyrim's DXVK
application initialization and a created Gamescope render surface before
starting its fixed dwell. This proves more than process creation, but it still
cannot certify host-desktop workspace placement, visible presentation, or
keyboard/input readiness; a normal visible launch remains mandatory after a
candidate changes synchronization or directory-enumeration behavior.

Summarize one or more captures with:

```bash
tools/usvfs-benchmark/summarize-runs.sh \
  /absolute/path/to/capture-a \
  /absolute/path/to/capture-b
```

Only `PASS` rows are timing evidence. Use at least three alternating warm runs
per payload for a performance claim and report median, range and median
absolute deviation. `beforeRun`-to-Skyrim, ActorLimitFix and
MainMenuRandomizer are log-derived proxies; none alone proves that the rendered
main menu is interactive.

## Restoring a known payload

`./build.sh` always recreates the pinned short-name payload from fork
prerelease `v0.5.7.2-wine-shortname.3`. It downloads archive SHA-256
`91e24d6971e8f9f084d60d2f372a5c6d816587a83f2683737c22e643eb40c133`
and packages x64 DLL SHA-256
`56728c79492bd6e8bc713cd1b79ec15498ef14b2dae4e1323e50d24d8ce8dd4a`
plus x86 DLL SHA-256
`4157835670e2f919bd3eac93b4819a548fc218e6dd6ee0116e36d97a54255a54`.
Run a deploy-only capture after that build to restore and verify the pinned
payload. The former Omni x64 reference
`7454334c1ea246a68ff8da492b5d63dae8cd2f1298f2d7105c920b5f593352aa`
remains the independently human-validated build of the same source fix.

The combined candidate from USVFS commit `03f9204`, x64 SHA-256
`bcb68274bbe49955c604ab76bb776a3c4c2835a64d468305aec5339644d0dcae`,
is retained only for regression diagnosis after a mixed-season asset report.
Do not restore it as the default. Use a gated artifact and the four-way matrix
above, then require a same-save visual A/B before accepting the exact-query
shortcut.

The current diagnostic artifact is commit `687e890`, workflow
`30731473176`, x64 SHA-256
`73a5e8b68543fb3656161df1448a67022ef0bbf6bebe105bf482135d95b8319d`.
It contains independent exact-query and shared-context gates, both default off.
It passed the four-way generated workload and headless True North matrix, but
its combined mode failed the same-save winter-scene check and must not be used
with both gates enabled.

The first combined-interaction repair was commit `d6e1186`, workflow
`30735531508`, x64 SHA-256
`e1c0019714cccc02db45233dd3460ccae216fb3dfbc7234a92357fce2cbba35f`.
It passed the full CI matrix, all four 100K generated-workload modes, and the
both-on headless True North/Root Builder gate, but a normal visible launch
reached main-menu plugin initialization without producing a usable window.
That artifact is rejected: its unconditional process-wide search mutex can
serialize unrelated handles and permits a context/search lock-order inversion.
Commit `12b5e3f`, workflow `30760697935`, x64 SHA-256
`3744a748fadbb60e55c8bc8c9d0ce20d21c2f6c8dcc95b7a38d78271d62b989c`,
replaces it with reference-counted per-handle records. All GitHub build/test
jobs, the 1K smoke, all four 100K modes, warmed control/both-on repeats, and the
strengthened headless True North/Root Builder gate passed. The latter requires
both DXVK initialization and a Gamescope render surface before its dwell.
Human same-save testing then reproduced the mixed/incorrect winter textures
with both gates enabled. The user later identified a mod under active
development as the likely source of that asset mixture, so the visual result
is confounded and no longer rejects `12b5e3f`. Leave both experimental gates
off until a clean fixed-mod-state A/B is captured.

That restored diagnostic artifact is not Omni's short-name-only DLL. Besides
the short-name patch, it retains the visually cleared disabled-logging cleanup,
benaphore correctness repair, wide-filename cleanup, non-serving profiling,
and the two disabled experimental implementations. Omni's narrower reference
payload has SHA-256
`7454334c1ea246a68ff8da492b5d63dae8cd2f1298f2d7105c920b5f593352aa`.

In either direction the harness removes only its own stale installed
candidate-provenance marker, verifies candidate metadata byte-for-byte when
present, and fails if the portable/installed core, helper, DLLs, bundle
identity or marker state differs.

Cross-process shared-mapping candidate `c7a72e7`, workflow `30769540485`, x64
SHA-256 `afd9ba432afd303dc9cc6cdb8ab45ac4e6065f40e85e34f86ef5757dd77e1d1b`
passed the full Windows matrix, local shared-mode test, all four 100K modes and
headless True North/Root Builder. Its visible mixed-assets observation is now
confounded by the same in-development mod and is not rejection evidence. Keep
the candidate experimental/off pending a clean visual A/B and performance
justification.

Automatic packaging may fetch only an exact commit's fully green matrix, as
`./build.sh usvfs` does. The normal Fluorine build may download only the
explicit tag and archive digest pinned in `docker/Dockerfile`; it must never
resolve `latest` or a branch artifact. Automatic deployment or promotion must remain a
separate, explicit allowlist/manifest change after synthetic, headless and
human visible gates pass. Never make the installed payload follow a branch's
latest artifact merely because CI is green. A normal reference build now
explicitly resets CMake's cached runtime path to `/opt/fluorine-usvfs`; hash
verification remains mandatory because provenance removal alone cannot prove
that candidate DLL bytes were replaced.
