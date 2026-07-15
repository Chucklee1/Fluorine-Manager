#include "espfile.h"
#include "espexceptions.h"
#include "subrecord.h"
#include <algorithm>
#include <array>
#include <cstring>
#include <sstream>
#include <vector>

namespace
{

uint32_t decodeLittleEndian32(const unsigned char* bytes)
{
  return static_cast<uint32_t>(bytes[0]) | (static_cast<uint32_t>(bytes[1]) << 8) |
         (static_cast<uint32_t>(bytes[2]) << 16) |
         (static_cast<uint32_t>(bytes[3]) << 24);
}

void readExact(std::istream& stream, void* destination, std::streamsize size,
               const char* message)
{
  if (!stream.read(static_cast<char*>(destination), size)) {
    throw ESP::InvalidRecordException(message);
  }
}

std::string boundedString(const unsigned char* bytes, size_t size)
{
  const auto* end = std::find(bytes, bytes + size, 0);
  return std::string(reinterpret_cast<const char*>(bytes),
                     static_cast<size_t>(end - bytes));
}

}  // namespace

ESP::File::File(const std::string& fileName)
{
  m_File.open(fileName, std::fstream::in | std::fstream::binary);
  init();
}

ESP::File::File(const std::wstring& fileName)
{
#ifdef _WIN32
  m_File.open(fileName, std::fstream::in | std::fstream::binary);
#else
  // Linux: properly encode wstring → UTF-8. The old naive
  // `string(w.begin(), w.end())` copy truncated any codepoint > 0x7F
  // (e.g. ö U+00F6, – U+2013) which broke paths like "Mörskom Estate" or
  // "Official Master Files – Cleaned".
  std::string narrowName;
  narrowName.reserve(fileName.size());
  for (wchar_t wc : fileName) {
    const auto cp = static_cast<uint32_t>(wc);
    if (cp < 0x80) {
      narrowName.push_back(static_cast<char>(cp));
    } else if (cp < 0x800) {
      narrowName.push_back(static_cast<char>(0xC0 | (cp >> 6)));
      narrowName.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    } else if (cp < 0x10000) {
      narrowName.push_back(static_cast<char>(0xE0 | (cp >> 12)));
      narrowName.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
      narrowName.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    } else {
      narrowName.push_back(static_cast<char>(0xF0 | (cp >> 18)));
      narrowName.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
      narrowName.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
      narrowName.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    }
  }
  m_File.open(narrowName, std::fstream::in | std::fstream::binary);
#endif
  init();
}

class membuf : public std::basic_streambuf<char>
{
public:
  membuf(const char* start, size_t size)
  {
    // baad me! this is intended for an istream only so we're not modifying
    char* startMod = const_cast<char*>(start);
    setg(startMod, startMod, startMod + size);
  }
};

