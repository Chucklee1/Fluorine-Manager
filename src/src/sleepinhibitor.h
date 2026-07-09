#ifndef SLEEPINHIBITOR_H
#define SLEEPINHIBITOR_H

#include <QDBusUnixFileDescriptor>
#include <QObject>
#include <QString>

// Holds a systemd-logind inhibitor lock (org.freedesktop.login1) while
// Fluorine's FUSE VFS is mounted, purely so a suspend/shutdown/lock attempt
// shows Fluorine's own reason instead of the generic, unidentifiable
// "systemd (1)".
//
// This deliberately does NOT try to unmount the VFS during the inhibitor's
// delay window. The FUSE mount's lifetime tracks the running game's lifetime
// (see OrganizerCore::afterRun — USVFS is only active while the game process
// is running, mirroring Windows), so there is no window where the mount is
// live but safe to tear down out from under it. A normal, un-forced
// suspend/resume or shutdown is safe as-is: Fluorine's own process (serving
// the FUSE session) pauses/resumes or exits together with the rest of the
// system, so nothing gets yanked. The only unsafe case is a user forcing the
// prompt through anyway — which this class can't prevent, only make
// informative instead of cryptic.
class SleepInhibitor : public QObject
{
  Q_OBJECT

public:
  explicit SleepInhibitor(QObject* parent = nullptr);
  ~SleepInhibitor() override;

  // Acquires the lock (with `reason` shown to the user) when active, drops
  // it otherwise. Safe to call repeatedly with the same state.
  void setActive(bool active, const QString& reason);

private slots:
  void onPrepareForSleep(bool start);
  void onPrepareForShutdown(bool start);

private:
  void acquire();
  void release();

  QDBusUnixFileDescriptor m_lock;
  QString m_reason;
  bool m_active    = false;
  bool m_acquiring = false;
};

#endif  // SLEEPINHIBITOR_H
