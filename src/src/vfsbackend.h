#ifndef VFSBACKEND_H
#define VFSBACKEND_H

#include <QString>
#include <QStringList>
#include <QStringView>

enum class VfsBackend
{
  Fuse,
  Usvfs,
};

inline constexpr auto kVfsBackendSetting = "fluorine/vfs_backend";
inline constexpr auto kUsvfsExactQueryExhaustionSetting =
    "fluorine/usvfs_exact_query_exhaustion";
inline constexpr auto kUsvfsSharedContextSetting =
    "fluorine/usvfs_shared_context";
inline constexpr auto kUsvfsExactQueryExhaustionEnvironment =
    "FLUORINE_USVFS_EXACT_QUERY_EXHAUSTION";
inline constexpr auto kUsvfsSharedContextEnvironment =
    "FLUORINE_USVFS_SHARED_CONTEXT";
inline constexpr auto kUsvfsLauncherExecutable =
    "fluorine-usvfs-launcher.exe";

VfsBackend parseVfsBackend(QStringView value);
QString vfsBackendSettingValue(VfsBackend backend);

// Parse an optional launch-only experiment override. Unknown values preserve
// the per-instance fallback instead of accidentally enabling an experiment.
bool parseUsvfsExperimentFlag(QStringView value, bool fallback);

// USVFS is a Windows API-hooking VFS. Native Linux executables always use
// FUSE even when an instance prefers USVFS for its Wine/Proton executables.
bool useUsvfsForLaunch(VfsBackend backend, bool useProton,
                       bool gameUsesOrganizerVfs = true);

// The Wine-side helper deliberately remains alive until every process
// registered with USVFS has exited. When it is in use, it is therefore the
// lifetime anchor for post-run synchronization; tracking a short-lived script
// extender would run afterRun() while the real game is still active.
QStringList processTrackingExecutables(const QStringList& targetExecutables,
                                       bool usingUsvfsHelper);

// Translate an absolute host path into Wine's default Z: mapping. Existing
// DOS/UNC paths are normalized but otherwise preserved.
QString toWinePath(const QString& path);

#endif
