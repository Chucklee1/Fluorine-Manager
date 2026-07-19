#include "steamdetection.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QTemporaryDir>
#include <gtest/gtest.h>

namespace
{
void createFile(const QString& path)
{
  ASSERT_TRUE(QDir().mkpath(QFileInfo(path).absolutePath()));
  QFile file(path);
  ASSERT_TRUE(file.open(QIODevice::WriteOnly));
}
}  // namespace

TEST(ProtonDetection, FindsHeroicRunnerWithoutSteamLibraries)
{
  QTemporaryDir temporary;
  ASSERT_TRUE(temporary.isValid());

  const QString runner = QDir(temporary.path()).filePath("GE-Proton-latest");
  createFile(QDir(runner).filePath("proton"));
  createFile(QDir(runner).filePath("files/bin/wine"));

  const QVector<SteamProtonInfo> protons =
      findProtonsForPaths({}, {temporary.path()});

  ASSERT_EQ(protons.size(), 1);
  EXPECT_EQ(protons[0].name, QStringLiteral("GE-Proton-latest"));
  EXPECT_EQ(QDir::cleanPath(protons[0].path), QDir::cleanPath(runner));
  EXPECT_FALSE(protons[0].is_steam_proton);
}

TEST(ProtonDetection, RejectsRunnerWithoutWineBinary)
{
  QTemporaryDir temporary;
  ASSERT_TRUE(temporary.isValid());

  const QString runner = QDir(temporary.path()).filePath("GE-Proton-latest");
  createFile(QDir(runner).filePath("proton"));

  EXPECT_TRUE(findProtonsForPaths({}, {temporary.path()}).isEmpty());
}

TEST(ProtonDetection, DeduplicatesCanonicalRunnerPaths)
{
  QTemporaryDir temporary;
  ASSERT_TRUE(temporary.isValid());

  const QString runner = QDir(temporary.path()).filePath("GE-Proton-latest");
  createFile(QDir(runner).filePath("proton"));
  createFile(QDir(runner).filePath("files/bin/wine"));

  const QVector<SteamProtonInfo> protons =
      findProtonsForPaths({}, {temporary.path(), temporary.path()});

  ASSERT_EQ(protons.size(), 1);
}
