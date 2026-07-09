#include "sleepinhibitor.h"

#include <log.h>

#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>

using namespace MOBase;

namespace
{
const QString Login1Service   = QStringLiteral("org.freedesktop.login1");
const QString Login1Path      = QStringLiteral("/org/freedesktop/login1");
const QString Login1Interface = QStringLiteral("org.freedesktop.login1.Manager");
}  // namespace

SleepInhibitor::SleepInhibitor(QObject* parent) : QObject(parent)
{
  const bool sleepConnected = QDBusConnection::systemBus().connect(
      Login1Service, Login1Path, Login1Interface, QStringLiteral("PrepareForSleep"),
      this, SLOT(onPrepareForSleep(bool)));
  const bool shutdownConnected = QDBusConnection::systemBus().connect(
      Login1Service, Login1Path, Login1Interface, QStringLiteral("PrepareForShutdown"),
      this, SLOT(onPrepareForShutdown(bool)));

  if (!sleepConnected || !shutdownConnected) {
    log::debug("could not subscribe to logind sleep/shutdown signals — system "
               "bus unavailable? suspend/shutdown prompts will show the generic "
               "systemd reason instead of Fluorine's");
  }
}

SleepInhibitor::~SleepInhibitor()
{
  release();
}

void SleepInhibitor::setActive(bool active, const QString& reason)
{
  m_active = active;
  m_reason = reason;

  if (active) {
    acquire();
  } else {
    release();
  }
}

void SleepInhibitor::acquire()
{
  if (m_lock.isValid() || m_acquiring) {
    return;
  }

  QDBusMessage msg = QDBusMessage::createMethodCall(
      Login1Service, Login1Path, Login1Interface, QStringLiteral("Inhibit"));
  msg << QStringLiteral("sleep:shutdown") << QStringLiteral("Fluorine") << m_reason
      << QStringLiteral("delay");

  // Async: this runs on every game launch (FuseConnector::mount() on the GUI
  // thread), and a blocking call here would stall the whole UI if logind/the
  // system bus is briefly slow or unavailable.
  m_acquiring = true;
  auto* watcher =
      new QDBusPendingCallWatcher(QDBusConnection::systemBus().asyncCall(msg), this);
  connect(watcher, &QDBusPendingCallWatcher::finished, this,
          [this](QDBusPendingCallWatcher* w) {
            w->deleteLater();
            m_acquiring = false;

            const QDBusPendingReply<QDBusUnixFileDescriptor> reply = *w;
            if (reply.isError()) {
              log::warn("failed to acquire logind inhibitor lock: {}",
                       reply.error().message().toStdString());
              return;
            }
            if (!m_active) {
              // setActive(false) landed while the request was in flight —
              // let the just-received fd close instead of holding a lock
              // nothing wants anymore.
              return;
            }
            m_lock = reply.value();
            log::debug("acquired logind sleep/shutdown inhibitor: {}",
                      m_reason.toStdString());
          });
}

void SleepInhibitor::release()
{
  if (!m_lock.isValid()) {
    return;
  }

  m_lock = QDBusUnixFileDescriptor();
  log::debug("released logind sleep/shutdown inhibitor");
}

void SleepInhibitor::onPrepareForSleep(bool start)
{
  // Just release so the system can proceed, then reacquire on resume — the
  // lock's only job is descriptive labeling, not gating the actual sleep.
  if (start) {
    release();
  } else if (m_active) {
    acquire();
  }
}

void SleepInhibitor::onPrepareForShutdown(bool start)
{
  // Symmetric with onPrepareForSleep: a "start=true" shutdown can still be
  // cancelled by another inhibitor or the user, in which case logind emits
  // "start=false" and we need to reacquire — otherwise a cancelled shutdown
  // would leave us silently uninhibited for the rest of the session.
  if (start) {
    release();
  } else if (m_active) {
    acquire();
  }
}
