#include "tes3subrecord.h"
#include "espexceptions.h"
#include <array>
#include <cstdint>
#include <string>
#include <unordered_map>

namespace
{

uint32_t decodeLittleEndian32(const unsigned char* bytes)
{
  return static_cast<uint32_t>(bytes[0]) | (static_cast<uint32_t>(bytes[1]) << 8) |
         (static_cast<uint32_t>(bytes[2]) << 16) |
         (static_cast<uint32_t>(bytes[3]) << 24);
}

}  // namespace

ESP::TES3SubRecord::TES3SubRecord() : m_Type(TYPE_UNKNOWN), m_Data() {}

bool ESP::TES3SubRecord::readFrom(std::istream& stream, uint32_t sizeOverride)
{
  static std::unordered_map<std::string, EType> s_TypeMap = {
      {"HEDR", TYPE_HEDR}, {"MAST", TYPE_MAST}, {"DATA", TYPE_DATA}};

  char typeString[5];
  if (!stream.read(typeString, 4)) {
    if (stream.gcount() == 0) {
      return false;
    } else {
      throw ESP::InvalidRecordException("sub-record incomplete (unknown type)");
    }
  }
  if (stream.gcount() != 4) {
    throw ESP::InvalidRecordException(
        std::string("sub-record type incomplete (invalid type ") + typeString + ")");
  }
  typeString[4] = '\0';  // not sure if this is required, shouldn't be
  auto iter     = s_TypeMap.find(std::string(typeString));
  m_Type        = iter != s_TypeMap.end() ? iter->second : TYPE_UNKNOWN;

  std::array<unsigned char, 4> sizeBytes{};
  if (!stream.read(reinterpret_cast<char*>(sizeBytes.data()), sizeBytes.size())) {
    throw ESP::InvalidRecordException("sub-record size incomplete");
  }
  uint32_t dataSize = decodeLittleEndian32(sizeBytes.data());

  if (sizeOverride != 0UL) {
    dataSize = sizeOverride;
  }
  constexpr uint32_t maxSubrecordSize = 64U * 1024U * 1024U;
  if (dataSize > maxSubrecordSize) {
    throw ESP::InvalidRecordException("sub-record is unreasonably large");
  }
  m_Data.resize(dataSize);

  if (dataSize > 0) {
    stream.read(reinterpret_cast<char*>(m_Data.data()), dataSize);
  }
  if (!stream) {
    throw ESP::InvalidRecordException(std::string("sub-record incomplete: ") +
                                      typeString);
  }
  return true;
}
