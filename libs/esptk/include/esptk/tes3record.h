#ifndef TES3_RECORD_H
#define TES3_RECORD_H

#include <cstdint>
#include <istream>
#include <vector>

namespace ESP
{

/**
 * @brief record storage class without record-specific information
 */
class TES3Record
{
public:
  TES3Record();

  bool readFrom(std::istream& stream);

  uint32_t dataSize() const { return m_DataSize; }
  uint32_t flags() const { return m_Flags; }

private:
  uint32_t m_DataSize;
  uint32_t m_Unknown;
  uint32_t m_Flags;
};

}  // namespace ESP

#endif  // TES3_RECORD_H
