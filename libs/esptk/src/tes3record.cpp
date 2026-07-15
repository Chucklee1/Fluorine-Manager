#include "tes3record.h"
#include "espexceptions.h"
#include <array>

namespace
{

uint32_t decodeLittleEndian32(const unsigned char* bytes)
{
  return static_cast<uint32_t>(bytes[0]) | (static_cast<uint32_t>(bytes[1]) << 8) |
         (static_cast<uint32_t>(bytes[2]) << 16) |
         (static_cast<uint32_t>(bytes[3]) << 24);
}

}  // namespace

ESP::TES3Record::TES3Record() : m_DataSize(0), m_Unknown(0), m_Flags(0) {}

bool ESP::TES3Record::readFrom(std::istream& stream)
{
  std::array<unsigned char, 12> header{};
  if (!stream.read(reinterpret_cast<char*>(header.data()), header.size())) {
    if (stream.gcount() == 0) {
      return false;
    } else {
      throw ESP::InvalidRecordException("record incomplete");
    }
  }

  m_DataSize = decodeLittleEndian32(header.data());
  m_Unknown  = decodeLittleEndian32(header.data() + 4);
  m_Flags    = decodeLittleEndian32(header.data() + 8);
  return true;
}