void ESP::File::init()
{
  if (!m_File.is_open()) {
    throw ESP::InvalidFileException("file not found");
  }
  m_File.exceptions(std::ios_base::badbit);

  uint8_t type[4];
  if (!m_File.read(reinterpret_cast<char*>(type), 4)) {
    throw ESP::InvalidFileException("file incomplete");
  }
  if (memcmp(type, "TES3", 4) == 0) {
    m_IsTES3 = true;

    ESP::TES3Record rec;
    if (!rec.readFrom(m_File)) {
      throw ESP::InvalidRecordException("TES3 record header incomplete");
    }

    const auto payloadStart = m_File.tellg();
    m_File.seekg(0, std::ios::end);
    const auto fileEnd = m_File.tellg();
    if (payloadStart < 0 || fileEnd < payloadStart ||
        static_cast<uint64_t>(fileEnd - payloadStart) < rec.dataSize()) {
      throw ESP::InvalidRecordException("TES3 record data incomplete");
    }
    m_File.seekg(payloadStart);

    uint32_t remaining = rec.dataSize();
    bool hasHeader     = false;
    while (remaining > 0) {
      if (remaining < 8) {
        throw ESP::InvalidRecordException("TES3 sub-record header incomplete");
      }

      std::array<char, 4> subrecordType{};
      std::array<unsigned char, 4> sizeBytes{};
      readExact(m_File, subrecordType.data(), subrecordType.size(),
                "TES3 sub-record type incomplete");
      readExact(m_File, sizeBytes.data(), sizeBytes.size(),
                "TES3 sub-record size incomplete");
      remaining -= 8;

      const uint32_t dataSize = decodeLittleEndian32(sizeBytes.data());
      if (dataSize > remaining) {
        throw ESP::InvalidRecordException("TES3 sub-record data exceeds record size");
      }

      if (memcmp(subrecordType.data(), "HEDR", 4) == 0) {
        constexpr size_t headerSize = 300;
        if (dataSize != headerSize) {
          throw ESP::InvalidRecordException("invalid TES3 HEDR size");
        }

        std::array<unsigned char, headerSize> header{};
        readExact(m_File, header.data(), header.size(), "TES3 HEDR incomplete");

        const uint32_t versionBits = decodeLittleEndian32(header.data());
        static_assert(sizeof(m_Header.version) == sizeof(versionBits));
        memcpy(&m_Header.version, &versionBits, sizeof(versionBits));
        m_TES3Master  = (decodeLittleEndian32(header.data() + 4) & 1U) != 0;
        m_Author      = boundedString(header.data() + 8, 32);
        m_Description = boundedString(header.data() + 40, 256);
        m_Header.numRecords =
            static_cast<int32_t>(decodeLittleEndian32(header.data() + 296));
        hasHeader = true;
      } else if (memcmp(subrecordType.data(), "MAST", 4) == 0) {
        constexpr uint32_t maxMasterNameSize = 4096;
        if (dataSize > maxMasterNameSize) {
          throw ESP::InvalidRecordException("TES3 MAST is unreasonably large");
        }
        std::vector<unsigned char> master(dataSize);
        if (dataSize > 0) {
          readExact(m_File, master.data(), master.size(), "TES3 MAST incomplete");
          m_Masters.insert(boundedString(master.data(), master.size()));
        }
      } else {
        m_File.seekg(static_cast<std::streamoff>(dataSize), std::ios::cur);
        if (!m_File) {
          throw ESP::InvalidRecordException("TES3 sub-record data incomplete");
        }
      }

      remaining -= dataSize;
    }

    if (!hasHeader) {
      throw ESP::InvalidRecordException("TES3 record has no HEDR sub-record");
    }
  } else if (memcmp(type, "TES4", 4) == 0) {
    m_File.seekg(0);

    m_MainRecord = readRecord();

    const std::vector<uint8_t>& data = m_MainRecord.data();
    if (data.empty()) {
      throw ESP::InvalidRecordException("record has no data");
    }
    membuf buf(reinterpret_cast<const char*>(data.data()), data.size());

    std::istream stream(&buf);
    while (!stream.eof() && !stream.fail()) {
      SubRecord rec;
      bool success = rec.readFrom(stream);
      if (success) {
        if (rec.type() != SubRecord::TYPE_UNKNOWN) {
          switch (rec.type()) {
          case SubRecord::TYPE_HEDR:
            onHEDR(rec);
            break;
          case SubRecord::TYPE_MAST:
            onMAST(rec);
            break;
          case SubRecord::TYPE_CNAM:
            onCNAM(rec);
            break;
          case SubRecord::TYPE_SNAM:
            onSNAM(rec);
            break;
          case SubRecord::TYPE_UNKNOWN:
          case SubRecord::TYPE_ONAM:
            break;
          }
        }
      }
    }
  } else {
    throw ESP::InvalidFileException("invalid file type");
  }
}

void ESP::File::onHEDR(const SubRecord& rec)
{
  if (rec.data().size() != sizeof(m_Header)) {
    printf("invalid header size\n");
    m_Header.version    = 0.0f;
    m_Header.numRecords = 1;  // prevent this esp appear like a dummy
  } else {
    memcpy(&m_Header, &rec.data()[0], sizeof(m_Header));
  }
}

void ESP::File::onMAST(const SubRecord& rec)
{
  if (rec.data().size() > 0)
    m_Masters.insert(reinterpret_cast<const char*>(&rec.data()[0]));
}

void ESP::File::onCNAM(const SubRecord& rec)
{
  if (rec.data().size() > 0)
    m_Author = reinterpret_cast<const char*>(&rec.data()[0]);
}

void ESP::File::onSNAM(const SubRecord& rec)
{
  if (rec.data().size() > 0)
    m_Description = reinterpret_cast<const char*>(&rec.data()[0]);
}

ESP::Record ESP::File::readRecord()
{
  ESP::Record rec;
  rec.readFrom(m_File);
  return rec;
}

bool ESP::File::isMaster() const
{
  if (m_IsTES3) {
    return m_TES3Master;
  }
  return m_MainRecord.flagSet(Record::FLAG_MASTER);
}

bool ESP::File::isLight(bool overlaySupport) const
{
  if (overlaySupport) {
    return m_MainRecord.flagSet(Record::FLAG_LIGHT_ALTERNATE);
  } else {
    return m_MainRecord.flagSet(Record::FLAG_LIGHT);
  }
}

bool ESP::File::isMedium() const
{
  return m_MainRecord.flagSet(Record::FLAG_MEDIUM);
}

bool ESP::File::isOverlay() const
{
  return m_MainRecord.flagSet(Record::FLAG_OVERLAY);
}

bool ESP::File::isBlueprint() const
{
  return m_MainRecord.flagSet(Record::FLAG_BLUEPRINT);
}

bool ESP::File::isDummy() const
{
  return m_Header.numRecords == 0;
}
