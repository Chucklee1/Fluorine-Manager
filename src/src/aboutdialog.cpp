/*
Copyright (C) 2014 Sebastian Herbord. All rights reserved.

This file is part of Mod Organizer.

Mod Organizer is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Mod Organizer is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Mod Organizer.  If not, see <http://www.gnu.org/licenses/>.
*/

#include "aboutdialog.h"
#include "shared/util.h"
#include "ui_aboutdialog.h"
#include <fluorine_build_info.h>
#include <utility.h>

#include <QApplication>
#include <QFontDatabase>
#include <QLabel>
#include <QListWidget>
#include <QListWidgetItem>
#include <QTextBrowser>
#include <QVariant>
#include <Qt>

AboutDialog::AboutDialog(const QString& version, QWidget* parent)
    : QDialog(parent), ui(new Ui::AboutDialog)
{
  ui->setupUi(this);

  m_LicenseFiles[LICENSE_LGPL3]   = "LGPL-v3.0.txt";
  m_LicenseFiles[LICENSE_LGPL21]  = "GNU-LGPL-v2.1.txt";
  m_LicenseFiles[LICENSE_GPL3]    = "GPL-v3.0.txt";
  m_LicenseFiles[LICENSE_GPL2]    = "GPL-v2.0.txt";
  m_LicenseFiles[LICENSE_BOOST]   = "boost.txt";
  m_LicenseFiles[LICENSE_7ZIP]    = "7zip.txt";
  m_LicenseFiles[LICENSE_CCBY3]   = "BY-SA-v3.0.txt";
  m_LicenseFiles[LICENSE_ZLIB]    = "zlib.txt";
  m_LicenseFiles[LICENSE_PYTHON]  = "python.txt";
  m_LicenseFiles[LICENSE_SSL]     = "openssl.txt";
  m_LicenseFiles[LICENSE_CPPTOML] = "cpptoml.txt";
  m_LicenseFiles[LICENSE_UDIS]    = "udis86.txt";
  m_LicenseFiles[LICENSE_SPDLOG]  = "spdlog.txt";
  m_LicenseFiles[LICENSE_FMT]     = "fmt.txt";
  m_LicenseFiles[LICENSE_SIP]     = "sip.txt";
  m_LicenseFiles[LICENSE_CASTLE]  = "Castle.txt";
  m_LicenseFiles[LICENSE_ANTLR]   = "AntlrBuildTask.txt";
  m_LicenseFiles[LICENSE_DXTEX]   = "DXTex.txt";
  m_LicenseFiles[LICENSE_VDF]     = "ValveFileVDF.txt";

  addLicense("Qt", LICENSE_LGPL3);
  addLicense("Qt Json", LICENSE_GPL3);
  addLicense("Boost Library", LICENSE_BOOST);
  addLicense("7-zip", LICENSE_7ZIP);
  addLicense("ZLib", LICENSE_NONE);
  addLicense("Tango Icon Theme", LICENSE_NONE);
  addLicense("RRZE Icon Set", LICENSE_CCBY3);
  addLicense("Icons by Lorc, Delapouite and sbed available on http://game-icons.net",
             LICENSE_CCBY3);
  addLicense("Castle Core", LICENSE_CASTLE);
  addLicense("ANTLR", LICENSE_ANTLR);
  addLicense("LOOT", LICENSE_GPL3);
  addLicense("Python", LICENSE_PYTHON);
  addLicense("OpenSSL", LICENSE_SSL);
  addLicense("cpptoml", LICENSE_CPPTOML);
  addLicense("Udis86", LICENSE_UDIS);
  addLicense("spdlog", LICENSE_SPDLOG);
  addLicense("{fmt}", LICENSE_FMT);
  addLicense("SIP", LICENSE_SIP);
  addLicense("DXTex Headers", LICENSE_DXTEX);
  addLicense("Valve File VDF Reader", LICENSE_VDF);

  // Show Fluorine Manager's own version instead of the upstream MO2 engine
  // version. The incoming
  // `version` parameter is the engine version string and is retained on the
  // revision line for reference.
  QString displayVersion = QStringLiteral(FLUORINE_DISPLAY_VERSION);
  if (FLUORINE_IS_NIGHTLY_BUILD) {
    displayVersion += QStringLiteral(" (nightly)");
  }
  ui->nameLabel->setText(
      QString("<span style=\"font-size:12pt; font-weight:600;\">%1 %2</span>")
          .arg(ui->nameLabel->text())
          .arg(displayVersion));

  QString revision = ui->revisionLabel->text() +
                     QStringLiteral(" MO2 engine ") + version;
  const QString commit = QStringLiteral(FLUORINE_BUILD_COMMIT);
  if (!commit.isEmpty()) {
    revision += QStringLiteral(" · ") + commit;
  }
#if defined(HGID)
  revision += QStringLiteral(" · ") + HGID;
#elif defined(GITID)
  revision += QStringLiteral(" · ") + GITID;
#endif
  ui->revisionLabel->setText(revision);

  ui->usvfsLabel->setText(ui->usvfsLabel->text() + " FUSE 3");
  ui->licenseText->setFont(QFontDatabase::systemFont(QFontDatabase::FixedFont));
}

AboutDialog::~AboutDialog()
{
  delete ui;
}

void AboutDialog::addLicense(const QString& name, Licenses license)
{
  QListWidgetItem* item = new QListWidgetItem(name);
  item->setData(Qt::UserRole, license);
  ui->creditsList->addItem(item);
}

void AboutDialog::on_creditsList_currentItemChanged(QListWidgetItem* current,
                                                    QListWidgetItem*)
{
  auto iter = m_LicenseFiles.find(current->data(Qt::UserRole).toInt());
  if (iter != m_LicenseFiles.end()) {
    QString const filePath = qApp->applicationDirPath() + "/licenses/" + iter->second;
    QString const text     = MOBase::readFileText(filePath);
    ui->licenseText->setText(text);
  } else {
    ui->licenseText->setText(tr("No license"));
  }
}

void AboutDialog::on_sourceText_linkActivated(const QString& link)
{
  MOBase::shell::Open(QUrl(link));
}
