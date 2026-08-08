#include <bsatk/bsaarchive.h>

#include <gtest/gtest.h>

#include <array>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>

namespace fs = std::filesystem;

namespace
{

class TempRoot
{
public:
  TempRoot()
  {
    char path[] = "/tmp/fluorine-bsatk-XXXXXX";
    if (const char* result = mkdtemp(path); result != nullptr) {
      m_path = result;
    }
  }

  ~TempRoot()
  {
    std::error_code error;
    fs::remove_all(m_path, error);
  }

  const fs::path& path() const { return m_path; }

private:
  fs::path m_path;
};

fs::path fixture(const char* name)
{
  return fs::path(FLUORINE_TEST_SOURCE_DIR) / "libs/libbsarch/examples" / name;
}

void expectArchiveExtracts(const char* archiveName)
{
  TempRoot temp;
  ASSERT_FALSE(temp.path().empty());

  BSA::Archive archive;
  ASSERT_EQ(archive.read(fixture(archiveName).string().c_str(), false),
            BSA::ERROR_NONE);

  const fs::path output = temp.path() / "output";
  EXPECT_EQ(archive.extractAll(
                output.string().c_str(), [](int, std::string) { return true; },
                false),
            BSA::ERROR_NONE);

  const fs::path extracted = output / "textures" / "grass" / "test.dds";
  ASSERT_TRUE(fs::is_regular_file(extracted));
  EXPECT_GT(fs::file_size(extracted), 4u);

  std::ifstream stream(extracted, std::ios::binary);
  std::array<char, 4> magic{};
  stream.read(magic.data(), magic.size());
  EXPECT_EQ(std::string(magic.data(), magic.size()), "DDS ");

  for (const auto& entry : fs::recursive_directory_iterator(output)) {
    EXPECT_EQ(entry.path().filename().string().find('\\'), std::string::npos)
        << entry.path();
  }
}

}  // namespace

TEST(BsatkExtraction, ExtractsBsaWithNativeDirectorySeparators)
{
  expectArchiveExtracts("test_read.bsa");
}

TEST(BsatkExtraction, ExtractsBa2WithNativeDirectorySeparators)
{
  expectArchiveExtracts("test_read.ba2");
}

TEST(BsatkExtraction, ReportsOutputDirectoryFailures)
{
  TempRoot temp;
  ASSERT_FALSE(temp.path().empty());

  const fs::path output = temp.path() / "not-a-directory";
  {
    std::ofstream stream(output);
    ASSERT_TRUE(stream.is_open());
  }

  BSA::Archive archive;
  ASSERT_EQ(archive.read(fixture("test_read.bsa").string().c_str(), false),
            BSA::ERROR_NONE);
  EXPECT_EQ(archive.extractAll(
                output.string().c_str(), [](int, std::string) { return true; },
                false),
            BSA::ERROR_ACCESSFAILED);
}
