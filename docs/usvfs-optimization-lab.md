# USVFS optimization and Skyrim benchmark lab

This document is the source of truth for Fluorine's USVFS performance work.
Update it before changing the test procedure and after every completed
experiment. Raw game logs remain in the instance log directory; this document
records build identities, comparable metrics, correctness observations and the
decision for each candidate.

The concise command/safety runbook for the scripts is
[`tools/usvfs-benchmark/README.md`](../tools/usvfs-benchmark/README.md).

## Objectives

1. Preserve USVFS behavior while reducing Wine/Proton launch time for large
   modlists.
2. Produce repeatable A/B evidence rather than relying on projected percentage
   improvements.
3. Keep experimental changes isolated so a regression can be attributed to one
   optimization.
4. Never promote a result based only on a microbenchmark. A candidate must pass
   unit/conformance tests and the True North launch test.

The linked ChatGPT share was fetched directly with `wget` on 2026-08-01 and
decoded from its embedded React Router hydration payload (342 conversation
nodes, 219 text messages). Its audit explicitly describes itself as static
source review rather than profiler evidence, and its percentage table calls the
numbers engineering estimates that should be treated as target ranges. The
share and screenshot are therefore hypothesis inputs only; decisions below use
source inspection, CI/conformance results and captured A/B runs. The downloaded
page is not committed because it is a generated 1.2 MiB third-party document.

The working application is Fluorine on branch `feat/usvfs-backend`. The pinned
USVFS source is release tag `v0.5.7.2-wine-snapshot.2` from
`SulfurNitride/usvfs`, which peels to release commit
`98bc3edb4aa0df2ea68bb59a7ba0be68b55f6e56`. It adds Wine short-name commit
`644eebfe7e454ead93774fcda95fa9b3ddfddb09`, resolved bulk import commit
`f5dea417eb8e5f0c654c9d9c5f50bad2a49ff0e9`, and release-context compatibility
at the tagged head over upstream `v0.5.7.2`.

The persistent source checkout is `/var/home/luke/Documents/usvfs`. Its
`perf/fluorine-lab` base begins at that exact commit; the current checked-out
topic is `safety/shared-context-mapping-lock`, based on final publication-
observer commit `95fd4e0`. It uses
`https://github.com/SulfurNitride/usvfs.git` as `origin`. Candidate work stays
on isolated topic branches or commits so it can be reviewed and cherry-picked
without mixing experimental changes into the Wine short-name reference.

## Known reference build

