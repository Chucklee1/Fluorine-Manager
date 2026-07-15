#include <gtest/gtest.h>

#include <esptk/espexceptions.h>
#include <esptk/espfile.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <set>
#include <string>
#include <string_view>
#include <vector>

namespace
{

using Bytes = std::vector<unsigned char>;

void append(Bytes& bytes, std::string_view value)
{
  bytes.insert(bytes.end(), value.begin(), value.end());
}

void appendLittleEndian32(Bytes& bytes, uint32_t value)
{
  bytes.push_back(static_cast<unsigned char>(value));
  bytes.push_back(static_cast<unsigned char>(value >> 8));
  bytes.push_back(static_cast<unsigned char>(value >> 16));
  bytes.push_back(static_cast<unsigned char>(value >> 24));
}

void writeLittleEndian32(Bytes& bytes, size_t offset, uint32_t value)
{
  bytes[offset]     = static_cast<unsigned char>(value);
  bytes[offset + 1] = static_cast<unsigned char>(value >> 8);
  bytes[offset + 2] = static_cast<unsigned char>(value >> 16);
  bytes[offset + 3] = static_cast<unsigned char>(value >> 24);
}

void writeFloat(Bytes& bytes, size_t offset, float value)
{
  uint32_t bits = 0;
  static_assert(sizeof(bits) == sizeof(value));
  std::memcpy(&bits, &value, sizeof(bits));
  writeLittleEndian32(bytes, offset, bits);
}

Bytes makeHedr(float version, uint32_t fileType, std::string_view author,
               std::string_view description, uint32_t recordCount)
{
  Bytes header(300, 0);
  writeFloat(header, 0, version);
  writeLittleEndian32(header, 4, fileType);
  std::copy_n(author.begin(), std::min<size_t>(author.size(), 32), header.begin() + 8);
  std::copy_n(description.begin(), std::min<size_t>(description.size(), 256),
              header.begin() + 40);
  writeLittleEndian32(header, 296, recordCount);
  return header;
}

void appendSubrecord(Bytes& payload, std::string_view type, const Bytes& data)
{
  ASSERT_EQ(type.size(), 4);
  append(payload, type);
  appendLittleEndian32(payload, static_cast<uint32_t>(data.size()));
  payload.insert(payload.end(), data.begin(), data.end());
}

Bytes makePlugin(const Bytes& payload, const Bytes& trailing = {})
{
  Bytes file;
  append(file, "TES3");
  appendLittleEndian32(file, static_cast<uint32_t>(payload.size()));
  appendLittleEndian32(file, 0);
  appendLittleEndian32(file, 0);
  file.insert(file.end(), payload.begin(), payload.end());
  file.insert(file.end(), trailing.begin(), trailing.end());
  return file;
}

class TemporaryPlugin
{
public:
  explicit TemporaryPlugin(const Bytes& contents,
                           std::string_view suffix = ".esp")
  {
    static std::atomic_uint64_t counter{0};
    const auto id = static_cast<uint64_t>(
                        std::chrono::steady_clock::now().time_since_epoch().count()) +
                    counter++;
    m_Path = std::filesystem::temp_directory_path() /
             ("fluorine-esptk-" + std::to_string(id) + std::string(suffix));

    std::ofstream file(m_Path, std::ios::binary);
    if (!contents.empty()) {
      file.write(reinterpret_cast<const char*>(contents.data()),
                 static_cast<std::streamsize>(contents.size()));
    }
    file.close();
  }

  ~TemporaryPlugin()
  {
    std::error_code ignored;
    std::filesystem::remove(m_Path, ignored);
  }

  const std::filesystem::path& path() const { return m_Path; }

private:
  std::filesystem::path m_Path;
};

}  // namespace

TEST(EspTkTes3, ParsesMetadataAndStopsAtHeaderRecordBoundary)
{
  const std::string author(32, 'A');
  const std::string description(256, 'D');

  Bytes payload;
  appendSubrecord(payload, "UNKN", Bytes{1, 2, 3});
  appendSubrecord(payload, "HEDR", makeHedr(1.3F, 1, author, description, 42));
  Bytes master;
  append(master, "Morrowind.esm");
  master.push_back(0);
  appendSubrecord(payload, "MAST", master);
  appendSubrecord(payload, "DATA", Bytes(8, 0));

  // Bytes after the declared TES3 payload are later top-level records and must not be
  // interpreted as TES3 header subrecords.
  TemporaryPlugin plugin(makePlugin(payload, Bytes{0xff, 0xff, 0xff}));
  ESP::File file(plugin.path().string());

  EXPECT_FLOAT_EQ(file.headerVersion(), 1.3F);
  EXPECT_TRUE(file.isMaster());
  EXPECT_FALSE(file.isDummy());
  EXPECT_EQ(file.author(), author);
  EXPECT_EQ(file.description(), description);
  EXPECT_EQ(file.masters(), std::set<std::string>({"Morrowind.esm"}));
}

TEST(EspTkTes3, ParsesKezymaOpenMWPlayerStubAsDummy)
{
  constexpr std::string_view description =
      "This is an empty esp used by OpenMW Player to represent omwaddon and "
      "omwscripts files in Mod Organizer 2.";

  Bytes payload;
  appendSubrecord(payload, "HEDR", makeHedr(1.0F, 0, "Kezyma", description, 0));
  const Bytes contents = makePlugin(payload);
  ASSERT_EQ(contents.size(), 324);

  TemporaryPlugin plugin(contents, ".omwscripts.esp");
  ESP::File file(plugin.path().string());

  EXPECT_FLOAT_EQ(file.headerVersion(), 1.0F);
  EXPECT_FALSE(file.isMaster());
  EXPECT_TRUE(file.isDummy());
  EXPECT_EQ(file.author(), "Kezyma");
  EXPECT_EQ(file.description(), description);
  EXPECT_TRUE(file.masters().empty());
}

TEST(EspTkTes3, RejectsTruncatedOuterRecord)
{
  Bytes payload;
  appendSubrecord(payload, "HEDR", makeHedr(1.2F, 0, "Author", "Description", 1));
  Bytes contents = makePlugin(payload);
  contents.pop_back();
  TemporaryPlugin plugin(contents);

  EXPECT_THROW(ESP::File file(plugin.path().string()), ESP::InvalidRecordException);
}

TEST(EspTkTes3, RejectsSubrecordOutsideDeclaredBoundary)
{
  Bytes payload;
  append(payload, "HEDR");
  appendLittleEndian32(payload, UINT32_MAX);
  payload.insert(payload.end(), 10, 0);
  TemporaryPlugin plugin(makePlugin(payload));

  EXPECT_THROW(ESP::File file(plugin.path().string()), ESP::InvalidRecordException);
}

TEST(EspTkTes3, RejectsMissingHedr)
{
  Bytes payload;
  appendSubrecord(payload, "UNKN", Bytes{1, 2, 3});
  TemporaryPlugin plugin(makePlugin(payload));

  EXPECT_THROW(ESP::File file(plugin.path().string()), ESP::InvalidRecordException);
}

TEST(EspTkTes3, RejectsInvalidHedrSize)
{
  Bytes payload;
  appendSubrecord(payload, "HEDR", Bytes(299, 0));
  TemporaryPlugin plugin(makePlugin(payload));

  EXPECT_THROW(ESP::File file(plugin.path().string()), ESP::InvalidRecordException);
}
