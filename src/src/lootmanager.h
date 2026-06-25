#ifndef LOOTMANAGER_H
#define LOOTMANAGER_H

#include <QString>
#include <functional>

/// Returns the LOOT install directory: ~/.local/share/fluorine/tools/loot
QString lootInstallDir();

/// Returns true if LOOT.exe is present in the tools directory.
bool isLootInstalled();

/// Returns the path to LOOT.exe, or empty if not installed.
QString getLootExePath();

/// Download and install LOOT from the latest GitHub release.
/// Finds the win64 .7z asset, extracts to lootInstallDir().
/// Returns empty string on success, or an error message.
QString downloadLoot(const std::function<void(float)>& progressCb,
                     const std::function<void(const QString&)>& statusCb,
                     const int* cancelFlag = nullptr);

#endif  // LOOTMANAGER_H