- USVFS version: `0.5.7.2-wine-snapshot.2`.
- Release commit: `98bc3edb4aa0df2ea68bb59a7ba0be68b55f6e56`.
- Full Windows matrix:
  [`31065013884`](https://github.com/SulfurNitride/usvfs/actions/runs/31065013884).
- Release archive SHA-256:
  `e6c38a64a2c6b23cc07411180a8958e026c362e3662f1df6542a72f4adcb6ecf`.
- x64 DLL SHA-256:
  `2902ec5ac898da59a522b48bc8b6d705758e3b103ef0b7397763688d5a47ceb7`.
- x86 DLL SHA-256:
  `bafb128bbe05084b929b5fa7ea37dac1448477e1a26d86938994f71d554c1ea7`.
- Prior independently human-validated x64 reference: Omni's build of the same
  short-name source change, SHA-256
  `7454334c1ea246a68ff8da492b5d63dae8cd2f1298f2d7105c920b5f593352aa`.
- Game shortcut:
  `/home/luke/Desktop/Skyrim-Modded-Play-True-North.sh`.
- Instance:
  `/home/luke/Games/Skyrim Modded`.
- Prefix:
  `/home/luke/.local/share/fluorine/Prefix/pfx`.
- Proton: `/home/luke/.local/share/Steam/compatibilitytools.d/Proton-GE Latest`.
- Steam app ID: `489830`.
- Profile observed in the reference run: `Default`, 922 enabled plugins.

The first compact reference log installed 1,144 mappings and attached a tree
with 405,417 nodes. Its mapping installation took 3,150 ms. That single number
is a useful smoke-test reference, not yet a statistically valid baseline.

## Current pinned runtime

The portable build now pins the fork-built Wine snapshot release above. Its
x64 SHA-256 is
`2902ec5ac898da59a522b48bc8b6d705758e3b103ef0b7397763688d5a47ceb7`;
the x86 DLL SHA-256 is
`bafb128bbe05084b929b5fa7ea37dac1448477e1a26d86938994f71d554c1ea7`.
The earlier capture `20260805T205106Z-shortname-release-836b2d9-headless`
validated the short-name parent release. The new database/bulk path still
requires its own True North/Root Builder and same-save visible A/B.

The independently gated diagnostic artifact from USVFS commit
`687e89006868618f81c5018692742f4cdcdf845d`, GitHub Actions run `30731473176`,
x64 SHA-256
`73a5e8b68543fb3656161df1448a67022ef0bbf6bebe105bf482135d95b8319d`, is retained
only as a prior experimental artifact. It is not currently selected or
installed.

The former selected combination from USVFS commit `03f9204`, x64 SHA-256
`bcb68274bbe49955c604ab76bb776a3c4c2835a64d468305aec5339644d0dcae`,
is withdrawn from visual acceptance. It remains a diagnostic artifact only.
Its exact-query exhaustion shortcut is the first visual-bisect suspect because
it changes directory-enumeration continuation behavior; shared context was off
and cache observers did not serve results.

USVFS branch `integration/wine-safe-candidates` now independently gates the
exact-query shortcut with
`FLUORINE_USVFS_EXACT_QUERY_EXHAUSTION`. Fluorine also exposes independent
per-instance INI/UI gates for that shortcut and the shared-context lock. Both
default off. A newly gated DLL must pass the full GitHub matrix and four-way
off/exact/shared/both workload matrix before staging, and the exact option
cannot be accepted until a human compares the same save and scene with it off
and on.

## Safety boundaries

- Before a run, enumerate matching Fluorine, Skyrim, SKSE, Proton and Wine
  processes. Do not start if another unrelated Wine/Proton session is active.
- Use `--preserve-focus` for background correctness testing. It uses
  Gamescope's headless backend rather than a KWin virtual desktop. An explicitly
  approved run alongside another Wine/Proton game must also use
  `--allow-concurrent-load`; the capture is marked exploratory and is never
  eligible for a performance claim.
- Record exact PIDs and parent/child relationships for the run.
- Cleanup is limited to the launched shortcut's process tree, Skyrim/SKSE and
  USVFS processes using the configured Fluorine prefix, and the `wineserver`
  whose `WINEPREFIX` canonicalizes to that exact prefix.
- Never use unscoped `pkill wine`, `killall wine`, or broad process-name kills.
- Send `SIGTERM`, wait for graceful shutdown, and use `SIGKILL` only for exact
  surviving PIDs from the recorded run.
- Do not delete the prefix, instance, saves, overwrite directory or shader
  caches during benchmarking.
- Do not drop the kernel page cache: that requires elevated global mutation and
  would disturb the desktop. These are warm-cache comparisons unless explicitly
  documented otherwise.

## Build and deployment procedure

For every candidate:

1. Record the Fluorine commit/worktree status, USVFS source commit, compiler
   configuration and SHA-256 of both DLLs.
2. Run `./build.sh test` from
   `/var/home/luke/Documents/Fluorine`.
3. Run `./build.sh` from the same directory. Do not substitute a direct CMake
   or Ninja packaging command.
4. Start
   `/var/home/luke/Documents/Fluorine/build/fluorine-manager/fluorine-manager`.
   Its wrapper overlays the new manifested bundle into
   `/home/luke/.local/share/fluorine/bin`.
5. Allow five seconds for synchronization and startup, then terminate only that
   exact Fluorine process tree. Confirm no `ModOrganizer-core` process remains.
6. Verify the installed `ModOrganizer-core`, helper and DLL hashes against the
   just-built portable bundle before launching the game.

For a committed fork head with a green Windows matrix, `./build.sh usvfs
[RUN_ID]` is the integrated form of steps 1-3. It runs Fluorine's test mode,
requires the exact USVFS commit in an `origin` branch or tag, verifies all
x86/x64 Debug/Release
build and test jobs, downloads the merged Release artifact, packages both DLL
architectures through the normal container build, writes exact
commit/workflow/SHA-256 provenance, and byte-compares the portable result. It
does not install the candidate or waive steps 4-6, generated-workload checks,
True North/Root Builder acceptance, or the final reference restore.

USVFS itself is a Visual Studio/vcpkg project. Custom DLLs are built with the
fork's Windows CI matrix, not with an unverified MinGW substitution. The matrix
builds x86 and x64 in Debug and Release configurations, runs the upstream test
executables, and publishes architecture-specific artifacts. A CI artifact is
not copied into Fluorine until its exact source commit, workflow run URL and
SHA-256 are recorded. Debug and x86 artifacts are retained for conformance;
True North uses the x64 Release DLL.

Fluorine's GitHub workflow also invokes `./build.sh test` followed by
`./build.sh`; it no longer calls `docker/build-inner.sh` directly. A published
builder image is only a Docker layer-cache seed. The current checkout's
`docker/Dockerfile` remains authoritative, and the same post-build x64/x86
hash gates used locally run before CI packages or uploads anything. This keeps
the local and GitHub entry points identical and prevents a stale builder image
from silently selecting a different USVFS payload.

After the normal `./build.sh`, stage an accepted x64 Release artifact with:

```bash
tools/usvfs-benchmark/stage-usvfs-candidate.sh \
  /absolute/path/to/usvfs_x64.dll \
  FULL_40_CHARACTER_SOURCE_COMMIT \
  https://github.com/OWNER/usvfs/actions/runs/RUN_ID
```

The staging helper rejects a non-x64 PE image, copies only
`build/fluorine-manager/usvfs/usvfs_x64.dll`, byte-compares the result, and
writes `fluorine-candidate-build.txt` with the commit, workflow and SHA-256.
The x86 DLL remains the known upstream reference unless the candidate affects
32-bit targets being tested. Staging always follows, never replaces, the
required Fluorine `./build.sh`.

## True North launch procedure

1. Snapshot the newest interface, USVFS and relevant SKSE log filenames and
   mtimes.
2. Start `/home/luke/Desktop/Skyrim-Modded-Play-True-North.sh` and record its
   root PID and monotonic start time.
   For background correctness testing, pass `--preserve-focus` to expose no
   focusable host window. Headless captures are comparable only with headless
   captures. Never use a run made while another game or substantial workload
   was active for a performance claim.
3. Confirm the new interface log selects the Wine/Proton USVFS backend.
4. Confirm the helper log reports successful injection into both
   `skse64_loader.exe` and `SkyrimSE.exe`.
5. Leave the game untouched. Wait 90 seconds after `SkyrimSE.exe` is observed;
   this gives the list time to reach and settle at its menu without mixing
   player-controlled save loading into the startup measurement.
6. Send `SIGTERM` to the exact `SkyrimSE.exe` PID(s) from this run. Wait up to
   ten seconds. Then terminate exact surviving helper/Proton/shortcut PIDs and
   the exact-prefix `wineserver` if necessary. Escalate surviving recorded PIDs
   to `SIGKILL` only after the grace period.
7. Wait for the helper's `child_drain` and `helper_total` records and for
   Fluorine's post-run sync. If the helper cannot finish, mark the run invalid
   and preserve its logs.
8. Copy the structured metrics and correctness observations into the results
   ledger below. Raw logs are identified by absolute path and SHA-256 rather
   than copied into Git.

The harness writes `validity.txt` beside every capture and exits nonzero unless
it sees a successful helper total, a registered child drain, at least two hook
initializations and process registrations, request-file removal, post-run INI
and plugin sync, no new crash file, and no surviving process belonging to the
exact prefix. It also records the DBVO `c000000f` count. These automated checks
are necessary but do not replace manual comparison of mappings, errors and
interactive menu behavior.

For profiler runs, add `--profile-usvfs`. The harness exports the profiling
gate only to the launch tree, captures shutdown summaries as `profile.txt`, and
requires nonzero context-lock and directory-query totals. It also snapshots the
live Root Builder manifest and file/backup hashes after Skyrim appears. Cleanup
must remove every unbacked deployment and the manifest, restore every backup
byte-for-byte, and leave no missing deployed path in the running snapshot.

Profiler build `8ee1d57` showed that controlled Unix-side game termination does
not run the injected DLL's teardown, so only the naturally exiting SKSE loader
emitted its final counters. The profiler now also emits a cumulative snapshot
every 10,000 directory queries. Snapshots are sequence-numbered and the summary
tool selects only the latest sequence per process/category/source. This keeps
the log bounded while preserving the long-running game's evidence before the
fixed-dwell termination; it does not log paths or individual calls.

## Comparable metrics

The USVFS log's structured records are authoritative for:

- `fluorine_prepare`;
- `request_serialize` and `request_parse`;
- `dll_load` and `vfs_create`;
- `mapping_install` and mapping count;
- `target_inject`;
- `target_lifetime` (the short-lived script-extender loader in this list);
- `child_drain` (mostly the intentional test dwell time);
- `helper_total` (setup plus intentional dwell, not a startup metric).

Additional timestamps:

- Fluorine launch preparation begins at the interface log's USVFS `beforeRun`
  record.
- `ActorLimitFix.log` or the first timestamped SKSE plugin record is the engine
  bootstrap proxy.
- `MainMenuRandomizer.log` is a later plugin-initialization proxy, but it does
  not prove that the rendered menu is interactive.
- A human-observed interactive main menu is the final end-to-end measure. It
  cannot be inferred reliably from `child_drain` or `helper_total`.

For each comparable phase, use at least three valid warm runs per build in
alternating order (`A B A B A B`). Report all observations, median, minimum,
maximum and median absolute deviation. Do not report percentages from a single
run. A run is invalid if it builds shaders, changes the mod/profile/plugin set,
loads a save, receives user input, crashes, or fails a correctness gate.

`tools/usvfs-benchmark/summarize-runs.sh RESULT_DIR...` emits a TSV containing
the DLL hash, mapping phases, `beforeRun`-to-Skyrim/ActorLimitFix/menu-proxy
times and DBVO miss count. Only rows whose `validity` is `PASS` are eligible for
statistics; older captures are labelled `LEGACY` even if manually reviewed.
The first valid-but-pre-validator reference row produces 6,439.301 ms to
Skyrim observation, 5,843.630 ms to ActorLimitFix and 12,660.160 ms to the menu
plugin proxy, matching the manual calculation.

## Correctness gates

Every candidate must satisfy all of these before it can be kept:

- All Fluorine automated tests pass.
- The Wine helper self-test loads the packaged x64 DLL.
- Mapping count and resolved VFS node count are stable unless the instance
  itself changed.
- Injection and hook initialization succeed in both SKSE and Skyrim.
- No new USVFS warning/error class appears relative to baseline.
- Existing DBVO `STATUS_NO_SUCH_FILE` observations are counted separately; an
  increase is a regression.
- SKSE plugins initialize without a new crash dump.
- Dynamic writes still land in `overwrite`, including Preloader cell-index
  temporary files.
- The request file is removed after parsing.
- `INI sync` and `syncPluginsBack` occur only after `child_drain` and
  `helper_total`, never after the short-lived SKSE loader exits.
- A second launch cannot overlap an active USVFS-backed game through premature
  post-run completion.

## Candidate order and experiment gates

### Autonomous workstream charter (2026-08-01)

The user authorized a continuing autonomous pass over the complete proposal
set, including architectural experiments rather than only one-line cleanups.
The goal is to finish as many candidates as can be made correctness-safe, not
to force nine result-changing patches into the runtime. Each row has its own
commit and evidence before any combined build is made:

| Workstream | Current stage | Required next evidence |
| --- | --- | --- |
| Wine 8.3 aliases | implemented/reference | Retain Wine gate and known artifact |
| Disabled call logging | implemented/neutral timing | Retain correctness cleanup; no claimed percentage |
| Hash duplicate tracking | implemented/low value | Synthetic category timing before reconsideration |
| Wide/path conversions | one safe site implemented | Per-call-site conversion counts before broader representation changes |
| Exact-query exhaustion | implemented/mixed small signal | Profiler count plus synthetic exact-search comparison |
| Recursive context lock | shared experiment measured; combined mode rejected | Stable tree-view lifetime/rebinding tests before any new serving path |
| Packed directory records | test-first | Differential ABI matrix, then isolated serving candidate |
| Exact-path cache | observation-first | Hit rate, bounded memory, shared mutation generation |
| Negative cache | observation-first | Hit rate plus hooked/native invalidation proof |
| Precomputed listings | design/test-first | Request-shape evidence, ABI replay, generation/invalidation model |

Every serving optimization is benchmarked against the Wine-short-name
reference and the validated safe combination. The generated 100K-file corpus
is the repeatable operation benchmark; True North remains the end-to-end and
Root Builder acceptance workload. A candidate can end in **accepted**,
**correct but neutral**, **rejected by measurement**, or **blocked by a named
correctness prerequisite**. The last outcome is a completed investigation,
not permission to bypass the prerequisite.

### Approved combined-candidate scope

The first integration candidate combines only changes that are narrow, already
covered independently and do not require new filesystem semantics:

1. Omni's Wine-only 8.3 short-name suppression;
2. the disabled `CallLogger` fast path;
3. the demonstrated `RecursiveBenaphore` initial-count repair; and
4. the Windows-native wide-filename cleanup in exact virtual queries.

This does not imply that the logging candidate produced a proven percentage
win. Its three-run deltas were all below one percent and therefore within the
observed launch variance. It is retained as a low-risk hot-path cleanup because
it avoids disabled string construction, passed the full matrix and game gates,
preserves Debug output, and corrects the previous per-template static flag's
inability to follow a runtime log-level change. The combined branch must still
pass the complete matrix as a new artifact; independently green patches do not
prove that their combination is green.

The exact-query exhaustion shortcut and hash duplicate tracker are excluded
from this first combination. The former has mixed end-to-end evidence and the
latter targets a category measured at only about 0.25 seconds. Packed records,
serving caches, precomputed listings and shared-reader locking remain separate
architectural experiments.

The later selected profiling combination at `03f9204` deliberately adds the
exact-query shortcut because the generated workload proves the intended call
removal with zero correctness failures. It also carries shared-reader locking
behind `FLUORINE_USVFS_SHARED_CONTEXT=1` and cache-potential instrumentation
behind `FLUORINE_USVFS_PROFILE=1`; neither changes default result semantics.
The hash duplicate tracker remains excluded because its measured category is
too small, while packed records and serving caches remain unimplemented behind
their named ABI and invalidation prerequisites.

### Persistent index and live-cache design

A persistent database is useful for avoiding repeated pre-launch scanning, but
it must not be queried synchronously for every hooked file operation. The hot
runtime representation should be an immutable in-memory or memory-mapped
snapshot constructed from the database and published with a shared monotonic
generation. Runtime creates, deletes, renames and winner changes belong in a
small generation-scoped delta until the next snapshot is published.

The persistent record can use layered validation:

- normalized source root, virtual path, provider priority and file type;
- device/file identity where the host exposes a stable one;
- size, nanosecond `mtime` and `ctime` plus directory metadata;
- a fast non-cryptographic fingerprint such as XXH3 for cheap change
  detection; and
- an optional BLAKE3 content digest when metadata changed, identities are
  unavailable, or a strict verification mode requests it.

On Linux, `ctime` is inode metadata-change time, not creation time. Metadata can
also be preserved or collide at filesystem timestamp granularity, while
content hashing every byte on every launch would erase much of the intended
speedup. Consequently metadata is a fast rejection/acceptance hint, not the
sole correctness proof. A content digest validates a file that was inspected;
it cannot discover an added, removed or renamed directory entry by itself.

Live invalidation therefore needs both sides of the boundary:

- every hooked USVFS create/delete/move/rename/mapping mutation advances the
  shared generation and updates or invalidates the affected delta;
- the native Fluorine controller watches physical source/overwrite directories
  for changes made by unhooked Linux processes and communicates generation
  invalidations to the Wine-side snapshot;
- watcher queue overflow, missed-root replacement, database/schema mismatch or
  an unrecognized mutation invalidates the affected subtree or entire snapshot
  and schedules a real rescan; and
- no negative physical-existence result is served unless the relevant watcher
  and generation coverage are demonstrably current.

The first cache milestone is observation-only: record prospective keys, hits,
misses, invalidation causes, memory requirement and generation churn while
always executing the reference lookup. Only virtual-path-to-copied-target
resolution—not raw shared-tree pointers, attributes or existence—is eligible
for the first serving experiment.

### Directory-query ABI conformance plan

`NtQueryDirectoryFile` and `NtQueryDirectoryFileEx` return chains of
variable-length records in a caller-owned byte buffer. Packing results is
eligible only after a differential probe exercises the reference implementation
and candidate with the same fixture and request sequence. The test must decode
records and also validate raw-buffer invariants; exact bytes are compared only
for stable fields because timestamps and file IDs may legitimately differ.

The matrix must cover:

- every directory information class supported by USVFS;
- x86 and x64, legacy and Ex APIs;
- zero, undersized, exact-boundary and multi-record buffer lengths around every
  fixed header, filename and alignment boundary;
- `ReturnSingleEntry`, restart flags, initial and continuation calls;
- exact names, `*`, `?`, DOS wildcards, case variants, Unicode, long names and
  names lacking optional 8.3 aliases;
- empty directories, one entry, multiple physical layers, collisions,
  file/directory conflicts and create targets;
- asynchronous/event/APC arguments where supported by the existing hook;
- mutation between continuation calls; and
- returned status, `IoStatusBlock.Information`, record count/order,
  `NextEntryOffset`, alignment, filename lengths, final zero offset, untouched
  guard bytes and absence of out-of-buffer writes.

Each packing change receives a focused regression case before it is added to
the implementation. The full matrix then runs in all four Debug/Release and
x86/x64 jobs, followed by tool-heavy Wine tests (xEdit and Pandora) and the
True North game gate. This is strong executable evidence, although no finite
suite proves compatibility with every undocumented application assumption.

### Audited implementation ladder (easiest to hardest)

This ordering is based on the `0.5.7.2` source, not the speculative percentage
ranges in the original screenshot.

Difficulty below rates reaching a production-safe result, including tests and
invalidation/concurrency proof, on a 1–10 scale. It is not merely the number of
changed lines:

| Proposal | Difficulty | Principal acceptance burden |
| --- | ---: | --- |
| Wine 8.3 suppression | 2 | Wine gating and legacy alias compatibility |
| Disabled call logging | 2 | Runtime level changes and identical Debug output |
| Hash duplicate tracking | 3 | Case equivalence, allocation behavior and ordering independence |
| Narrow wide/narrow conversion cleanup | 3 | Unicode and long physical filenames |
| Exact-query exhaustion shortcut | 4 | Continuation, restart and exact-name state |
| Demonstrated benaphore repair | 4 | Deterministic exclusion plus all architecture/configuration tests |
| Broader UTF/path reconstruction reduction | 6 | NT/DOS/UNC forms, Unicode case behavior and shared representation |
| Pack multiple redirected results | 8 | Directory buffer ABI and per-handle continuation matrix |
| Exact-path serving cache | 8 | Stable copied values and shared mutation generation |
| Recursive reader/writer context redesign | 9 | Mutable read-labelled paths, recursion and lock upgrade rules |
| Negative/missing-file serving cache | 9 | Hooked, cross-process and native-Linux invalidation |
| Precomputed directory listings | 10 | ABI, ordering, stateful enumeration and live invalidation together |

1. **Disabled call logging**: 38 `LOG_CALL()` sites currently construct a
   function-name string and invoke the Debug logger even while the configured
   level is Info. The parameter formatter is already mostly gated. The isolated
   fast path is small and has no filesystem semantics.
2. **Remove the exact-query exhaustion probe**: every virtual match is queried
   by its exact physical filename. After a successful result, current code
   retains the handle/match solely to issue another query that returns
   `STATUS_NO_MORE_FILES`, then closes and advances it. Consuming the exact
   match immediately is narrower and easier to prove than packing records and
   directly addresses the approximately 393,000 probes/6.35 seconds in the
   supplied profile.
3. **Duplicate tracker container**: `Searches::Info::foundFiles` is an ordered
   `std::set<std::wstring>`, but callers only insert, clear and test insertion
   success. A normalized `unordered_set` is mechanically simple, although the
   supplied profile found only about 0.25 seconds here and Omni already reported
   no useful end-to-end improvement.
4. **Remove a wide/narrow/wide filename round trip**: a `boost::filesystem::path`
   created from `std::wstring realPath` calls `.filename().string()` and then
   converts that presumed UTF-8 string back to wide. `.filename().wstring()` is
   both cheaper and more correct. Broader tree/path representation changes need
   instrumentation first.
5. **Pack results across virtual matches**: requires calculating each returned
   record's used/aligned size, restoring `NextEntryOffset` chains, respecting
   `ReturnSingleEntry`, buffer exhaustion and every supported information class.
   Existing tests cover basic enumeration but not this complete matrix, so the
   replay/conformance suite comes first.
6. **Observation-only cache simulations** (negative, exact-path, listings):
   counters can be safe, but serving results needs generation/invalidation for
   filesystem changes and mod-priority collisions.
7. **Context-lock restructuring**: hardest. `READ_CONTEXT()` paths mutate
   per-handle search maps, and re-entrant hooks require recursive acquisition.
   Measure contention before splitting state or designing a recursive
   reader/writer lock.

### 1. Wine 8.3 short-name suppression

Status: **reference behavior, already enabled for x64**.

Retain Omni's Wine-gated change. Use the official upstream DLL as the A build
only when quantifying the already-observed benefit; do not make it the normal
installed baseline.

### 2. Disabled logging overhead

Status: **approved for isolated implementation and A/B testing**.

Measure call counts and time spent constructing disabled `CallLogger` objects.
The candidate may bypass construction and destructor calls only when Debug is
disabled. Warning/error diagnostics must remain intact. Expected benefit is
small; reject it if below noise.

Planned isolated change: maintain an atomic Debug-enabled flag updated by
USVFS's existing `SetLogLevel` path. `CallLogger` will snapshot that flag and,
when Info or above is selected, avoid function-name parsing, string allocation,
the `spdlog::debug` call and parameter formatting. Debug mode must produce the
same call records as the reference. This avoids consulting the spdlog registry
inside every hooked call and also fixes the current per-template static flag,
which cannot follow a runtime log-level change. No warning/error logging is
touched. Build acceptance is all upstream x86/x64 Debug/Release tests; game
acceptance is the standard correctness gate followed by alternating A/B runs.

### 2a. Exact-query exhaustion probe

Status: **approved for isolated implementation after source-state audit**.

`addVirtualSearchResult()` issues an exact-filename
`NtQueryDirectoryFile` against one physical parent. On success the current
implementation returns the record but deliberately leaves both
`virtualMatches.front()` and `currentSearchHandle` in place. The next outer
directory-query call repeats the same exact query, receives
`STATUS_NO_MORE_FILES`, closes the handle and advances the queue. Because the
query is exact and one successful record has already consumed that search
handle, the second kernel/Wine call cannot yield another distinct result.

The isolated candidate adds one per-handle boolean recording that the current
exact virtual match has returned its record. On the next continuation it closes
and pops that completed match without querying it again, then continues to the
next match in the same existing outer loop. It must reset the flag on every
pop, restart-created `Searches::Info`, failed query and handle close. It does
not pack multiple successful records into one caller response, change ordering,
cache filesystem data, or alter `ReturnSingleEntry`/restart behavior.

Acceptance requires the complete upstream x86/x64 Debug/Release matrix plus
existing Nt and Win32 enumeration fixtures. Runtime acceptance requires the
standard True North gates and an instrumented count proving that successful
exact virtual queries no longer produce a corresponding physical exhaustion
call. If source tests expose any case where one exact query returns more than
one record, or where restart/continuation status differs, reject the shortcut.

### 3. Hash-based duplicate tracking

Status: **reproduce once, then normally reject**.

Replace only the per-search `std::set<std::wstring>` duplicate tracker with a
case-normalized hash set. Preserve case-insensitive identity and iterator
independence. Existing profiling attributed only about 0.25 seconds to this
work, so this experiment primarily validates the harness and the prior result.

### 4. UTF conversion and path reconstruction

Status: **one audited round trip approved; broader work remains instrumentation-first**.

Count conversions, input/output units and cumulative time by call site. Cache
or avoid only repeated conversions whose ownership and lifetime are clear.
Correctness tests must cover ASCII, accented Latin, CJK, Cyrillic, curly
apostrophes, supplementary characters, long paths, separators and
case-insensitive collisions.

The one isolated candidate eligible now is inside
`addVirtualSearchResult()`. `realPath` is already a `std::wstring` and the
Windows `boost::filesystem::path` therefore has a wide native representation.
Current code obtains `fullPath.filename().string()` (wide to narrow through the
globally imbued path locale), then explicitly decodes that narrow string as
UTF-8 back into `std::wstring` for `UNICODE_STRING`. Replacing the expression
with `fullPath.filename().wstring()` removes both conversions and avoids making
UTF-8 assumptions about a value that the NT API consumes as UTF-16.

This one-line candidate is isolated from the exact-exhaustion candidate and
must add focused non-ASCII virtual-enumeration coverage before CI. It does not
authorize changing the redirection tree's UTF-8 storage or other path
conversions. Game timing is expected to be small unless this site is hit at the
hundreds-of-thousands frequency seen for virtual matches.

### 5. Pack multiple redirections per directory call

Status: **conformance harness required before serving packed results**.

The source already notes that only one redirection is appended per call. A
candidate must correctly align and chain every supported directory information
record, honor small output buffers, `ReturnSingleEntry`, restart flags, exact
and wildcard searches, collisions and end-of-search status.

Required replay matrix before implementation:

- legacy `NtQueryDirectoryFile` and Ex API when Wine exposes the Ex hook;
- every information class supported by `file_information_utils.h`, with focused
  coverage for `FileDirectoryInformation`, `FileFullDirectoryInformation`,
  `FileBothDirectoryInformation`, `FileNamesInformation`, ID variants and
  extended ID variants;
- 1 byte below minimum, exact-size, one-record, two-record and oversized
  buffers, including filenames that change the aligned record size;
- `ReturnSingleEntry`/`SL_RETURN_SINGLE_ENTRY` on and off;
- initial, continued and restarted scans;
- exact filename, `*`, `*.*`, extension wildcard and no-match patterns;
- physical-only, virtual-only, multiple mapped parents, physical/virtual
  collision and two virtual layers with case-only collisions;
- ASCII, accented Latin, CJK, Cyrillic, supplementary characters, long names
  and long paths;
- assertions for status, `IoStatusBlock.Information`, record alignment,
  `NextEntryOffset`, final zero offset, name/short-name lengths, stable order,
  duplicate suppression and guard bytes outside the caller buffer.

The current `tvfs_test` has basic virtual-file coverage and the integration
fixtures enumerate real scenarios, but they do not establish this full binary
buffer contract. Therefore candidate 5 remains blocked on test construction,
not on game availability.

Source/test audit update (2026-08-01): both legacy and Ex hooks use the same
one-record virtual loop and contain an explicit TODO acknowledging that records
from more than one redirection are not appended. `FileInformationCurrent`
never advances after a successful virtual result, `dataRead` is reset to the
caller's full `Length`, and the successful match remains at the queue front
until a later physical exhaustion query. Packing therefore cannot be expressed
as merely removing the loop's `dataReturned` condition. It needs all of the
following as one reviewed unit: consume completed exact matches, advance by an
aligned used-record size, link the prior record's `NextEntryOffset`, pass only
the remaining buffer to the next query, retain an unqueried match when it will
not fit, and return total bytes rather than the last record's bytes. The
current Ex test uses only `FileFullDirectoryInformation`, a 2,048-byte buffer,
flags zero and a broad final-name superset assertion; it does not assert bytes,
offset alignment, restarts, small buffers, guard regions or multi-layer order.
This confirms that production packing before the replay matrix would be an
unmeasured ABI change, so no packed game DLL was built tonight.

Runtime-shape observation: every A/B and smoke capture logs the same failure to
install Wine's `NtQueryDirectoryFileEx` hook, while the legacy directory hook
is active and the game still enumerates correctly. Therefore the True North
timings exercise the legacy path only. CI directly exercises the Ex hook, but a
game smoke on this Proton version cannot validate Ex packing/restart behavior.
Any packing candidate needs the Windows/CI replay matrix for both APIs and must
not cite this Skyrim run as Ex coverage.

### 6. Negative/missing-file cache

Status: **observation-only simulation first**.

Record hypothetical hits without changing returned results. Do not serve cache
hits until invalidation is proven for create, delete, rename, overwrite writes,
mod-priority collisions and external filesystem changes.

Observation record must distinguish misses in immutable redirection-tree lookup
from misses in mutable physical existence/attributes. Proposed key fields are
normalized virtual path, operation family and the redirection-tree generation;
request access/disposition cannot be discarded when it changes semantics.
Count total probes, unique keys, repeat distance and hypothetical hits without
short-circuiting the real call.

Audit update (2026-08-01): a `STATUS_NO_SUCH_FILE`/Win32 not-found result is not
intrinsically cacheable. The same path can become valid through a hooked create
or rename, an overwrite write, another injected process, or an unhooked Linux
process. Redirection-tree generation alone covers only virtual mapping changes;
it does not cover physical creation. A safe observer may hash and count repeated
misses, but a serving negative cache needs either filesystem notification plus
overflow recovery or a deliberately short, validated lifetime with operation-
specific exclusions. No result-changing negative cache is authorized by the
current evidence.

### 7. Exact-path lookup cache

Status: **observation-only simulation first**.

Separate immutable redirection-tree resolution from mutable physical metadata.
Only the former is a plausible early cache target. Attribute/existence results
must remain uncached until invalidation is demonstrated.

The first safe experiment memoizes only virtual-path-to-redirection-node
resolution within one immutable published tree. It does not cache the resulting
physical file's existence, attributes, security, timestamps or create target.
Record hit rate by operation family and maximum retained key count; cap memory
before considering a serving build.

Source audit update (2026-08-01): the current tree has no mutation generation
suitable for a cache key. Hooked create/delete/move operations call
`insertMapping()`/`removeMapping()` during the game. `TreeContainer` can also
mark a shared-memory block outdated, allocate a larger block, copy the tree and
make each injected process lazily reassign its local pointer. A cache of raw
node pointers could therefore become both semantically stale and physically
dangling; a process-local invalidation counter would not observe another
injected process's shared-tree mutation. Before serving cached lookups, add a
shared monotonic generation changed by every tree mutation/reallocation and
prove that cache entries hold reconstructible values rather than unstable node
pointers. Until then, record normalized key hashes/hypothetical hits only and
always execute the real lookup.

### 8. Precomputed directory listings

Status: **design/profiling only**.

This requires a generation model for merged physical and virtual listings,
ordering, collision precedence, query patterns and live invalidation. It is not
eligible for the game DLL until the directory-query replay suite is complete.

A listing key would need virtual directory, normalized search pattern,
information class and mapping generation. The value cannot safely freeze
physical attributes. Invalidation must account for every hooked create,
delete, rename, copy, move and directory operation, writes into overwrite, and
changes made by unhooked/native Linux processes. Because the last category is
not observable inside the injected process, an immutable virtual-name listing
or bounded rescan design is more plausible than caching complete NT records.

Audit update (2026-08-01): directory enumeration is stateful per handle. The
current `Searches::Info` carries a search pattern, duplicate set, regular-phase
completion, queued virtual layers and an open physical search handle. A
precomputed global listing would have to reproduce that snapshot/continuation
state independently for legacy and Ex restart semantics; caching a vector of
names is not equivalent. This candidate remains behind the same replay suite
as packed records and additionally needs a cross-process/shared-tree generation
and a policy for native Linux filesystem changes.

### 9. Exclusive recursive context lock

Status: **contention instrumentation only**.

Record acquisition count, recursion depth, uncontended/contended count,
cumulative/max wait and hold time, thread ID and call site without logging
paths. Do not mechanically replace `RecursiveBenaphore`: `READ_CONTEXT()`
currently accesses mutable `customData` search maps and hook re-entry requires
recursive acquisition.

The profiler build will report per process: total acquisitions; outer versus
recursive acquisitions; contended acquisitions; cumulative/max wait; outer
hold count and cumulative/max hold; maximum recursion depth; and the thread ID
plus stable source hash for maximum wait/hold. Timing uses
`QueryPerformanceCounter`. Results are emitted once during normal
`usvfsDisconnectVFS`; the profiler DLL is never compared as a speed candidate
because the measurement itself adds overhead.

Source audit update (2026-08-01): this lock needs a correctness harness before
even the contention profiler. `readAccess()` and `writeAccess()` do use the
same `RecursiveBenaphore`, but “read” is not const in practice:
`HookContext::customData() const` inserts into `m_CustomData`, directory-query
code mutates per-handle `Searches`, two `READ_CONTEXT()` paths update
`SearchHandleMap`, and other read-labelled paths call `removeMapping()`.
Consequently `std::shared_mutex` would permit known writes to race. It would
also lose required recursive acquisition.

The existing benaphore has a separate suspicious first-contention behavior.
It starts with `m_Counter=0` but creates the kernel semaphore with initial count
one. Thread A increments the counter to one and enters without waiting. If
thread B overlaps, it increments to two, successfully consumes that initial
semaphore token, replaces `m_OwnerId`, increments the shared recursion count and
also enters before A signals. This follows directly from the source state
transitions; a targeted Windows concurrency test must reproduce or disprove it
under scheduling before a production fix. `m_OwnerId` and `m_Recursion` are
also ordinary shared fields, so their cross-thread access needs review.

Revised lock order: (1) add a deterministic mutual-exclusion/recursive-entry
test around `RecursiveBenaphore`; (2) correct any demonstrated exclusivity bug
without changing the API; (3) add low-overhead wait/hold counters; (4) audit and
separate every mutable read-labelled call site; only then consider a recursive
reader/writer design. A lock correctness fix and a lock performance experiment
must remain separate candidates.

### 9a. Stable shared-tree read view

Status: **test/infrastructure matrix green; no hook behavior change**.

The recursive reader/writer experiment proved that concurrent tree lookup can
remove substantial synthetic contention, but it also demonstrated that the
whole `HookContext` is the wrong sharing boundary. In addition to mutable
`customData`, `TreeContainer::get() const` calls `reassign()` through a
`const_cast` when another process marks the current shared-memory block
outdated. That operation replaces the process-local `m_SHM`, `m_TreeMeta` and
`m_SHMName`; admitting two nominal readers can therefore race in the local
rebind path. The rejected visual run logs show no post-attach rebind, so this is
a separate proved source hazard rather than an asserted explanation of the
winter-scene regression.

USVFS branch `perf/tree-read-view` starts from `687e890`, excluding both
rejected directory-search repairs. Source commit `48f1c30` adds a movable
`TreeContainer::ReadView` that keeps a process-local shared lock for the full
tree traversal, serializes stale-block reassignment through an exclusive slow
path, and makes `addFile`, `addDirectory` and container clearing wait for active
views. Two focused tests require eight simultaneous readers to converge on the
same newer block and require a local writer to remain blocked until a pinned
view is released. Commit `063bf5d` only adds the branch to the existing Windows
matrix trigger; `29b15eb` cleans up the new API comment without changing
behavior. [Final-head build run `30762949800`](https://github.com/SulfurNitride/usvfs/actions/runs/30762949800)
passed all x86/x64 Debug/Release builds and all four complete Windows test jobs,
including `shared_test` in every configuration. Lint run `30762949777` names
only the six already-documented inherited files and neither changed source/test
file.

This slice intentionally does not convert a hook, enable shared context, stage
a DLL or claim cross-process mutation safety. The next eligible step is a
separate cross-process test and generation-scoped delta (or equivalent
interprocess publication model) so the published base can actually be treated
as immutable. Only after that gate should raw-pointer-returning lookup use be
replaced with copied redirection results under `ReadView`, beginning with the
profiled attribute paths while exact-query exhaustion remains forced off.

### 9b. Published-tree mutation observer

Status: **final-head Windows matrix and exploratory runtime correctness green;
no post-publication mutation observed; selected Omni payload restored**.

The isolated implementation establishes the real lifecycle boundary before
designing immutable generations. A cross-process record in the stable shared
configuration marks the first attempted process injection as publication, with
target-side `HookManager` publication as a defensive fallback. Both redirection
trees report successful clear/add-file/add-directory operations through
process-local container observers, while the existing direct
`removeFromTree()` path reports removal only when an erase succeeds. The record
counts post-publication operations by tree and operation without logging paths,
and a compact summary is emitted when a normally exiting context disconnects.

Publication is intentionally idempotent and observational: post-publication
mutations continue to use the reference behavior. Pre-publication observer
calls use a process-local atomic fast rejection and do not acquire the shared
configuration mutex. Focused tests cover exclusion of pre-publication tree
construction, visibility through a second shared-memory mapping, failed-add
exclusion, and classification of every container mutation kind. Only one final
source head will enter the full Windows matrix. After that matrix is green, its
provenanced x64 artifact may be staged only long enough for the runtime
observation and the required deployment/correctness gates; it is not a selected
payload or a performance candidate.

Source commit `25c0bcb` contains the shared publication record, process-local
tree observers, successful-removal reporting, injection boundaries, compact
summary, and focused tests. Commit `e0d2534` changes only the workflow branch
trigger. The first build run `30764038606` compiled the DLL but exposed that the
new TVFS test directly referenced non-exported `HookContext` internals at link
time; fail-fast then canceled the other three build lanes. Commit `95fd4e0`
switches the test to the existing exported context factory and shared record,
exports only the new publication method, and leaves runtime behavior unchanged.
[Final-head build run `30764395765`](https://github.com/SulfurNitride/usvfs/actions/runs/30764395765)
passed every x86/x64 Debug/Release build, artifact merge, and complete test job.
Final-head lint run `30764395783` reports only the same six inherited formatter
failures; the two reported `kernel32.cpp` locations are pre-existing lines 716
and 849, outside the new publication block.

The required pre-staging Fluorine validation on 2026-08-02 passed: `./build.sh
test` completed all 19 tests and `./build.sh` completed the full portable
package. These commands did not stage or select an experimental DLL.

The exact `usvfs_Release_x64` artifact from commit
`95fd4e06e1740de02b5e53d0b311760a5ef868fc` and workflow `30764395765` has
DLL SHA-256
`b226e071452e4940ab1910715a6949bc8cbe08930e1eda8be1314b46c2d760c5`.
It was byte-verified in the portable observational bundle, whose recomputed
payload identity is
`e16eac028164a8ea336c91b98b9612ce560f5485de647af6320d406698993ff6`.
Attempted capture
`20260802T202019Z-tree-publication-observer-95fd4e0` correctly stopped at
preflight without deployment because the separate Steam compatibility prefix
`2357570` was active. No broad process cleanup was attempted. Repeat when the
host is idle, or only with explicit approval for an exploratory concurrent-load
correctness run.

Explicitly approved exploratory concurrent-load capture
`20260802T203850Z-tree-publication-observer-95fd4e0-concurrent` passed every
automated correctness gate: 1,144 mappings, two successful hook
initializations, the known 24 DBVO misses, DXVK/Gamescope surface, helper and
child drain, request removal, post-run sync, no new crash, all six Root Builder
files deployed/restored, and no exact-prefix survivor. The separate Overwatch
prefix remained present after Fluorine cleanup, proving cleanup stayed scoped.
Publication occurred immediately before the first target injection. The shared
summary after the subsequent Skyrim injection reported `publish_calls=3` and
zero post-publication mutations in either tree or any operation class. That
summary precedes completion of Skyrim initialization, but the observer also
warns synchronously on the first later shared mutation; no such warning appears
anywhere in the live log through the 90-second rendered dwell. Therefore this
launch observed no mutation after publication. Because it is one lifecycle
sample under unrelated concurrent load, retain dynamic-write support and use
the result only to justify the next generation-plus-delta prototype—not an
unconditional immutable-tree conversion or a timing claim.

After the observation, `./build.sh` regenerated the portable bundle from the
documented Omni payload. Deploy-only capture
`20260802T204240Z-restore-omni-after-tree-publication-observer` removed the
installed candidate marker and byte-verified both portable and installed x64
DLLs at SHA-256
`7454334c1ea246a68ff8da492b5d63dae8cd2f1298f2d7105c920b5f593352aa`.
The experimental `b226e071...760c5` DLL is no longer selected or installed.

### 9c. Cross-process shared-mapping boundary

Status: **automated correctness pass; the earlier mixed-assets visual rejection
is confounded by a mod that was under active development and no longer supports
a USVFS causal conclusion. Keep the shared-context option experimental/off and
make no performance claim pending a clean controlled visual repeat**.

The observer established that publication precedes target injection and found
no later mapping mutation in one complete rendered launch, but observation
alone does not make concurrent traversal safe. The safety candidate is USVFS
commit `ff4f8f14966ee13dd7388b97685a3174b516eaf8` on branch
`safety/shared-context-mapping-lock`. It keeps the existing opt-in environment
gate and coordinates every process attached to one mapping instance. Only the
outermost recursive context acquisition takes the interprocess boundary; the
process-local recursive SRW lock continues to handle hook re-entry.

The initial implementation commit `2573cac` used Boost's in-shared-memory
sharable mutex. Source audit then found that the primitive keeps a shared
reader count and exclusive flag that an abruptly terminated owner cannot clear.
That would trade corruption for an indefinite hang. Follow-up commit `1b7dec5`
replaces it with 64 named Windows mutex stripes plus a named writer gate.
Readers briefly pass the gate and own one stripe; a writer holds the gate while
acquiring every stripe. Kernel mutex abandonment makes dead reader ownership
recoverable without inventing a stale shared counter. An abandoned writer is
different: ownership can be recovered, but its shared tree may have been left
mid-mutation. The final safety audit therefore adds a named manual-reset
write-state event. Writers mark it before returning from exclusive acquisition
and clear it only after a normally completed write; abrupt termination or C++
exception leaves the instance poisoned, and later readers/writers fail closed
instead of traversing possibly inconsistent memory. Architecture
is part of the object name because x86 and x64 use different tree mappings;
commit `12c68a2` encodes the complete instance identifier in every object name
instead of accepting even a theoretical hash collision. Commit `771888e`
ensures recovery diagnostics cannot throw after an abandoned mutex has already
transferred ownership, which would otherwise leak the recovered lock.
Commit `74841bd` separates mapping-tree writes from process-local context-state
writes: both retain the process-local exclusive context lock, but only actual
mapping add/remove/clear/grow operations acquire every interprocess stripe.
Search bookkeeping and other local writes pin the mapping generation with one
shared stripe instead of paying 64 kernel mutex acquisitions.
Commit `2cbfbcd` also refreshes both process-local tree assignments at the
outermost ordinary or mapping write entry. This matters because directory
search setup uses the ordinary write guard for process-local search state and
then reads the tree, and because publishing parameters after mutating one tree
must not republish a stale generation name for the other tree.

An outer read refreshes both local `TreeContainer` assignments while holding
the shared interprocess lock before exposing either raw tree pointer. Every
known controller-side mapping clear/add path now enters the same context write
boundary used by hook-side additions/removals, so tree growth, outdated-marker
publication and generation copying occur under the exclusive interprocess
lock. Hook-context construction pins the mapping generation while attaching.
`RerouteW` no longer stores a shared-memory node pointer after its read guard
ends; removal re-finds the node under write access instead. This closes the
identified old-generation dangling-pointer path.

Focused tests cover explicit stale-generation refresh, outermost recursive lock
release, coordination through independently opened named mutex instances,
committed writer state, recoverable reader abandonment, and fail-closed writer
abandonment. The build
workflow runs all normal x86/x64 Debug/Release tests and, in every lane, repeats
TVFS, the upstream runner and the global runner with
`FLUORINE_USVFS_SHARED_CONTEXT=1`. Obsolete first-implementation build run
`30767082480` and intermediate run `30767346408` were canceled after safer
heads were pushed. Final-head build run `30767543772` reached compilation in
all four configurations, then failed on two integration defects: the const read
guard could not release its mapping mutex, and the context-access macros were
not namespace-qualified when used by the controller translation unit. The
correction commit `8126b36` makes the kernel-backed lock operations logically
const and fully qualifies the macros. Audit before that replacement completed
then found that ordinary context writes can also traverse mappings while
updating search state, so commit `2cbfbcd` refreshes both tree generations on
every outer write and safely unwinds both locks if refresh fails. Run
`30767903922` was canceled as obsolete. The write-interruption audit then
superseded `30767955829`. Replacement matrix
[`30768105847`](https://github.com/SulfurNitride/usvfs/actions/runs/30768105847)
at fail-closed commit `ff4f8f1` built all four x86/x64 Debug/Release lanes and
passed the normal suites plus focused committed-writer, abandoned-reader and
abandoned-writer tests. Its Release shared-mode upstream runner rejected the
candidate: recursive overwrite created the physical
`mfolder2\\newfile2.txt`, but a later injected process could not resolve it.
An exact-prefix local Proton reproduction produced the same failure and its
USVFS log identified both `recursive shared mutex upgrade is unsupported` and
`mapping lock upgrade is unsupported` during `NtCreateFile`. `CreateRerouter`
can recursively enter hooked create/close calls while its caller still holds a
read guard, so the later mapping insertion is correctly rejected instead of
performing an unsafe shared-to-exclusive upgrade. The correction must reserve
exclusive mapping intent before entering path creation; releasing and
reacquiring the shared lock is unacceptable because it introduces a stale-view
window. No artifact was staged from this failed or any superseded run.

Commit `05d1a40` adds an exclusive mapping-intent guard for path-resolution
helpers that can recursively create files/directories, with formatting-only
follow-up `6ee36f7`. Matrix
[`30768896450`](https://github.com/SulfurNitride/usvfs/actions/runs/30768896450)
passed every x86/x64 Debug/Release build and normal/shared-mode test, including
the formerly failing recursive overwrite/read. Its exact x64 Release DLL is
`7c5172aa30d631ffca77d876db4fc68bf9f98001448902cfcaf97c1cf7ff1313`.
A fresh exact-prefix Proton run also completed the `basic_x64` scenario and
confirmed the recursive file contents, but post-run USVFS log inspection found
19 swallowed `mapping lock upgrade is unsupported` diagnostics. They occur
when first-search directory setup holds an ordinary write/shared-mapping guard
while its `CreateFileW` parent-directory open re-enters `NtCreateFile`. Those
opens did not require a new mapping in this scenario, so functional assertions
missed the defect. The two legacy and Ex first-search blocks must reserve
mapping write intent, and the Windows shared-runner step must reject any future
upgrade, incomplete-write, or fail-closed diagnostic. The green artifact is
therefore diagnostic-only and remains unstaged.
Lint run
`30767543774` names only five inherited formatter failures and none of the
changed files; formatting the now-touched `kernel32.cpp` mapping calls removed
that file from the historical failure list. The legacy default path is
unchanged, and no artifact may be staged until the final matrix is fully green.
The required pre-staging Fluorine checks at this source head are green:
`./build.sh test` passed all 19 tests and `./build.sh` completed the portable
package using its cached local builder. The latter also regenerated the
documented Omni x64 payload; it did not stage this candidate.

The second correction is commits `ffaac6c` and formatting-only `c7a72e7`.
Both legacy and Ex directory first-search setup now reserve mapping write
intent before their parent-directory `CreateFileW` can re-enter the hook. The
shared-runner workflow also scans every generated USVFS log and fails on an
unsupported mapping/recursive upgrade, an incomplete write state, or a
fail-closed mapping-write diagnostic. Final matrix
[`30769540485`](https://github.com/SulfurNitride/usvfs/actions/runs/30769540485)
at exact head `c7a72e7125e82f42b503dd292bd5f7e0bb1bca29` passed all four builds,
all four complete test jobs, every shared-mode rerun, and the new diagnostic
gate. The x64 Release DLL SHA-256 is
`afd9ba432afd303dc9cc6cdb8ab45ac4e6065f40e85e34f86ef5757dd77e1d1b`;
the x86 Release DLL SHA-256 is
`763809a1364ff08ce9c29a4b2e33ff3d55a48afe4e1d4cb65201a81a7af5d0da`.
The separate lint run `30769540488` names only five inherited formatter
failures and no candidate-changed file.

An exact-prefix GE-Proton 11-3 validation of that final artifact passed
`semaphore_test_x64` and shared-mode `UsvfsTest.basic_x64`. The recursive
`mfolder2/newfile2.txt` mapping resolved to the overwrite source, the log
contained none of the four unsafe lock diagnostics, and no process survived in
the dedicated temporary prefix.

`./build.sh usvfs 30769540485` then exercised the new integrated packaging
path. It passed all 19 Fluorine tests, independently verified the exact workflow
head and eight required matrix jobs, packaged via Podman, embedded provenance,
and byte-compared both portable DLLs to the downloaded artifact. The installed
runtime remained the Omni reference; only `build/fluorine-manager` contains the
candidate.

The final artifact passed the four required 100K generated-workload modes
against the same corpus. Captures `20260802T222746Z-...-exactoff-sharedoff`,
`20260802T223149Z-...-exacton-sharedoff`,
`20260802T223326Z-...-exactoff-sharedon`, and
`20260802T223619Z-...-exacton-sharedon` each contain the complete 18 JSON
records, zero correctness errors, a profiler summary and no initial or final
benchmark-prefix PID. Mixed-concurrent elapsed times were 3,547.32, 3,558.64,
10,725.0 and 10,820.7 ms respectively. These single runs show a substantial
synthetic cost for the cross-process safety boundary and support no performance
claim; correctness, not speed, is the result of this matrix.

The first exact-only attempt `20260802T222926Z-...-exacton-sharedoff` was
manually interrupted after 8 of 17 operation phases. Proton returned zero, so
the old harness rejected it only at the missing-profiler gate. It is excluded.
The wrapper now prints a 15-second heartbeat and requires the exact full phase
multiset, preventing an interrupted partial JSON file from passing even when
the launcher reports success. True North uses the same visible fixed-dwell
cadence. The first True North attempt remained pending while unrelated
Overwatch prefix `2357570` was active; no concurrent Skyrim run was started.
Once the host was idle, controlled headless capture
`20260805T200945Z-shared-mapping-boundary-c7a72e7` deployed and byte-verified
the exact candidate with shared context on and exact-query exhaustion off. It
passed all gates: 1,144 mappings in 3,765 ms, two successful hook
initializations/process registrations, the reference 24 DBVO misses, DXVK and
Gamescope render-surface observation, helper/child drain, request removal,
post-run sync, no new crash, all six Root Builder files deployed and restored,
a nonempty profiler summary, no unsafe shared-lock diagnostic and no exact-
prefix survivor. The game process recorded 2,778,512 context acquisitions with
31 contended acquisitions; cumulative lock wait was 32,737.990 ms across all
calls. This is one correctness run, not timing evidence, and the 3,765 ms
mapping install plus the synthetic shared-mode slowdown provide no basis for a
performance claim.

The required human visible run began at 2026-08-05 20:14:53 UTC from the same
installed candidate, same True North shortcut and same profile. The interface
log proves `exact_query_exhaustion=false` and `shared_context=true`; the USVFS
log records 1,144 mappings in 3,731 ms, successful SKSE/Skyrim injection and
hook initialization, the same 24 known DBVO misses, normal helper completion
and no unsafe mapping-lock diagnostic. Despite that clean lifecycle, the user
observed mixed assets again in the visible scene. On 2026-08-05 the user
identified a mod being actively developed at the time as a likely independent
source of the asset mixture. The run remains valid lifecycle evidence, but it
is not a controlled USVFS visual comparison and cannot reject the
shared-context candidate or the exact-query interaction. USVFS log
`/home/luke/Games/Skyrim Modded/logs/usvfs-20260805-201453-167.log` has SHA-256
`069cd11e05ad273a36108d527c77a47d3b7755edf9c34ca708684d581e371e25`;
interface log `mo_interface_2026-08-05_15-14-52.log` has SHA-256
`3ce0bc3e9a62e753545cbd1166b58a7f8e1399ccd81a2837d463beb6faa81f3e`.
The candidate remains opt-in because its synthetic shared-mode slowdown and
single headless sample provide no promotion or performance basis. A future
acceptance decision requires a clean, fixed-mod-state same-save visual A/B.

The first attempted reference restore exposed a separate packaging safety bug:
the normal build removed candidate provenance but CMake retained the previous
`FLUORINE_USVFS_RUNTIME_DIR` cache entry, silently leaving candidate DLL bytes
in both bundles. Hash verification rejected that false restore. The container
build now always passes an explicit runtime path, using `/opt/fluorine-usvfs`
when no candidate is selected. A second required `./build.sh` rebuilt the Wine
controller from the pinned reference path. Ordinary tarball/installer builds
now also fail unless the staged/portable DLLs match both pinned reference
hashes and contain no candidate marker. Final deploy-only capture
`20260805T202025Z-restore-omni-after-shared-mixed-assets-final` verified both
portable and installed x64 hashes at `7454334c...352aa`, both x86 hashes at
`de23207b...13fc`, absent candidate provenance, absent Root Builder manifest
and no exact-prefix survivor. The short-name reference is restored.

## Results ledger

| Experiment | Build/DLL SHA-256 | Valid runs | Key result | Correctness | Decision |
| --- | --- | ---: | --- | --- | --- |
| Reference compact-log run | `7454334c...352aa` | 1 | 1,144 mappings; `mapping_install=3150 ms` | Game loaded/saved; premature Fluorine sync found | Not a statistical baseline |
| Lifecycle-anchor fix | core `dde18cf2...a93d`; DLL `7454334c...352aa` | 1 | `mapping_install=3125 ms`; Skyrim observed 6.43 s after `beforeRun`; menu-plugin proxy 12.99 s | Sync occurred ~0.52 s after termination; no crash; helper registration race exposed | Core fix verified; repair helper race before A/B work |
| Helper registration grace | helper `4c014e39...ab37`; DLL `7454334c...352aa` | 1 | `mapping_install=3126 ms`; Skyrim observed 6.44 s after `beforeRun`; menu-plugin proxy 12.66 s; `child_drain=91944 ms` | Both processes initialized; `observed_child=1`; request removed; sync after helper; 24 reference DBVO misses; no crash | Valid correctness baseline; collect repetitions before performance claims |
| Disabled logging | `26e290cb...debf` | 3 B + 3 A | Candidate median deltas: Skyrim -0.038%; Actor -0.655%; menu -0.531%; mapping -0.383% | All six automated runtime gates pass; 1,144 mappings; 24 DBVO misses; no crash | Correctness pass, performance reject; Omni restored |
| Skip exact exhaustion query | `85b3271c...d074` | 3 B + 3 A | Candidate medians: mapping -0.829%; Skyrim +0.314%; Actor -1.616%; menu -0.747% | Full CI matrix and all six runtime gates pass; 1,144 mappings; 24 DBVO misses | Correctness pass; modest later-proxy signal, no primary-startup win; do not promote from this evidence alone |
| Hash duplicate tracker | `b05a6259...5650` | 1 | Smoke: mapping 3,156 ms; Skyrim 6,565.439 ms; Actor 5,861.616 ms; menu 12,663.435 ms | Full CI plus runtime pass; 1,144 mappings; 2 hooks; 24 DBVO misses; clean teardown | Correctness pass, performance reject based on prior profile; no six-run series |
| Wide exact-query filename | `6c8af83f...58c` | 1 | Smoke: mapping 3,140 ms; Skyrim 6,502.332 ms; Actor 5,826.390 ms; menu 12,634.433 ms | Full CI plus runtime pass; 1,144 mappings; 2 hooks; 24 DBVO misses; clean teardown | Correctness pass; keep as Unicode/correctness cleanup, no timing claim from one run |
| Combined Wine-safe candidate | `f498e6c0...b68` | 3 B + 3 A controlled | Candidate median deltas: mapping -0.032%; Skyrim -0.346%; Actor +0.165%; menu +0.458% | Full CI plus all six runtime gates; 1,144 mappings; 2 hooks; 24 DBVO misses; clean teardown | Correctness pass, performance neutral; retain changes for correctness/review individually, do not replace Omni for speed |
| Selected combined profiling payload | `bcb68274...dcae` | 6 generated + 6 game | Exact continuation calls -330K/run; shared generated mixed phase -59.95%; default/shared game startup mixed within 0.74% | Full CI; all generated checks; all game/Root Builder gates; final deploy hash/provenance pass | Keep combined default path; retain shared lock opt-in; observers never serve cached data |
| Packed directory results | test matrix at `36752a9` | 4 CI configurations | Exact-query ABI matrix covers legacy/Ex, continuation/restart and six layouts; full Windows run `30714319149` green | No serving change; all upstream/focused tests pass | Continue buffer-size/multi-entry matrix before implementation |
| Negative cache observer | `bcb68274...dcae` | 6 game + 6 generated | Game lower bound: 129,248 repeated misses/380,884 observed (33.9%); collision table replaces 49.2% | Observation only; never serves a result | Promising, but blocked on native/external invalidation proof |
| Exact-path cache observer | `bcb68274...dcae` | 6 game + 6 generated | Game lower bound: 644,635 repeats/954,076 lookups (67.6%); generated lower bound 49.6% | Observation only; never serves a result | Build cross-process generation before any serving cache |
| Precomputed listings | pending design | 0 | — | — | No semantic change yet |
| Recursive lock exclusion | `ca8680ff...9d71` | 1 | Smoke: mapping 3,116 ms; Skyrim 6,554.502 ms; Actor 5,834.499 ms; menu 12,651.552 ms | Full CI plus runtime pass; 1,144 mappings; 2 hooks; 24 DBVO misses; clean teardown | Correctness fix accepted for review; no performance claim from one smoke |
| Recursive shared context lock | `bcb68274...dcae` | 3 default + 3 shared generated; 3 + 3 game | Generated mixed phase -59.95%; game startup proxies mixed within 0.74%; full-profile lock wait about -39% | Full CI; all generated checks; six Root Builder/game PASS captures | Retain opt-in; concurrency win proven, startup win rejected |
| Stable shared-tree read view | source `48f1c30` + comment `29b15eb`; workflow `30762949800` green | 4 CI configurations | Pins local tree assignment and serializes stale rebind; no hook converted | All x86/x64 Debug/Release builds and complete test jobs passed, including both focused tests | Infrastructure only; do not stage |
| Published-tree mutation observer | `b226e071...760c5`; source `25c0bcb` + linkage fix `95fd4e0`; matrix `30764395765` green | 1 exploratory correctness run | Publication calls 3; no post-publication mutation or first-mutation warning through rendered dwell | Full CI; all True North/Root Builder gates pass; exact-prefix cleanup left Overwatch untouched | Supports generation-plus-delta prototype; no timing claim; restore Omni |
| Cross-process shared-mapping boundary | source `c7a72e7`; matrix `30769540485`; DLL `afd9ba43...1d1b` | 4 generated; 1 local diagnostic; 1 headless + 1 confounded visible game | Shared mixed phase about 10.7–10.8 s vs 3.55–3.56 s off; headless mapping 3,765 ms; visible mapping 3,731 ms | Every automated gate passed; visible asset observation was later confounded by a mod under development | Correctness evidence retained; visual rejection withdrawn; remain experimental/off pending clean A/B and no performance promotion |
| Generated workload profiler | `943f28bf...2b4f` | 1 smoke + 1 100K | 100K: 360,000 parent opens/14.05 s; 639,995 contended locks/12.46 s cumulative wait | 180,001 physical files; every lookup/listing/collision check passed | Parent lifecycle and context lock are confirmed synthetic targets |

## Active experiment record: generated workload and context-lock profiler

- Profiler/benchmark acceptance build:
  `https://github.com/SulfurNitride/usvfs/actions/runs/30711608974` at
  `8ee1d57b17c6950b4cd174b564698915fdec33c8`. All x86/x64 Debug/Release
  builds and all shared, semaphore, injection, hook, TVFS, USVFS and global
  tests passed. Release x64 DLL SHA-256:
  `943f28bf14e5ecab188ec62b391dbb769385c90e647c71a23119b7435cc02b4f`;
  benchmark executable SHA-256:
  `3bb121b25e601546edf42d6f5441edf457c19532e304344c14d5f5f5435833dc`.
- The first standalone smoke correctly failed before VFS creation because the
  test helper assumed the repository's `test/bin`/`lib` layout. Commit
  `9368e20` makes the benchmark load its matching DLL from the executable
  directory. The old green artifact was rerun in its expected temporary layout
  to validate the workload while that fix rebuilt.
- Smoke capture:
  `/home/luke/Games/VFS Benchmarks/results/20260801T181547Z-files1000-layers4-threads4`.
  It passed all results with 1,000 logical files, four layers and 128 buckets.
  It measured 2,400 parent opens/93.450 ms, 4,600 virtual backing queries/28.816
  ms, 2,656 `NO_MORE_FILES` results and 3,512 contended context acquisitions/
  21.598 ms cumulative wait.
- 100K capture:
  `/home/luke/Games/VFS Benchmarks/results/20260801T181603Z-files100000-layers8-threads8`.
  The durable corpus contains 100,000 unique assets plus 10,000 collision names
  in all eight layers: 180,001 physical files including the marker, using 704
  MiB. All attribute, missing, open, exact-search, merged-listing, collision and
  concurrent checks reported zero errors.
- Key 100K wall times: mapping 2,789.53 ms; existing attributes about 1,003–
  1,011 ms/100K; missing attributes 2,679–2,713 ms/100K; one-byte opens 4,357–
  4,497 ms/100K; exact collision searches 2,164–2,169 ms/10K; merged walks
  7,151–7,217 ms/4,096 buckets; eight-thread mixed lookup 2,694.83 ms/300K.
- Key cumulative profiler totals: 6,447,463 context acquisitions; 639,995
  contended (9.926%); 12,457.079 ms wait and 19,444.972 ms hold; 384,576 legacy
  directory calls; 360,000 physical parent opens/14,047.195 ms; 690,000 virtual
  backing queries/4,604.085 ms; and 372,288 backing `NO_MORE_FILES` results.
  Attribute hooks account for essentially all observed contention. This proves
  a synthetic concurrency opportunity but not an equal real-game percentage;
  profiling atomics also add overhead, so wall-time A/B remains mandatory.
- True North capture
  `20260801T181800Z-combined-profile-8ee1d57` passed every game, hook, sync,
  crash, process and Root Builder gate. Six deployed root files existed while
  running and were fully restored. It was marked invalid only because fixed-
  dwell process termination bypassed the game DLL's teardown summary; the
  naturally exiting SKSE loader emitted 27 queries and no parent opens. Commit
  `1feedf0` adds sequence-numbered cumulative snapshots every 10,000 queries so
  the next fixed-dwell capture retains the game's counters without per-call
  logs.
- The first reader/writer experiment is environment-gated by
  `FLUORINE_USVFS_SHARED_CONTEXT=1`. Default behavior remains the repaired
  recursive benaphore. The candidate uses a recursive SRW reader/writer lock,
  makes every known `customData`, search-map and mapping-removal mutation
  explicitly exclusive, rejects shared-to-exclusive upgrades, and adds focused
  tests for overlapping readers, writer exclusion, recursion and upgrade
  rejection. It is not eligible for game staging until the full matrix and
  generated 100K correctness run pass.
- The same profiler head adds two non-serving, fixed-memory cache observers.
  Each uses a 65,536-slot direct-mapped table of case/separator-normalized
  63-bit path hashes and never skips the real lookup. `tree_lookup_cache`
  classifies repeated found/missing redirection-tree resolutions;
  `negative_attribute_cache` classifies repeated final Win32 missing outcomes.
  It records same-result repeats, result changes, first slot uses and collision
  replacements. The bounded direct map can undercount reusable paths due to
  eviction and has a negligible theoretical hash-collision risk; it cannot
  establish invalidation safety. It measures the ceiling/hit shape needed
  before a generation-aware serving cache is considered.

## Active experiment record: recursive context-lock exclusion

Recorded before implementation on 2026-08-01.

- Reference source: `644eebfe7e454ead93774fcda95fa9b3ddfddb09`.
- Scope: prove and, if reproduced, fix the existing `RecursiveBenaphore`
  mutual-exclusion invariant before measuring contention or attempting shared
  reads. This is a correctness candidate, not the screenshot's proposed
  reader/writer optimization.
- Source hypothesis: `m_Counter` starts at zero but the kernel semaphore is
  created with initial count one. Owner A's first acquisition increments to one
  and does not wait. Waiter B increments to two and consumes the already-
  signaled semaphore immediately, so both can enter and B overwrites the owner
  and recursion fields.
- Deterministic test design: owner A recursively acquires twice and remains in
  the critical section. Waiter B announces that it is about to acquire. Assert
  B cannot enter before either owner release, remains blocked after the first
  recursive release, and enters only after the final release. Always release
  and join both threads even when an assertion fails.
- Narrow proposed repair if the test reproduces: initialize the semaphore with
  count zero, matching the standard benaphore counter protocol. Do not change
  dead-owner recovery, timeout behavior, recursion API, call sites or context
  state in the same candidate.
- Acceptance: new focused test fails against the reference implementation,
  passes with the one-line initialization fix, and the complete x86/x64
  Debug/Release matrix remains green. Game timing is not an acceptance metric
  for a mutual-exclusion correctness repair; a runtime smoke is considered only
  after the full matrix.
- Test commit: `03c7322` on `fix/recursive-benaphore-exclusion` adds a dedicated
  `semaphore_test` executable that compiles the real lock implementation and
  exercises two recursive owner levels against a competing thread. Fork-cache
  and branch-trigger commits are isolated from the test/repair.
- Red build run: `https://github.com/SulfurNitride/usvfs/actions/runs/30687732461`
  built all four configurations successfully at unfixed head `b341e7d`. The
  workflow did not yet list the newly auto-built executable, so its x64 Release
  `semaphore_test` artifact was run directly through GE-Proton 11-3 in a fresh
  temporary prefix with GTest XML output. It failed both required exclusion
  checkpoints in 3 ms: waiter B entered while owner A held two recursive levels
  and was already inside after A released only one level. Test executable SHA-
  256: `52f24f7896972d085e38c78387316dd92ce1f9c2567c3570740bce87dc04bb05`;
  captured XML SHA-256:
  `9dd56ac3c98f7500316aed86f6a415956fb4c304c27bae74961bf103003e6340`.
- Repair commit: `dee6f19` changes only `CreateSemaphore`'s initial count from
  one to zero and documents the counter protocol. Workflow commit `0647ffe`
  adds `semaphore_test` to every x86/x64 Debug/Release test job.
- First green attempt `30688121775` was superseded/cancelled when the separate
  whole-tree formatter identified four alignment-only changes in the new test.
  Commit `6908856` applies those changes; none affects test behavior or the
  lock repair.
- Green run:
  `https://github.com/SulfurNitride/usvfs/actions/runs/30688358000` at full head
  `6908856cfc294e615ff6ba9f95760e179d6a44e3` is now the acceptance matrix.
  Do not stage its DLL unless all four focused tests and the complete upstream
  suite pass. Lint run `30688357996` no longer names either candidate file; it
  fails only on the same seven inherited reference-tree files recorded for the
  earlier candidates. Candidate formatting therefore passes, while inherited
  whole-tree debt remains separate.
- Green result: run `30688358000` completed successfully. All four builds and
  every shared, semaphore, injection, hook, TVFS, USVFS and global test passed
  in x86/x64 Debug/Release. Merged Release x64 DLL SHA-256:
  `ca8680ff41c0928a3c63f24632732b0a5a7ace720b87145d7229fdff455a9d71`.
  It was staged only after a fresh required Fluorine `./build.sh`; the next
  action is one standard 90-second True North correctness smoke. This run is
  explicitly not a context-lock performance benchmark.
- Runtime smoke `20260801T065752Z-recursive-benaphore-fix-smoke` passed every
  automated gate with the exact candidate DLL: 1,144 mappings in 3,116 ms, both
  hooks initialized, 24 reference DBVO misses, request removal, post-helper
  profile sync, no new crash and no exact-prefix survivor. Startup proxies were
  6,554.502, 5,834.499 and 12,651.552 ms. Its warning/error-class count matches
  A7 exactly. This establishes exercised-workload compatibility for the
  correctness repair; one smoke is not timing evidence and says nothing about
  the benefit of a future reader/writer redesign.

## Active experiment record: exact virtual-query exhaustion

Recorded before build or runtime testing on 2026-08-01.

- Reference source: `644eebfe7e454ead93774fcda95fa9b3ddfddb09`.
- Candidate code commit: `c9392ba` on `perf/skip-exact-exhaustion` in
  `/var/home/luke/Documents/usvfs`.
- CI-only follow-ups select the fork-safe GitHub Actions vcpkg cache and add
  this branch to the existing push matrix; candidate filesystem behavior is
  contained entirely in `c9392ba`.
- Focused continuation/restart test commit: `2ff438f`. It extends the legacy
  exact-name test to require success, `STATUS_NO_MORE_FILES`, and success again
  after restart on the same handle.
- Build matrix: `https://github.com/SulfurNitride/usvfs/actions/runs/30686589387`.
- Lint run: `https://github.com/SulfurNitride/usvfs/actions/runs/30686589380`.
  An earlier matrix for the same code without the focused assertion was
  cancelled once this superseding commit began; it is not acceptance evidence.
- Controlled variable: a boolean in each active directory search records that
  its current exact virtual match already returned successfully. The next
  continuation closes/pops that match without the redundant NT query.
- Non-changes: still one successful virtual match per caller response; no
  record packing, cache, ordering, normalization, buffer or lock changes.
- Build gate: all x86/x64 Debug/Release binaries and every upstream test must
  pass before the Release x64 artifact may be staged.
- Runtime gate: standard helper/hook/request/sync/crash/process validity plus
  unchanged 1,144 mappings and 24 reference DBVO misses. A single valid B run
  is only a smoke test; timing acceptance still needs alternating repetitions.
- CI result: run `30686589387` completed successfully. All four x86/x64
  Debug/Release builds passed every shared, injection, hook, TVFS, USVFS and
  global test, including the new exact-query continuation/restart assertions.
  Merged Release x64 DLL SHA-256:
  `85b3271c41e98f49cadf09c05d81f8b70a08eda0749a52fecbebf95cee21d074`.
  It is now eligible for staged runtime testing; no game result exists yet.
- B1 runtime capture: `20260801T060207Z-skip-exact-exhaustion-b1` passed every
  automated gate with the exact candidate DLL and content-derived bundle
  identity. It installed 1,144 mappings in 3,128 ms, initialized both SKSE and
  Skyrim hooks, retained the 24 reference DBVO misses, removed the request,
  synced afterward, produced no crash and left no prefix survivor. Startup
  proxies were 6,544.116 ms to Skyrim, 5,859.369 ms to ActorLimitFix and
  12,659.099 ms to MainMenuRandomizer. This single run is not faster than the
  reference band and supports no performance claim; continue alternating A/B.
- A5 reference capture: `20260801T060424Z-omni-baseline-a5` was rebuilt with
  `./build.sh`, contained Omni's exact DLL and no candidate metadata, and passed
  every runtime gate. Mapping installation was 3,130 ms; startup proxies were
  6,536.018, 5,918.330 and 12,720.099 ms with the same 1,144 mappings and 24
  DBVO misses. The bundle identity correctly forced candidate-to-reference
  deployment without the old core-mtime workaround.
- B2 capture: `20260801T060643Z-skip-exact-exhaustion-b2` passed all gates with
  1,144 mappings, two hooks, 24 reference DBVO misses and clean teardown.
  Mapping installation was 3,110 ms; startup proxies were 6,554.773,
  5,801.694 and 12,625.021 ms. The candidate was slower at the coarse Skyrim
  observation but earlier at the plugin/menu proxies than adjacent A5; this
  mixed single-pair result is not a decision, so continue the alternation.
- A6 reference capture: `20260801T060901Z-omni-baseline-a6` passed all gates.
  Mapping installation was 3,136 ms and startup proxies were 6,509.292,
  5,957.483 and 12,765.821 ms, again with 1,144 mappings and 24 DBVO misses.
- B3 capture: `20260801T061116Z-skip-exact-exhaustion-b3` passed all gates.
  Mapping installation was 3,110 ms and startup proxies were 6,514.977,
  5,822.697 and 12,624.868 ms with unchanged mapping/miss counts. Candidate
  plugin/menu proxies are now consistently earlier across three runs, but the
  final rebuilt A7 and aggregate statistics remain mandatory.
- A7 reference capture: `20260801T061353Z-omni-baseline-a7` passed all gates
  after a fresh required `./build.sh`. Mapping installation was 3,164 ms and
  startup proxies were 6,523.660, 5,913.792 and 12,717.986 ms, with the same
  1,144 mappings, two hook initializations and 24 DBVO misses.

Final six-run A/B result (three runs per payload):

| Metric | Omni A median (range; MAD) | Candidate B median (range; MAD) | B - A |
|---|---:|---:|---:|
| Mapping installation | 3,136 ms (3,130–3,164; 6) | 3,110 ms (3,110–3,128; 0) | -26 ms (-0.829%) |
| `beforeRun` to Skyrim observation | 6,523.660 ms (6,509.292–6,536.018; 12.358) | 6,544.116 ms (6,514.977–6,554.773; 10.657) | +20.456 ms (+0.314%) |
| `beforeRun` to ActorLimitFix | 5,918.330 ms (5,913.792–5,957.483; 4.538) | 5,822.697 ms (5,801.694–5,859.369; 21.003) | -95.633 ms (-1.616%) |
| `beforeRun` to MainMenuRandomizer | 12,720.099 ms (12,717.986–12,765.821; 2.113) | 12,625.021 ms (12,624.868–12,659.099; 0.153) | -95.078 ms (-0.747%) |

All six runs passed the same lifecycle and correctness gates. The candidate
does not improve the primary Skyrim-process observation; its median is 20 ms
later. It does show a repeatable roughly 95 ms earlier Actor/menu-plugin signal,
but the two later timestamps move together and the MainMenuRandomizer timestamp
does not prove that a rendered menu is interactive. Treat this as evidence that
the removed probe is behaviorally sound and may save a small amount of later
startup work, not as proof of a total load-time improvement. Keep the isolated
commit for lower-level profiling or a human/frame-detected menu series; do not
make it Fluorine's default USVFS payload from this result alone.

## Active experiment record: wide physical query filename

Recorded before build or runtime testing on 2026-08-01.

- Reference source: `644eebfe7e454ead93774fcda95fa9b3ddfddb09`.
- Candidate code/test commit: `ab71bfe` on
  `perf/wide-virtual-filename`.
- Controlled change: replace
  `filename().string()` plus explicit UTF-8 decoding with the Windows-native
  `filename().wstring()` at the single `addVirtualSearchResult()` call site.
- Focused test: create and enumerate a real temporary physical filename that
  contains accented Latin (`é`), Cyrillic (`Ж`), CJK (`文件`) and a
  supplementary character (rocket), mapped to an ASCII virtual name. Cleanup
  is scoped to that exact temporary file.
- Non-changes: redirection-tree UTF-8 storage, virtual-name conversion,
  normalization, ordering, caches, locks and query lifecycle are untouched.
- Build matrix:
  `https://github.com/SulfurNitride/usvfs/actions/runs/30686678311`.
- Lint run:
  `https://github.com/SulfurNitride/usvfs/actions/runs/30686678315`.
- Acceptance: every x86/x64 Debug/Release test passes, followed by standard
  True North correctness gates. Because this is one conversion site, promote
  only if it is behaviorally safer for Unicode or produces repeatable timing;
  do not extrapolate it to the screenshot's broad UTF percentage range.
- CI result: build/test run `30686678311` at workflow head
  `1f8ce872000da49d948c75b724a5e0472358b32d` completed successfully. Every
  x86/x64 Debug/Release shared, injection, hook, TVFS, USVFS and global test
  passed, including the focused Unicode physical-name assertion. The separate
  whole-tree formatting job failed only on inherited reference-tree files;
  neither candidate-changed file is in that failure set. The Release artifact
  x64 SHA-256 is
  `6c8af83fb24c2bf7df9c89159c504fa43ecbefbfb0cf9b4d9bcabc482e9e858c`.
  It was staged from the immutable workflow artifact after a fresh baseline
  `./build.sh`.
- Runtime smoke `20260801T061755Z-wide-physical-filename-smoke` passed every
  automated gate with that exact DLL: 1,144 mappings in 3,140 ms, successful
  SKSE and Skyrim hooks, 24 reference DBVO misses, request removal, post-helper
  profile sync, no new crash and no exact-prefix survivor. Startup proxies were
  6,502.332 ms to Skyrim, 5,826.390 ms to ActorLimitFix and 12,634.433 ms to
  MainMenuRandomizer. This is intentionally one correctness smoke, not a timing
  series. The change is a more direct/correct Windows-wide-path operation and
  is safe in the tested workload, but the run supports no speed percentage.
  Its warning/error-class count and normalized diagnostic set exactly match A7:
  the same unavailable Wine hooks and the same 24 known DBVO misses, with no
  candidate-only class.

## Active experiment record: hash duplicate tracker

Recorded before build or runtime testing on 2026-08-01.

- Reference source: `644eebfe7e454ead93774fcda95fa9b3ddfddb09`.
- Candidate code commit: `c0ba2b2` on `perf/hash-duplicate-tracker`.
- Controlled change: `Searches::Info::foundFiles` and its helper parameter use
  `std::unordered_set<std::wstring>` instead of `std::set<std::wstring>`.
  Values remain uppercased before insertion, and code never iterates the
  container, so ordering cannot affect directory-result order.
- Non-changes: normalization, collision precedence, virtual-match order,
  directory buffers and query lifecycle are untouched.
- Build matrix:
  `https://github.com/SulfurNitride/usvfs/actions/runs/30686721391`.
- Lint run:
  `https://github.com/SulfurNitride/usvfs/actions/runs/30686721387`.
- Decision gate: compile/test and at most a correctness smoke run. Existing
  profiling attributes only ~0.25 seconds to all duplicate/filter work, so it
  is not entitled to a six-run game series unless a lower-level measurement
  first contradicts that profile.
- CI result: build/test run `30686721391` at workflow head
  `3c04a883adbbf6834c7fe78d86ec1121dea9e804` completed successfully. Every
  x86/x64 Debug/Release shared, injection, hook, TVFS, USVFS and global test
  passed. The separate whole-tree formatting failure is the same inherited
  reference-tree debt and does not name the candidate-changed files. The
  Release artifact is eligible for one correctness smoke after its hash is
  recorded; the existing profile still rules out spending a six-run game
  series on it. Release x64 SHA-256 is
  `b05a62593881d1815e2a0aa7ef722e08f080b6a333333e8ae83e5621ad775650`.
  It was staged only after a fresh required `./build.sh`; the next action is the
  single documented 90-second True North correctness smoke.
- Runtime smoke `20260801T062031Z-hash-duplicate-tracker-smoke` passed every
  automated gate with that exact DLL: 1,144 mappings in 3,156 ms, both hooks,
  24 reference DBVO misses, request removal, post-helper sync, no new crash and
  no exact-prefix survivor. Startup proxies were 6,565.439, 5,861.616 and
  12,663.435 ms. One smoke cannot establish timing; combined with the existing
  profile's ~0.25 seconds for the entire duplicate/filter category, there is no
  basis for an expensive six-run series or a user-visible performance claim.
  Keep it only as a behaviorally safe micro-optimization candidate.
  Its warning/error-class count and normalized diagnostic set also exactly
  match A7, so the smoke introduced no new logged failure class.

## Active experiment record: disabled `CallLogger` fast path

Recorded before implementation on 2026-08-01.

- Reference source: `644eebfe7e454ead93774fcda95fa9b3ddfddb09`.
- Candidate code commit: `bf816976832a91d258623bb1f0f703d20c03a597` on
  `SulfurNitride/usvfs:perf/fluorine-lab`; CI-only cache repair commit:
  `bbff6f541956970d4e305023bd6e2299b8dbe8cf`.
- Windows build/test run:
  `https://github.com/SulfurNitride/usvfs/actions/runs/30685416581`.
- Formatting/lint run:
  `https://github.com/SulfurNitride/usvfs/actions/runs/30685416580`.
- Reference game DLL: `7454334c...352aa` (Omni Wine short-name build).
- Reference valid run:
  `20260801T050455Z-helper-registration-grace-1`.
- Controlled variable: only disabled Debug call-logging bookkeeping in USVFS;
  Fluorine, profile, mappings, Proton, dwell and x64/x86 pairing stay fixed.
- Primary startup proxies: `beforeRun` to Skyrim observation,
  `ActorLimitFix.log` mtime, and `MainMenuRandomizer.log` mtime.
- Supporting USVFS metrics: mapping count/install time and hook-init outcome;
  `child_drain` and `helper_total` are lifecycle gates, not speed metrics.
- Rejection criteria: any upstream test failure, missing hook/process record,
  changed VFS behavior, new crash/error class, request leak, premature sync, or
  an A/B effect indistinguishable from warm-run variation.
- Current state: committed, pushed, fully built/tested, and B1 game-tested. The
  first build run
  (`30685337482`) failed before configuration because the upstream workflow's
  private Azure vcpkg variables are unavailable to a fork. Commit `bbff6f5`
  selects the native GitHub Actions cache and reruns the matrix. The standalone
  whole-tree clang-format 22
  workflow failed on seven files already present in the reference commit; none
  of the four candidate-changed files appears in its failure list. Treat this
  as inherited repository lint debt, not a candidate pass, and rely on the
  Windows compile/test matrix plus changed-file formatting for acceptance.

CI and first runtime update:

- Run `30685416581` built x86/x64 Debug/Release successfully and every upstream
  shared, injection, hook, TVFS, USVFS and global test executable passed in all
  four configurations.
- Merged x64 Release DLL SHA-256:
  `26e290cbce96db48f4d24cba586eb1d7782ecc4a9b975cbad9378aa5e4b5debf`.
- B1 capture: `20260801T052623Z-disabled-call-logging-b1`.
- B1 passed every automated game gate with 1,144 mappings, 24 reference DBVO
  misses and no crash. Startup proxies were 6,439.325 ms to Skyrim observation,
  5,838.478 ms to ActorLimitFix and 12,647.235 ms to MainMenuRandomizer. These
  are effectively identical to the single reference observation; continue the
  alternating series before deciding.
- B2 retry capture: `20260801T053316Z-disabled-call-logging-b2-retry`.
- B2 passed every automated gate with the candidate SHA, 1,144 mappings, two
  successful hook initializations, 24 reference DBVO misses and no crash or
  surviving prefix process. Mapping installation took 3,119 ms; startup proxies
  were 6,521.817 ms to Skyrim observation, 5,845.261 ms to ActorLimitFix and
  12,651.427 ms to MainMenuRandomizer. The candidate remains within ordinary
  run-to-run variation; no performance claim is supported yet.

Final six-run A/B result (three validator-era runs per payload):

| Metric | Omni A median (range) | Candidate B median (range) | B - A |
|---|---:|---:|---:|
| Mapping installation | 3,131 ms (3,110–3,142) | 3,119 ms (3,114–3,134) | -12 ms (-0.38%) |
| `beforeRun` to Skyrim observation | 6,524.313 ms (6,514.205–6,542.175) | 6,521.817 ms (6,439.325–6,530.421) | -2.496 ms (-0.038%) |
| `beforeRun` to ActorLimitFix | 5,883.793 ms (5,868.492–5,923.916) | 5,845.261 ms (5,838.478–5,846.254) | -38.532 ms (-0.655%) |
| `beforeRun` to MainMenuRandomizer | 12,714.698 ms (12,676.495–12,741.897) | 12,647.235 ms (12,635.406–12,651.427) | -67.463 ms (-0.531%) |

All six runs had exactly 1,144 mappings, two successful hook initializations,
24 identical known DBVO misses, clean request/profile/process teardown and no
new crash. The candidate is therefore a correctness pass but a performance
rejection for this workload: every median delta is below 1%, and the primary
Skyrim-observation delta is effectively zero. Keep the source commit as a safe
micro-optimization/data point, but do not replace Omni's build or claim a load
time improvement from it. The installed and portable bundles were restored to
the Omni reference after the series.

## Change log

- 2026-07-31: Created the lab protocol before automated deployment or game
  testing. Recorded the reference run, safety scope, lifecycle regression and
  candidate-specific gates.
- 2026-07-31: Added `tools/usvfs-benchmark/run-true-north.sh`. The harness
  records build/DLL identities and process snapshots, deploys through the
  portable wrapper, verifies the installed files, launches the exact True North
  shortcut, waits a fixed interval after detecting Skyrim, terminates only
  processes associated with the exact Fluorine prefix, and extracts structured
  benchmark/timeline diagnostics. `bash -n` passes before its first game run;
  `shellcheck` is not installed on the host and is recorded as unavailable.
- 2026-07-31: First baseline preflight was invalidated before game launch. The
  host permits enumerating `/proc` entries whose `environ` files are not
  readable; the initial reader emitted a permission diagnostic per entry. The
  run was aborted after bundle deployment and is not counted. Process readers
  now open `/proc/<pid>/environ` and `comm` through guarded file descriptors and
  silently skip inaccessible entries.
- 2026-07-31: A deploy-only validation exposed Bash's left-to-right redirection
  ordering: the protected file was opened before stderr was redirected. This
  second preflight was also aborted before game launch and is not counted. The
  readers now redirect diagnostics before opening the guarded `/proc` file.
- 2026-08-01: Deploy-only validation
  `20260801T050026Z-harness-deploy-validation-2` completed successfully. It
  produced no `/proc` noise, stopped its exact process group, verified that no
  installed organizer remained, and byte-compared the installed core and x64
  DLL with the portable build.
- 2026-08-01: True North run
  `20260801T050045Z-lifecycle-fixed-baseline-1` verified the lifecycle-anchor
  repair. Fluorine tracked a helper-named process through the 90-second dwell
  and did not run INI/plugin sync until approximately 0.52 seconds after Skyrim
  termination. There was no new crash file. The run also exposed a separate
  helper race: SKSE's target lifetime was 129 ms, and the helper observed an
  11 ms empty registered-process window while `SkyrimSE.exe` was still
  initializing. It disconnected before Skyrim completed registration, so
  `helper_total=3311 ms` and the USVFS log ended mid-initialization even though
  the game continued. This run verifies the Fluorine lifecycle fix but is not a
  valid USVFS optimization baseline.
- 2026-08-01: Added a two-second post-loader registration grace and a 500 ms
  stable-empty requirement to the Windows helper's child-drain loop. The next
  game run must report `observed_child=1` and retain logging until Skyrim exits.
- 2026-08-01: `./build.sh test` passed 18/18 tests and the required full
  `./build.sh` packaging build completed for the helper-race repair. True North
  run `20260801T050455Z-helper-registration-grace-1` then completed cleanly.
  The x64 DLL remained Omni's exact Wine-short-name build
  (`7454334c...352aa`). USVFS installed 1,144 mappings in 3,126 ms, initialized
  hooks successfully in both the 129 ms SKSE loader and Skyrim, observed the
  Skyrim child, and remained connected for a 91,944 ms child drain. Fluorine's
  INI/plugin sync followed helper completion, the serialized request was gone,
  the known DBVO `c000000f` count was 24, and no new crash file appeared. Raw
  capture:
  `/home/luke/Games/Skyrim Modded/logs/benchmarks/20260801T050455Z-helper-registration-grace-1`.
  This is a valid correctness baseline but a single observation, so it is not
  used for a percentage claim.
- 2026-08-01: Created the persistent USVFS checkout at
  `/var/home/luke/Documents/usvfs`, local branch `perf/fluorine-lab`, from
  `SulfurNitride/usvfs` commit `644eebfe7e454ead93774fcda95fa9b3ddfddb09`.
  Selected the repository's Visual Studio 2022/vcpkg CI matrix as the canonical
  custom-DLL build path because it also exercises upstream x86/x64 test suites;
  host-side MinGW output will not be treated as release-equivalent evidence.
- 2026-08-01: Extended the True North harness with a machine-readable
  `validity.txt` and a failing exit status for missing lifecycle, registration,
  hook-init, request cleanup, sync, crash and exact-prefix cleanup gates. It
  records the DBVO miss count for direct comparison. `bash -n` and the help
  path pass after the change; the next game run will exercise all runtime
  checks.
- 2026-08-01: Added
  `tools/usvfs-benchmark/stage-usvfs-candidate.sh` for reproducible integration
  of a CI-produced x64 Release DLL after `./build.sh`. It validates the PE
  architecture and full source commit/run URL, records provenance and SHA-256,
  and byte-compares the staged DLL. `bash -n` and its usage-error path pass.
- 2026-08-01: Installed no new host packages, but used an ephemeral copy of the
  existing Fluorine builder container to run ShellCheck against the benchmark
  helpers. `run-true-north.sh`, `stage-usvfs-candidate.sh`, and
  `summarize-runs.sh` pass with no diagnostics. This supersedes the earlier note
  that ShellCheck was unavailable on the host while preserving the host
  environment.
- 2026-08-01: Added the TSV summarizer and validated it against
  `20260801T050455Z-helper-registration-grace-1`; its three startup deltas and
  24 DBVO misses agree with the raw timestamps and manual audit.
- 2026-08-01: Candidate B2 preflight
  `20260801T053109Z-disabled-call-logging-b2` was rejected before game launch
  because the installed USVFS DLL still had the reference SHA. The generated
  portable wrapper fingerprints updates using only `ModOrganizer-core` size
  and mtime; changing only `usvfs_x64.dll` therefore did not trigger a second
  overlay after the immediately preceding reference deployment. This capture
  is not a benchmark observation. The candidate staging helper now advances
  the portable core mtime after a verified DLL replacement, forcing the normal
  wrapper overlay on its next deployment. The game harness still requires
  byte-identical deployed core and x64 DLL files before it can launch, so a
  stale candidate is a hard preflight failure rather than contaminated data.
- 2026-08-01: The B2 preflight is also a production updater defect, not only a
  lab inconvenience. Planned repair: build `fluorine-bundle-version.txt` from
  a deterministic SHA-256 digest of every shipped regular file except the
  manifest and version file themselves. The portable launcher will hash that
  tiny version file for its installed marker and retain the core size/mtime
  only as compatibility fallback for older bundles. Candidate staging will
  recompute the same digest after replacing a DLL; on an old build it will keep
  the documented core-mtime fallback. This detects helper, DLL, plugin,
  library and asset-only updates without hashing the 237 MB payload at every
  application launch.
- 2026-08-01: Retried B2 as
  `20260801T053316Z-disabled-call-logging-b2-retry` after the documented staging
  correction. It passed all automated validity gates. The deployed DLL was
  `26e290cb...debf`, both SKSE and Skyrim hooks initialized, the helper drained
  the child for 92,043 ms, the serialized request was removed, profile sync ran
  afterward, no new crash appeared, and exact-prefix cleanup had no survivors.
  The three startup proxies were 6,521.817, 5,845.261 and 12,651.427 ms; retain
  the candidate only as an A/B subject until the full alternating series is
  summarized.
- 2026-08-01: Rebuilt the portable bundle with the required `./build.sh` and
  verified that A3 contained Omni's exact `7454334c...352aa` x64 DLL and no
  candidate provenance file. Run `20260801T053537Z-omni-baseline-a3` passed all
  gates: 1,144 mappings, two hook initializations, 24 reference DBVO misses,
  request removal, post-run sync, no crash and no exact-prefix survivors.
  Mapping installation took 3,131 ms and the three startup proxies were
  6,514.205, 5,923.916 and 12,741.897 ms.
- 2026-08-01: Candidate run
  `20260801T053743Z-disabled-call-logging-b3` passed all gates with the exact
  `26e290cb...debf` DLL, 1,144 mappings, two hook initializations, 24 reference
  DBVO misses, request removal, post-run sync, no crash and no prefix survivor.
  Mapping installation took 3,134 ms and the three startup proxies were
  6,530.421, 5,846.254 and 12,635.406 ms. This completes three valid candidate
  observations; one more rebuilt reference run supplies three validator-era A
  observations for the decision summary.
- 2026-08-01: Final reference run
  `20260801T053958Z-omni-baseline-a4` passed every automated gate with Omni's
  exact x64 DLL, 1,144 mappings, two hook initializations, 24 reference DBVO
  misses, no request/crash/process residue and post-run sync. While assembling
  the six-run table, the startup columns for some older captures became blank:
  the summarizer was rereading the original rotating `mo_interface` log even
  though the harness had already saved an immutable `interface-timeline.txt`.
  No raw timing evidence was lost. The summarizer now reads the captured
  timeline first, and future captures also persist `before_run_utc` directly in
  metadata; the live log is only a legacy fallback. Statistics are withheld
  until the corrected summarizer reproduces every per-run value.
- 2026-08-01: The corrected summarizer reproduced all six previously observed
  startup values from immutable captures. The three-A/three-B medians show
  -0.038% to Skyrim observation, -0.655% to ActorLimitFix, -0.531% to menu and
  -0.383% mapping-install time. Candidate 1 is accepted as behaviorally safe
  in the exercised workload but rejected as a useful performance change. The
  final portable/deployed state remains Omni's reference build.
- 2026-08-01: Implemented and verified the content-derived portable bundle
  identity. `./build.sh test` passed 18/18 and the required full `./build.sh`
  completed with a 15-entry manifest containing
  `fluorine-bundle-version.txt`. Independently recomputing the complete payload
  digest reproduced the recorded
  `f44bfe4c6046cced2eec07b72784e08e9f53f34027299a0515607c0eafbdd3fb`.
  Deploy-only capture
  `20260801T055858Z-bundle-identity-deploy-validation` forced the normal
  overlay, byte-verified the core, helper, x64/x86 DLLs and identity file, and
  verified installed marker
  `bundle:ab1536822d3d83179a8646c3e4af3e36b69cc99ffffa73d08951b0359ceaeba7`.
  No organizer survived the five-second deployment check. This supersedes the
  candidate helper's temporary core-mtime workaround for newly built bundles;
  the fallback remains solely for older portable directories.
- 2026-08-01: Completed the alternating exact-query-exhaustion series with
  B1/A5/B2/A6/B3/A7. All six captures passed the same mapping, hook,
  request-removal, post-sync, crash and exact-prefix cleanup gates. Relative to
  Omni, candidate medians were -0.829% for mapping installation, +0.314% to
  Skyrim observation, -1.616% to ActorLimitFix and -0.747% to the menu-plugin
  proxy. The later two proxies consistently moved about 95 ms earlier, but the
  primary observation did not improve and no proxy proves an interactive menu.
  The change remains an isolated, correctness-tested research candidate rather
  than the default payload.
- 2026-08-01: The wide-physical-filename and hash-duplicate-tracker candidates
  both completed the full x86/x64 Debug/Release Windows test matrix
  successfully in runs `30686678311` and `30686721391`. Their independent
  whole-tree format jobs failed on inherited files outside the candidate diffs.
  Both are now eligible for the deliberately limited runtime smoke tests
  documented above; no timing conclusion has been recorded yet.
- 2026-08-01: Wide-physical-filename smoke
  `20260801T061755Z-wide-physical-filename-smoke` passed with candidate SHA
  `6c8af83f...58c`, unchanged 1,144 mappings and 24 DBVO misses, both injected
  hooks, clean helper/sync/request/crash/process gates and ordinary reference-
  band startup proxies. It is a correctness/Unicode cleanup candidate; a
  single smoke is explicitly not used to claim a performance improvement.
- 2026-08-01: Hash-duplicate-tracker smoke
  `20260801T062031Z-hash-duplicate-tracker-smoke` passed with candidate SHA
  `b05a6259...5650`, 1,144 mappings, both hooks, 24 DBVO misses and clean
  lifecycle teardown. Its single-run proxies sit in the established reference
  band. In light of the prior ~0.25-second whole-category profile, it is a
  correctness pass and performance reject; no six-run series is warranted.
- 2026-08-01: Final Omni restore rebuilt the portable payload and deployed the
  exact `7454334c...352aa` DLL successfully. A chained provenance assertion
  then found the previous lab-only `fluorine-candidate-build.txt` still present
  beside the installed DLL. This did not affect the restored binary: the
  portable and installed DLL hashes were already identical to Omni. The
  updater intentionally overlays without deleting unknown files, so the lab
  harness now removes only that exact candidate marker when deploying a
  reference bundle, verifies candidate metadata byte-for-byte when present,
  and fails if stale candidate provenance survives a reference restore. The
  stale marker from the completed hash smoke was removed; no application,
  profile, prefix or user data was deleted.
- 2026-08-01: Added a deterministic two-thread/two-recursion-level test for
  `RecursiveBenaphore`. The unchanged reference implementation built cleanly in
  all four configurations, but its x64 Release test artifact failed both
  exclusion assertions under GE-Proton in a fresh temporary prefix, proving
  that the first waiter enters while another thread owns the lock. Commit
  `dee6f19` changes only the kernel semaphore's initial count from one to zero;
  commit `0647ffe` wires the new executable into every CI test job and
  `6908856` applies the formatter's alignment-only correction. Superseding green
  run `30688358000` is the acceptance gate before any game smoke or contention
  profiling.
- 2026-08-01: The superseding lock-fix matrix `30688358000` passed every x86/x64
  Debug/Release test, including all four focused semaphore executions. True
  North smoke `20260801T065752Z-recursive-benaphore-fix-smoke` then passed all
  runtime gates with candidate SHA `ca8680ff...9d71`, unchanged 1,144 mappings,
  both injected processes, the same 24 known DBVO misses and no new diagnostic,
  crash or process-residue class. This accepts the one-line exclusion repair as
  a correctness candidate, not as a measured startup optimization.
- 2026-08-01: Final full `./build.sh` and deploy-only capture
  `20260801T070038Z-final-omni-restore` restored both portable and installed x64
  DLLs to Omni's exact `7454334c...352aa` reference. The harness removed only
  its stale candidate-provenance marker, verified the complete deployment and
  left no candidate marker installed. Experimental DLLs are not the user's
  final runtime state.
- 2026-08-01: Extended the request-format test to cover enabled and disabled
  forced DLL entries, executable and library blacklists, suffix and directory
  skip lists, and exact end-of-file consumption. The final verification pass
  completed `./build.sh test` with 18/18 tests, a full `./build.sh`, `bash -n`
  for every benchmark helper, ShellCheck in a disposable container, and
  `git diff --check` without errors.
- 2026-08-01: Pushed the conservative combined candidate at USVFS commit
  `655c2cb5c11512b7d73725214fee33b535175e24` on branch
  `integration/wine-safe-candidates`. GitHub Actions run `30701877708` built
  x86 and x64 in Debug and Release and passed all 32 test-program executions,
  including the focused logger, recursive-benaphore and Unicode-directory
  tests plus the upstream injection, hook, VFS and global suites. The exact
  merged Release artifact's x64 DLL is 1,388,032 bytes with SHA-256
  `f498e6c07eaa4ba757e43c985d54f8ace27ba3884aeb1c49499bdeffd7453b68`.
  This records build provenance before runtime staging; it is not yet a True
  North result or a decision to replace the Omni reference payload.
- 2026-08-01: Combined candidate smoke
  `20260801T135028Z-wine-safe-combined-smoke` passed every runtime gate with
  exact DLL `f498e6c0...b68`, 1,144 mappings, both injected hooks, the same 24
  known DBVO misses, request removal, post-run synchronization, no new crash
  and no exact-prefix survivor. Mapping installation was 3,111 ms. This is a
  correctness acceptance only; a single observation is not a performance
  result.
- 2026-08-01: Replaced the first focus-preservation experiment after it was
  observed switching the user's KDE workspace. The harness now uses
  Gamescope's `headless` backend and creates no host window or virtual desktop.
  Deployment-only capture `20260801T135331Z-headless-deploy-validation` and
  20-second game capture
  `20260801T135343Z-wine-safe-combined-headless-validation` both passed. The
  latter initialized both hooks, installed 1,144 mappings in 3,112 ms, retained
  the reference count of 24 DBVO misses, synchronized cleanly, created no crash
  and left no process residue. Headless captures are correctness evidence and
  are benchmark-comparable only against other headless captures made on an
  otherwise idle machine.
- 2026-08-01: Added explicit `--allow-concurrent-load` support for an approved
  background correctness run. It records every other Wine-prefix process,
  process CPU/memory snapshots, logical CPU count and load average, labels the
  capture `EXPLORATORY_CONCURRENT_LOAD`, and never broadens cleanup beyond the
  exact Fluorine prefix. Capture
  `20260801T135625Z-wine-safe-combined-concurrent-correctness` ran alongside
  Overwatch, passed every lifecycle/hook/sync/crash/residue gate with 1,144
  mappings, and left Overwatch PID 438959 active. Mapping installation rose to
  3,513 ms at recorded load average 7.50 on 16 logical CPUs, illustrating why
  the timing is not a controlled performance result. It observed 15 known DBVO
  misses rather than the usual 24; this is a decrease, not a new error class,
  but the variation remains part of the exploratory capture.
- 2026-08-01: Performed the required full `./build.sh` after combined-candidate
  testing and used headless deploy-only capture
  `20260801T135737Z-final-omni-restore-headless` to restore the reference
  payload while Overwatch remained active in its separate prefix. Portable and
  installed x64 DLLs both have Omni's exact SHA-256 `7454334c...352aa`; both
  candidate provenance markers are absent. The installed runtime is therefore
  back on the known reference rather than the experimental combined DLL.
- 2026-08-01: Completed an explicitly exploratory alternating concurrent-load
  series while Overwatch remained active: combined B1, Omni A1, combined B2,
  Omni A2, combined B3, Omni A3. All six captures passed every automated
  validity gate with 1,144 mappings and no new warning, crash or residue class.
  Omni medians were 3,215 ms mapping installation, 5,571.775 ms to Skyrim,
  5,584.749 ms to ActorLimitFix and 12,482.788 ms to the menu proxy. Combined
  medians were 3,487 ms, 5,629.316 ms, 5,994.068 ms and 12,934.705 ms,
  respectively. Those apparent changes (+8.46%, +1.03%, +7.33% and +3.62%)
  are not accepted performance effects: per-run load averages ranged from 1.64
  to 7.50, both builds contain large opposing startup outliers, and the closest
  A1/B2 pair differs by only 6 ms mapping and 4.260 ms to Skyrim. The series
  establishes repeated correctness under contention and shows no compelling
  large speedup; an idle alternating series remains required for performance.
  Final A3 restored Omni's exact reference DLL and removed candidate markers.
- 2026-08-01: Completed the controlled idle `A/B/A/B/A/B` series after all
  unrelated game and Wine processes were closed. Every capture passed with
  exactly 1,144 mappings, two successful hook/process registrations, 24 known
  DBVO misses, request removal, post-run sync, no crash and no exact-prefix
  residue. Omni medians were 3,113 ms mapping (3,096–3,145; MAD 17),
  6,553.310 ms to Skyrim (6,538.426–6,554.935; MAD 1.625), 5,817.553 ms to
  ActorLimitFix (5,772.623–5,917.916; MAD 44.930), and 12,619.967 ms to the
  menu proxy (12,586.187–12,735.904; MAD 33.780). Combined medians were 3,112
  ms (3,112–3,121; MAD 0), 6,530.657 ms (6,511.075–6,556.672; MAD 19.582),
  5,827.171 ms (5,824.518–5,834.616; MAD 2.653), and 12,677.768 ms
  (12,657.742–12,694.180; MAD 16.412). Candidate deltas are therefore -1 ms
  (-0.032%), -22.653 ms (-0.346%), +9.618 ms (+0.165%), and +57.801 ms
  (+0.458%). The mixed sub-percent changes are performance-neutral and do not
  justify replacing Omni's DLL for startup speed. Final full `./build.sh` and
  deploy-only capture `20260801T171925Z-idle-combined-final-omni-restore`
  restored the exact `7454334c...352aa` reference and removed candidate
  provenance.
- 2026-08-01: Retained the combined Wine-safe branch as the profiling baseline
  rather than treating its mixed sub-percent result as grounds to discard the
  safe/correctness changes. USVFS commits `05e0ee4` and `debcba1` add and format
  an opt-in process-local profiler gated by `FLUORINE_USVFS_PROFILE=1`. It
  measures recursive context-lock wait/hold/contended counts and call sites,
  plus legacy/Ex directory API, information class, exact/wildcard/null pattern,
  buffer size and completion status. A following instrumentation slice also
  times physical parent-directory opens and regular versus virtual backing
  queries. It emits no paths and no per-call log messages. The superseding
  GitHub Windows matrix for final commit `41d637d` is the active build/test gate.
- 2026-08-01: Added `test/usvfs_benchmark` at fork commit `cb56386`. The opt-in
  Windows executable creates/reuses only a marker-owned seeded corpus with
  configurable 100K–1M logical loose files, directories, layers and collisions;
  it never recursively deletes the corpus. A hooked worker checks mapping
  winners and records JSON Lines for mapping construction, cold/warm existing
  and missing attributes, one-byte opens, exact searches, directory walks and
  multithreaded mixed probes. The game profiler will select which shapes deserve
  optimization; this workload supplies repeatability, not promotion evidence by
  itself.
- 2026-08-01: Extended the True North harness before the next candidate run.
  `--profile-usvfs` captures and validates nonzero profiler summaries. Root
  Builder state is now copied while Skyrim runs, every deployed file and backup
  is hashed, and post-run validity requires unbacked files/manifest to be absent
  and backed destinations to match their saved SHA-256. Fluorine also removes a
  stale empty Root Builder manifest during no-op cleanup. `bash -n` passes and
  `./build.sh test` remains green at 18/18; a full build and profiled game run
  remain pending until the corresponding USVFS artifact passes CI.
- 2026-08-01: The profiler/benchmark correction at USVFS commit
  `8ee1d57b17c6950b4cd174b564698915fdec33c8` passed the complete Windows
  matrix in GitHub Actions run `30711608974`: x86/x64 Debug/Release builds and
  every upstream/focused test passed. The Release x64 DLL has SHA-256
  `943f28bf14e5ecab188ec62b391dbb769385c90e647c71a23119b7435cc02b4f`;
  the matching benchmark executable has SHA-256
  `3bb121b25e601546edf42d6f5441edf457c19532e304344c14d5f5f5435833dc`.
  Follow-up `9368e20` makes the benchmark load its matching DLL from the
  executable directory, eliminating the artifact-layout workaround used for
  this first build.
- 2026-08-01: Generated smoke capture
  `20260801T181547Z-files1000-layers4-threads4` passed with zero correctness
  errors. It observed 2,400 physical parent opens costing 93.450 ms, 4,600
  virtual backing queries costing 28.816 ms, 2,656 end-of-search results and
  3,512 contended context-lock acquisitions costing 21.598 ms of cumulative
  wait. This established that the profiler and result checker agree on a small
  corpus before creating the durable 100K corpus.
- 2026-08-01: Generated 100K baseline capture
  `20260801T181603Z-files100000-layers8-threads8` passed every collision,
  lookup, open, missing-file, directory-listing and concurrency correctness
  check. The marker-owned corpus at
  `/home/luke/Games/VFS Benchmarks/usvfs-100k-v1` contains 100,000 logical
  assets represented by 180,001 physical files (704 MiB), with 10,000
  colliding names in each of eight layers. Mapping construction was 2,789.53
  ms; 100K existing-attribute passes were 1,003--1,011 ms, missing-attribute
  passes 2,679--2,713 ms, one-byte opens 4,357--4,497 ms, 10K exact collision
  searches 2,164--2,169 ms, 4,096 directory enumerations 7,151--7,217 ms and
  the 300K-probe/eight-thread mixed phase 2,694.83 ms.

  The same baseline recorded 6,447,463 context acquisitions, of which 639,995
  (9.926%) were contended, 12,457.079 ms cumulative wait and 19,444.972 ms
  cumulative hold. Attribute hooks account for essentially all measured lock
  contention. Directory work included 360,000 parent opens costing 14,047.195
  ms, 690,000 virtual backing queries costing 4,604.085 ms and 372,288 backing
  `NO_MORE_FILES` completions. Those cumulative per-thread times are workload
  attribution, not wall-clock time. They make the shared-context lock and
  exact-query exhaustion the next measurable candidates; they do not by
  themselves prove either implementation is safe.
- 2026-08-01: Profiled True North capture
  `20260801T181800Z-combined-profile-8ee1d57` passed every game, hook, request,
  sync, crash, process-lifecycle and Root Builder gate. Six Root Builder files
  were verified while live and every physical destination was restored
  byte-for-byte. Only the `usvfs_profile_summary` gate failed: the short-lived
  SKSE loader emitted 27 directory queries, while controlled termination of
  the long-lived game did not invoke normal DLL teardown and therefore emitted
  no summary. Commit `1feedf0` fixes measurement survivability by publishing
  cumulative, sequence-numbered snapshots every 10,000 directory calls with a
  reentrancy guard. The summarizer selects the latest snapshot for each
  process/category/source rather than summing cumulative records.
- 2026-08-01: Integrated the focused exact-query exhaustion candidate
  (`4d94e0c`) and its continuation/restart tests (`642db66`) into the combined
  branch. It remembers that a successful exact virtual match is exhausted and
  closes it on the caller's next continuation rather than issuing the known
  redundant backing query. It intentionally preserves the Windows API's
  externally visible successful first call and `NO_MORE_FILES` continuation;
  the next generated workload must confirm the predicted reduction in backing
  `NO_MORE_FILES` queries without changing any returned directory entry.
- 2026-08-01: Added an opt-in recursive reader/writer context-lock candidate at
  `6d76152`. `FLUORINE_USVFS_SHARED_CONTEXT=1` selects an SRW-lock-backed
  implementation with recursive reads, recursive writes and writer-to-read
  recursion. Reader-to-writer upgrade throws instead of deadlocking or racing,
  and cross-lock nesting is rejected. Directory search/custom-data and mapping
  removal sites known to mutate state now request write access. Focused tests
  require two readers to overlap, a writer to wait for both, recursion to work
  and upgrade to fail. The repaired `RecursiveBenaphore` remains the default;
  the shared candidate is not eligible for a game run until the generated
  concurrent workload passes in both modes.
- 2026-08-01: Added observation-only bounded cache-potential counters at
  `0dcea3f`. Two fixed 65,536-slot, direct-mapped hash tables measure repeat
  positive/negative redirection-tree resolutions and repeated final missing
  attribute outcomes. They normalize case and separators, record replacements
  and changed outcomes, and never serve or suppress a filesystem operation.
  This deliberately tests the workload premise without introducing stale
  state. A persistent database containing path, mtime, ctime and a content hash
  still cannot be a coherent hot-path cache by itself: it must also represent
  virtual priority/collisions and all in-process mutations, atomically
  invalidate parent and child answers, and define behavior when external
  processes change the tree. Hashing file contents would normally cost more
  I/O than the metadata lookup being avoided. No result-serving cache will be
  enabled until those generation and invalidation rules have executable tests.
- 2026-08-01: Pushed combined experimental head
  `0dcea3f987914ef90285680f4a2ca1b26c1ce23a` to
  `integration/wine-safe-candidates`; Windows build/test run `30712655206` is
  the active acceptance gate. The repository-wide lint run `30712655244`
  reports existing whole-tree formatting debt in upstream files; it did not
  name the new shared-lock, profiling or cache-observer sources. A green full
  build/test matrix, exact artifact hashes, generated default/shared A/B runs
  and a periodic-snapshot True North run remain required before accepting any
  runtime change.
- 2026-08-01: Build run `30712655206` rejected that head before artifacts were
  produced. MSVC found that the shared-lock audit had changed two delete paths
  to acquire `HookContext::Ptr`, while `RerouteW::removeMapping` still accepted
  only `HookContext::ConstPtr`; the other matrix jobs were cancelled by
  fail-fast. This was a useful type-level finding rather than a toolchain
  failure: removal can delete a redirection-tree node and update deletion/fake
  directory trackers, so it is a write operation. Commit `03f9204` changes the
  method contract and all five delete/move call sites to require
  `WRITE_CONTEXT()`. Replacement full-matrix run `30712988928` is the new gate;
  no rejected artifact was staged or executed. Fluorine was independently
  rebuilt through the required wrappers: `./build.sh test` passed 18/18 and
  the complete `./build.sh` portable build succeeded.
- 2026-08-01: Replacement GitHub Actions run `30712988928` passed the complete
  x86/x64 Debug/Release matrix and every upstream/focused test at USVFS commit
  `03f920430ffe31a0c20365b25ed6c3ef7751b8b1`. The exact Release x64 DLL has
  SHA-256 `bcb68274bbe49955c604ab76bb776a3c4c2835a64d468305aec5339644d0dcae`;
  its matching benchmark executable has SHA-256
  `b21186326f97e43fefb09d5495d29921e7b32882ee9f34181bf877711ff3bfdf`.
  The artifact was staged only after the successful full Fluorine build.
- 2026-08-01: Default/shared smoke captures
  `20260801T185150Z-files1000-layers4-threads4` and
  `20260801T185158Z-files1000-layers4-threads4` both passed every generated
  correctness check. Relative to the pre-exhaustion profiler baseline, the
  combined exact-query change reduced virtual backing queries from 4,600 to
  2,400 and backing `NO_MORE_FILES` completions from 2,656 to 456: exactly
  2,200 avoided continuation queries. The shared lock reduced 3,660 contended
  acquisitions to zero and the four-thread mixed phase from 19.776 to 14.779
  ms. This pair was only the escalation gate, not a performance claim.
- 2026-08-01: Completed alternating generated 100K captures A1/B1/A2/B2/A3/B3
  at `20260801T185218Z`, `185320Z`, `185422Z`, `185524Z`, `185634Z` and
  `185738Z`. All six reused the exact 180,001-file corpus and passed every
  lookup, missing, open, collision, enumeration and concurrency assertion with
  zero errors. One ProtonFixes manifest download timed out before B2 started;
  the benchmark's internal phase timers begin inside the executable and are
  unaffected, but the warning remains preserved in that capture.

  Default/shared medians in milliseconds were: mapping 2,779.54/2,800.08,
  existing attributes 1,042.73/1,049.23, missing attributes
  2,756.40/2,749.50, opens 4,377.22/4,422.18, exact searches
  2,210.64/2,211.66, directory enumeration 6,699.07/6,589.79 and eight-thread
  mixed probes 2,871.67/1,149.99. The serial phases are mixed and approximately
  neutral; the concurrent phase is 59.95% faster. Median cumulative lock wait
  fell from 13,490.685 to 425.516 ms (96.85%) and the approximately 654K
  contended acquisitions fell to zero. This accepts the shared lock as a
  synthetic concurrency candidate, not as the runtime default.

  Exact-query exhaustion reduced each 100K run to 360,000 virtual backing
  queries and 42,288 backing `NO_MORE_FILES` completions, versus 690,000 and
  372,288 in the pre-change baseline: 330,000 redundant backing calls removed.
  Exact-search wall time remained neutral, so this is a measured lifecycle
  cleanup without a speed claim. The tree observer saw 2,379,580 lookups, with
  about 1.179M same-slot repeats (49.6% lower-bound reuse) and 1.137M slot
  replacements. The 65,536-slot table is intentionally collision-heavy and
  undercounts reuse. The synthetic negative observer is not representative
  because that workload's missing probes use other attribute APIs.
- 2026-08-01: Completed alternating profiled True North captures A1/B1/A2/B2/
  A3/B3 at `20260801T185931Z`, `190134Z`, `190334Z`, `190520Z`, `190710Z` and
  `190855Z`. All six passed every validity gate with the exact candidate hash:
  1,144 mappings, two or more successful hooks/process registrations, 24 known
  DBVO misses, request removal, post-run sync, no crash, no prefix survivor,
  six live Root Builder deployments and byte-exact restoration. Periodic
  profiler snapshots were present in every run. A1's game exited naturally
  before the full dwell and is not used for full-duration profiler comparison;
  its startup anchors remain valid.

  Default/shared startup medians were 3,132/3,124 ms mapping (-0.26%),
  6,535.063/6,559.052 ms to Skyrim (+0.37%), 5,936.945/5,893.059 ms to
  ActorLimitFix (-0.74%) and 12,780.102/12,727.143 ms to the menu proxy
  (-0.41%). Those mixed sub-percent changes are performance-neutral. Across
  the two comparable full-duration default profiles and three shared profiles,
  shared locking reduced roughly 45.5K contended acquisitions to 31.9K
  (about 30%) and cumulative wait from about 1.71 seconds to 1.03 seconds
  (about 39%), but this did not become a repeatable startup improvement. Keep
  it opt-in pending broader mutation-heavy application coverage.

  The stable full game shape contained 289,468 physical parent opens costing
  11.7 seconds of cumulative attributed time and the same number of virtual
  backing queries, with 21,635 backing `NO_MORE_FILES` results. The bounded
  tree observer recorded 954,076 lookups and at least 644,635 same-slot repeats
  (67.6% lower-bound reuse); the `GetFileAttributesExW` negative observer
  recorded 380,884 missing results and at least 129,248 repeats (33.9%). High
  replacement counts (25.7% and 49.2%) confirm that these fixed tables
  undercount rather than safely identify cache entries. This supports building
  a collision-safe cache prototype only after a cross-process tree generation
  is added. It does not justify serving results from the observer or from a
  process-local mtime database.
- 2026-08-01: Added test-only exact virtual-directory ABI coverage at USVFS
  commit `36752a9`. It runs the legacy and Ex hooks across six layouts
  (`Directory`, `Full`, `Both`, `Names`, `IdBoth`, and `IdFull`) and validates
  the successful record, final zero offset/name decoding, exhausted
  continuation status, and restart success. This is 12 API/layout
  configurations and three lifecycle phases per configuration. It changes no
  runtime source and is the first executable prerequisite for packed results;
  small/boundary buffers, multi-entry chains, wildcard ordering and mutation
  between continuations are still deliberately outstanding. GitHub Actions run
  `30714319149` passed x86/x64 Debug/Release builds and every upstream/focused
  test. The independent whole-tree lint run `30714319151` still reports known
  formatting debt in six existing runtime/upstream files; it does not name the
  only file changed by this test commit, `test/tvfs_test/main.cpp`.
- 2026-08-01: Final deploy-only capture
  `20260801T191544Z-final-combined-03f9204-selected` passed. It installed and
  byte-compared the core, helper, DLLs, bundle identity and candidate metadata;
  the portable and installed x64 DLLs both have SHA-256
  `bcb68274bbe49955c604ab76bb776a3c4c2835a64d468305aec5339644d0dcae`
  and the marker identifies commit `03f9204` plus green workflow
  `30712988928`. No Fluorine/game/helper/Proton process belonging to the test
  remained. This is the selected combined runtime; shared context remains off
  by default and observer tables remain non-serving.
- 2026-08-01: Post-acceptance interactive testing reported a mixed winter/
  summer scene, specifically snow-covered objects alongside ordinary roads,
  and the user confirmed that the same scene was correct before the selected
  experimental DLL changes. Treat this as a candidate regression until an A/B
  visual reproduction proves otherwise.
  The corresponding launch at `22:36:06` installed all 1,144 mappings and
  initialized both hooks without a new VFS error class. Priority inspection
  shows seasonal/Lodgen outputs above the ordinary road/landscape providers.
  The newest save is in `WhiterunWorld`, where
  `Simplicity of Seasons/Seasons/SoS_Seasonspatch_WIN.ini` explicitly comments
  out the `WRMainRoadMarket -> WRMainRoadMarketWinter` swap while leaving the
  plains road swap enabled; both normal and snowy market meshes exist. This is
  a plausible pre-existing explanation for that particular mesh, but it cannot
  explain a before/after change on its own. The selected candidate is therefore
  withdrawn from visual acceptance pending the same-save comparison under the
  known Omni DLL and then the earlier safe combination. First bisect the
  exact-query exhaustion change because it is the only newly selected
  result-changing directory-enumeration optimization; shared context was off
  and the cache observers never serve data. Do not promote serving caches or
  packed results meanwhile.
- 2026-08-01: Implemented the one-at-a-time bisect requested after that report.
  USVFS commit `2f12a85` makes exact-query exhaustion strictly opt-in through
  `FLUORINE_USVFS_EXACT_QUERY_EXHAUSTION`; absent, `0`, and unrecognized values
  preserve the pre-shortcut continuation path. Its workflow runs the normal
  test suite with the gate off, then reruns the exact-query/ABI tests in a
  separate process with the gate on. Fluorine stores independent per-instance
  booleans under `fluorine/usvfs_exact_query_exhaustion` and
  `fluorine/usvfs_shared_context`, exposes both under Settings > Wine/Proton >
  VFS, passes normalized `0`/`1` values into the launch tree, and logs the
  selected pair. Benchmark scripts also force absent options to `0`, preventing
  an inherited shell variable from contaminating controls. Commit `687e890`
  fixes only the two new clang-format-22 alignment findings; the remaining
  formatter failures are pre-existing whole-tree debt.
- 2026-08-01: Required Fluorine `./build.sh test` passed 18/18 tests and the
  required full `./build.sh` package build completed. Deploy-only capture
  `20260802T035451Z-restore-omni-after-visual-regression` restored and verified
  the Omni x64 payload (`7454334c...352aa`) in both portable and installed
  locations. The visually withdrawn `bcb68274...dcae` payload is no longer the
  ordinary runtime.
- 2026-08-02: USVFS commit `687e890` passed GitHub Actions run `30731473176`:
  x86 and x64 Debug/Release builds, merged artifacts, and all four upstream
  test jobs passed. The workflow ran the ordinary suite with exact-query
  exhaustion off and the focused legacy/ABI tests in a separate process with
  it on. Whole-tree lint run `30731473177` still failed only the six documented
  pre-existing files; `ntdll.cpp` is no longer listed.
- 2026-08-02: The gated x64 artifact passed the 1,000-file smoke and 100K-file
  generated workload in all four configurations: off/off, exact/on only,
  shared/on only, and both/on. Every attribute, missing-file, open, exact-find,
  merged-directory, collision and eight-thread mixed result reported zero
  errors. Captures are:
  `20260802T052703Z-files100000-layers8-threads8-exactoff-sharedoff`,
  `20260802T052811Z-files100000-layers8-threads8-exacton-sharedoff`,
  `20260802T052914Z-files100000-layers8-threads8-exactoff-sharedon`, and
  `20260802T053017Z-files100000-layers8-threads8-exacton-sharedon`.
  Exact-only reduced virtual backing queries from 690,000 to 360,000 (47.8%)
  and cumulative virtual-query work from 4,537.503 to 3,197.817 ms (29.5%);
  its two warm merged-directory passes averaged 6,669.575 ms versus 7,100.185
  ms for control (6.1%). Shared-only reduced the 300K-operation eight-thread
  mixed phase from 2,815.70 to 1,138.90 ms (59.6%) and measured lock wait from
  13,009.020 to 425.275 ms. Both-on was effectively identical to shared-only
  for the mixed phase (1,138.44 ms) while retaining exact-query call removal.
  These are one matrix's operation measurements, not a three-series game
  percentage claim.
- 2026-08-02: The same artifact passed the headless True North/Root Builder
  harness in all four gate configurations. Captures
  `20260802T053148Z-gated-687e890-both-off`,
  `20260802T053407Z-gated-687e890-exact-only`,
  `20260802T053604Z-gated-687e890-shared-only`, and
  `20260802T053759Z-gated-687e890-both-on` each installed 1,144 mappings,
  initialized and registered SKSE plus Skyrim, retained the known 24 DBVO
  misses, produced no new crash, removed the request, completed post-run sync,
  deployed and restored all six Root Builder files, and left no exact-prefix
  process. Mapping installation was 3,191/3,183/3,128/3,189 ms respectively,
  which does not support a game-startup speed claim from these single fixed-
  dwell runs. The launch logs prove the intended false/true environment pair
  in every mode. Automated gates cannot inspect the rendered winter scene;
  same-save visual A/B remains mandatory before enabling exact by default.
- 2026-08-02: Human same-save inspection of the gated `687e890` artifact with
  exact-query exhaustion off and shared-context locking off showed the correct
  winter textures. This clears the gated base, disabled-logging cleanup,
  benaphore repair, wide-filename cleanup, and non-serving instrumentation as
  causes of the reported scene regression in this reproduction. The instance
  was then changed to exact-query on/shared-context off for the decisive
  one-change visual comparison; exact remains unaccepted until that inspection
  completes.
- 2026-08-02: Human inspection of the same save and scene with exact-query
  exhaustion on and shared-context locking off also showed the correct winter
  textures. Exact-query therefore did not reproduce the prior mixed-season
  scene in isolation with the gated artifact. The instance was switched to
  exact-query off/shared-context on for the next one-change comparison.
- 2026-08-02: Human inspection of the same save and scene with exact-query off
  and shared-context on also showed the correct winter textures. Shared-context
  did not reproduce the scene regression in isolation. The instance was then
  switched to exact-query on/shared-context on to test their interaction.
- 2026-08-02: Human inspection of the same save and scene with both exact-query
  exhaustion and shared-context locking on reproduced the broken/mixed texture
  state. Interface log `mo_interface_2026-08-02_01-05-53.log` confirms
  `exact_query_exhaustion=true shared_context=true`, 1,144 mappings, normal
  post-run plugin synchronization, and no configuration ambiguity. Because
  off/off, exact-only and shared-only were visually correct, the combined mode
  is rejected as an interaction regression even though its synthetic and
  headless correctness suites passed. The instance was immediately restored to
  exact-query off/shared-context off. Do not enable both gates together until
  the interaction is reproduced in a purpose-built directory enumeration test
  and fixed.
- 2026-08-02: Source audit after the combined-only reproduction found a concrete
  lifetime race matching the observed interaction. Both legacy and Ex directory
  hooks acquired `WRITE_CONTEXT()` only while locating/inserting a
  `Searches::Info` map entry, then released it while retaining the iterator and
  mutating `regularComplete`, `foundFiles`, search handles, virtual queues and
  the exact-query `currentVirtualMatchComplete` flag. Shared-context mode can
  therefore let another thread advance or erase that state. Exact-query changes
  the continuation state and timing enough to expose the race. USVFS commits
  `48169a9` and `d6e1186` protect the complete directory-query lifecycle in
  both APIs with the existing dedicated recursive search mutex. The broader
  context remains exclusive only while locating/initializing search state, then
  is released before backing I/O so shared-reader concurrency remains available
  to the attribute-heavy paths that produced the synthetic gain. `NtClose`
  takes the same search mutex before erasing an entry. The fix adds an eight-
  thread/same-handle exact-restart stress test and a separate CI invocation with
  both environment gates on. It is pending GitHub matrix, workload, game and
  same-save visual validation; the installed `687e890` artifact remains
  configured off/off meanwhile.
- 2026-08-02: USVFS commit `d6e1186` completed GitHub Actions build run
  `30735531508` successfully. All x86/x64 Debug/Release builds and all four
  upstream test jobs passed. The focused Release x64 job also ran the new
  eight-thread same-handle exact-restart stress test with both experimental
  gates enabled. The downloaded x64 DLL SHA-256 is
  `e1c0019714cccc02db45233dd3460ccae216fb3dfbc7234a92357fce2cbba35f`;
  the paired benchmark executable SHA-256 is
  `074f104f00d7bdd7d315d359cca77f0883ec9c8be7eef141700aff19d9111aea`.
- 2026-08-02: The exact CI artifact passed a 1,000-file both-on smoke and the
  complete four-way 100K generated-workload matrix with zero errors. Captures
  are `20260802T062715Z-files100000-layers8-threads8-exactoff-sharedoff`,
  `20260802T062819Z-files100000-layers8-threads8-exacton-sharedoff`,
  `20260802T062922Z-files100000-layers8-threads8-exactoff-sharedon`, and
  `20260802T062612Z-files100000-layers8-threads8-exacton-sharedon`. Combined
  mode retained the intended exact-query reduction (690,000 to 360,000
  virtual backing queries), reduced measured virtual-query work from
  4,583.715 to 3,110.333 ms, and reduced the 300K-operation eight-thread mixed
  phase from 2,817.17 to 1,146.67 ms. Its three directory-enumeration passes
  averaged 6,550.383 ms versus 7,176.267 ms for off/off. These are
  single-matrix operation results, not an end-to-end game percentage claim.
- 2026-08-02: The repaired both-on candidate passed headless True North/Root
  Builder capture `20260802T063126Z-d6e1186-search-state-fix-both-on`. It
  installed 1,144 mappings, initialized and registered SKSE plus Skyrim,
  retained the known 24 DBVO misses, produced no new crash, removed its
  request, completed post-run sync, deployed and restored all six Root Builder
  files, and left no process in the exact prefix. Mapping installation was
  3,135 ms and beforeRun-to-Skyrim was 6,609.694 ms; this single fixed-dwell
  run is a correctness gate rather than a timing claim. The exact candidate
  DLL is installed and both per-instance gates are enabled solely for the
  required same-save visual retest. If that scene is still mixed, immediately
  restore both gates to false and reject the candidate despite every automated
  pass.
- 2026-08-02: Human-window testing rejected `d6e1186` despite the headless
  pass. Interface log `mo_interface_2026-08-02_10-36-18.log` and USVFS log
  `usvfs-20260802-153619-168.log` prove that both gates were enabled, all 1,144
  mappings installed, SKSE and Skyrim injected successfully, ActorLimitFix
  initialized at 10:36:25 and MainMenuRandomizer initialized at 10:36:31.
  Nevertheless no usable game window appeared; after roughly two minutes the
  wrapper was stopped and recorded abnormal exit code 1. This reveals a blind
  spot in the headless gate: observing `SkyrimSE.exe` and main-menu plugin logs
  does not prove presentation/input readiness.
- 2026-08-02: The likely defect in `d6e1186` is its unconditional process-wide
  directory-query mutex. It both serializes unrelated directory handles and,
  after releasing the context while retaining the search mutex, permits a
  lock-order inversion when backing filesystem work re-enters a hook while a
  second thread holds the context and waits for the search mutex. The Skyrim
  instance was returned to exact=false/shared=false and diagnostic artifact
  `687e890` was restored in both portable and installed locations with SHA-256
  `73a5e8b68543fb3656161df1448a67022ef0bbf6bebe105bf482135d95b8319d`.
  Deploy-only capture `20260802T154142Z-restore-687-after-d6e1186-window-stall`
  verified the restore. The next candidate must use reference-counted
  per-handle search records, never wait for their lock while holding the
  context, and extend the concurrent restart test across both legacy and Ex
  directory APIs before any game test.
- 2026-08-02: USVFS commit `12b5e3f` implements that second repair. Each
  directory handle now owns a reference-counted `Searches::Info` and recursive
  mutex. Query hooks copy the shared record under the brief context write lock,
  release the context, and only then wait for that handle's mutex. Initialization
  may reacquire the context while holding the record because no close/query path
  waits for a record under the context. `NtClose` removes the shared record and
  search-handle mapping under the context, releases it, then waits for any
  in-flight query before closing the backing search handle. Restart resets the
  existing record while holding its mutex and now also closes the prior backing
  handle instead of dropping it. Unrelated directory handles no longer
  serialize. The eight-thread same-handle stress test now mixes legacy and Ex
  restart calls.
- 2026-08-02: GitHub build run `30760697935` completed successfully for
  `12b5e3f`. All x86/x64 Debug/Release builds, all four corresponding test jobs,
  both focused gate combinations, and the upstream global/injection tests
  passed. The exact Release x64 artifact hashes are
  `3744a748fadbb60e55c8bc8c9d0ce20d21c2f6c8dcc95b7a38d78271d62b989c`
  for `usvfs_x64.dll` and
  `7114d8da28da35e60044c57b27dd20dd18421d972f45811ad6a6f4f6f2d22125`
  for the paired benchmark executable. The lint workflow named only six known
  pre-existing files; neither changed file was among them.
- 2026-08-02: Two initial 1K both-on smoke runs completed all 13 workload rows
  with zero errors and logged `vfs unloaded`, but the wrapper sampled one
  Proton service PID immediately after Proton returned. Each PID disappeared
  before manual inspection. The wrapper now records initial and final
  exact-prefix PID sets and waits at most forty 250 ms intervals for natural
  service shutdown; it neither broad-matches nor kills Wine/Proton processes.
  Repeat capture
  `20260802T182944Z-files1000-layers4-threads8-exacton-sharedon` passed after
  one interval, with an empty final PID set.
- 2026-08-02: The exact `12b5e3f` CI artifact passed the full four-way 100K
  generated-workload matrix with zero errors:
  `20260802T182957Z-files100000-layers8-threads8-exactoff-sharedoff`,
  `20260802T183105Z-files100000-layers8-threads8-exacton-sharedoff`,
  `20260802T183209Z-files100000-layers8-threads8-exactoff-sharedon`, and
  `20260802T183312Z-files100000-layers8-threads8-exacton-sharedon`. Both-on
  retained the intended virtual backing-query reduction from 690,000 to
  360,000. Because the first control paid a cold-cache penalty, performance
  conclusions use the later warmed pair instead of its total time.
- 2026-08-02: Warmed captures
  `20260802T183444Z-files100000-layers8-threads8-exactoff-sharedoff` and
  `20260802T183550Z-files100000-layers8-threads8-exacton-sharedon` both passed
  with zero errors. Both-on reduced mean directory-enumeration time from
  7,220.467 to 6,617.383 ms (8.35%), the 300K-operation mixed eight-thread
  phase from 2,791.50 to 1,166.14 ms (58.23%), and the sum of synthetic phase
  times from 58,554.16 to 54,995.42 ms (6.08%). These are workload-local
  measurements, not an end-to-end game-load percentage claim.
- 2026-08-02: Strengthened True North capture
  `20260802T183723Z-12b5e3f-per-handle-both-on` passed every gate with the exact
  CI DLL. It installed 1,144 mappings, initialized and registered SKSE plus
  Skyrim, observed both DXVK initialization and a Gamescope render surface,
  retained the known 24 DBVO misses, produced no crash, removed its request,
  completed post-run sync, restored all six Root Builder files, produced a
  profile summary, and left no exact-prefix process. Mapping installation was
  3,090 ms. The candidate was then removed from both portable and installed
  bundles; deploy-only capture
  `20260802T184005Z-restore-687-after-12b5e3f-headless` verified restored
  diagnostic artifact `687e890` with SHA-256
  `73a5e8b68543fb3656161df1448a67022ef0bbf6bebe105bf482135d95b8319d`.
  Both instance gates remained false pending normal visible-window and
  same-save visual testing.
- 2026-08-02: Human same-save capture
  `20260802T184300Z-12b5e3f-human-visual` originally appeared to reject the
  per-handle repair. The
  exact CI DLL SHA-256 was
  `3744a748fadbb60e55c8bc8c9d0ce20d21c2f6c8dcc95b7a38d78271d62b989c`,
  and the interface log explicitly recorded exact-query exhaustion=true and
  shared-context=true with 1,144 mappings. USVFS initialized and registered
  both SKSE and Skyrim, mapping installation took 3,106 ms, the helper exited
  normally, the known 24 DBVO misses were unchanged, Root Builder cleared all
  six deployed files, and INI/plugin sync completed. Nevertheless the user
  observed that the affected winter scene was still mixed/incorrect. On
  2026-08-05 the user reported that a mod under active development was likely
  responsible for the mixed assets. This invalidates the run as a controlled
  USVFS visual rejection: retain its logs, but do not use it to infer that the
  directory-search repair caused the scene. The candidate remains experimental
  and off until a clean fixed-mod-state A/B is recorded.
- 2026-08-02: After the visual rejection, no Skyrim/SKSE/USVFS process remained.
  Both instance gates were reset to false, candidate provenance was removed,
  and deploy-only capture
  `20260802T184605Z-restore-687-after-12b5e3f-visual-reject` verified portable
  and installed x64 SHA-256
  `73a5e8b68543fb3656161df1448a67022ef0bbf6bebe105bf482135d95b8319d`.
  This is gated diagnostic artifact `687e890`, not Omni's short-name-only
  payload. It includes the short-name patch, visually cleared disabled-logging
  cleanup, benaphore repair, wide-filename cleanup, non-serving instrumentation,
  and both experimental implementations disabled. Omni's narrower reference
  DLL is `7454334c1ea246a68ff8da492b5d63dae8cd2f1298f2d7105c920b5f593352aa`.
- 2026-08-02: Investigated reports that Fluorine sometimes appears to index the
  same game again, including after reboot. The catalog always walks provider
  trees to validate cheap stat fingerprints, but its progress dialog called
  that verification "Indexing game files" even when zero content hashes were
  calculated. A separate correctness defect used the caller's literal path as
  both the catalog database hash and provider key. On this Bazzite host,
  `/home/luke` resolves to `/var/home/luke`, and existing catalogs contain both
  spellings, so launch-context path aliases could select separate databases or
  miss provider rows for the same files. The implementation now derives only
  persistent catalog identities from weakly canonical, lexically normalized
  paths while retaining the caller's path for filesystem access. Reconcile,
  in-session base snapshots, forced refreshes, invalidations and overwrite
  duplicate review all use the same identity. The dialog now says
  "Verifying game files" during metadata checks and changes to "Indexing
  changed game files" only after a fingerprint miss. Completion diagnostics
  count total and uncached misses plus device, inode, size, mode, mtime, ctime
  and missing-digest causes; reasons may overlap for one file. `st_dev` remains
  part of the safety fingerprint until real post-reboot logs show that it is
  the source of false misses. A symlink-alias regression proves both spellings
  select the same database, reuse hashes on the second reconcile, retain the
  same profile root, expose canonical provider roots and load the base snapshot
  through either spelling. It also proves an alias-addressed forced refresh is
  warm on the next real-path reconcile and that alias-addressed invalidation
  removes the real-path row. The final required `./build.sh test` passed all 19
  tests and the final required full `./build.sh` portable package completed
  successfully. This is cache-correctness and observability evidence, not a
  performance claim; no USVFS payload changed and no game benchmark was
  required for this catalog-identity repair.
- 2026-08-05: Created annotated tag `v0.5.7.2-wine-shortname.2` at exact
  short-name commit `644eebf` to obtain fork-owned Windows artifacts. Workflow
  run `31044442007` failed before compilation because the historical workflow
  expanded the unavailable upstream Azure cache variables to
  `clear;x-azblob,,,readwrite`. No artifact or release was produced, and the
  failed tag remains as an audit record.
- 2026-08-05: Release tag `v0.5.7.2-wine-shortname.3` peels to `836b2d9`. Its
  application diff from upstream `v0.5.7.2` remains only short-name commit
  `644eebf`; commits `a7c5fee` and `836b2d9` change only the workflow to use
  the fork's GitHub Actions vcpkg cache and quote the environment output path.
  Full matrix run `31044652426` passed all x86/x64 Debug/Release builds, all
  four test jobs, both artifact merges and the publish job. The resulting
  prerelease archive is
  `usvfs_v0.5.7.2-wine-shortname.3.7z`, SHA-256
  `91e24d6971e8f9f084d60d2f372a5c6d816587a83f2683737c22e643eb40c133`;
  its Release DLL hashes are `56728c79...dd4a` x64 and
  `41578356...5a54` x86.
- 2026-08-05: Fluorine now downloads that immutable release archive directly
  and verifies both the archive and license before extracting all four runtime
  files. The first full package attempt failed its new post-build hash gate
  because CMake's helper custom command copied DLLs only when the helper itself
  rebuilt, leaving the prior Omni bytes in an incremental build. The runtime
  copy is now an always-run `fluorine-usvfs-runtime` target. A repeated
  `./build.sh test` passed 19/19 and a repeated required `./build.sh` verified
  both x64/x86 hashes in staging and the portable bundle.
- 2026-08-05: Headless capture
  `20260805T205106Z-shortname-release-836b2d9-headless` passed every True
  North/Root Builder gate with exact-query and shared-context experiments off:
  two hook initializations, 1,144 mappings, DXVK and Gamescope surface, the
  known 24 DBVO misses, all six Root Builder files restored, no new crash,
  request removal, post-run sync and no exact-prefix survivors. Portable and
  installed x64 hashes both equal `56728c79...dd4a`. The GitHub release remains
  a prerelease pending human same-save/scene verification; no performance
  claim is made from this one correctness run.
- 2026-08-05: The user reported that the mod responsible for the affected
  assets was itself under active development during the earlier visible tests
  and is now the likely source of the mixed scene. The logs and asset
  observations remain recorded, but the causal rejection of `12b5e3f` and
  `c7a72e7` is withdrawn as confounded. This does not automatically promote the
  shared-context work: it remains opt-in/off because a clean fixed-mod-state
  visual A/B and performance justification are still absent. The narrower
  short-name-only `v0.5.7.2-wine-shortname.3` payload is approved for public
  nightly trial with exact-query and shared-context experiments off.
