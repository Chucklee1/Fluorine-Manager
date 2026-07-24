#ifndef VFS_ARCHIVEINDEX_H
#define VFS_ARCHIVEINDEX_H

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string_view>
#include <vector>

// Compact, immutable-after-build membership index for paths stored inside the
// visible BSA/BA2 containers. A match never turns an archive member into a
// loose FUSE file or changes Bethesda resource priority. A complete index may
// also be serialized as a conservative absence proof for consumers.
//
// Twelve bits and seven probes per member give a false-positive rate below 1%
// at the intended load factor while avoiding another multi-million-string map.
class VfsArchiveMemberIndex
{
public:
  explicit VfsArchiveMemberIndex(std::size_t expected_members = 0,
                                 std::size_t archive_count = 0,
                                 bool complete = true)
      : m_bit_count(std::max<std::size_t>(64, expected_members * 12)),
        m_bits((m_bit_count + 63) / 64),
        m_archive_count(archive_count),
        m_member_count(expected_members),
        m_complete(complete)
  {}

  void add(std::string_view normalized_path)
  {
    if (normalized_path.empty()) return;
    const auto [first, step] = hashes(normalized_path);
    for (uint64_t probe = 0; probe < kProbeCount; ++probe) {
      const std::size_t bit = static_cast<std::size_t>(
          (first + probe * step) % static_cast<uint64_t>(m_bit_count));
      m_bits[bit / 64] |= uint64_t{1} << (bit % 64);
    }
  }

  bool mightContain(std::string_view normalized_path) const
  {
    if (normalized_path.empty() || m_member_count == 0) return false;
    const auto [first, step] = hashes(normalized_path);
    for (uint64_t probe = 0; probe < kProbeCount; ++probe) {
      const std::size_t bit = static_cast<std::size_t>(
          (first + probe * step) % static_cast<uint64_t>(m_bit_count));
      if ((m_bits[bit / 64] & (uint64_t{1} << (bit % 64))) == 0) return false;
    }
    return true;
  }

  std::size_t archiveCount() const { return m_archive_count; }
  std::size_t memberCount() const { return m_member_count; }
  std::size_t bitCount() const { return m_bit_count; }
  std::size_t memoryBytes() const { return m_bits.size() * sizeof(uint64_t); }
  bool complete() const { return m_complete; }
  static constexpr uint64_t probeCount() { return kProbeCount; }

  // Wire representation is a sequence of little-endian uint64 words. The
  // explicit encoding keeps the producer's immutable publication independent
  // of host endianness.
  std::vector<unsigned char> serializedBits() const
  {
    std::vector<unsigned char> bytes(m_bits.size() * sizeof(uint64_t));
    for (std::size_t word = 0; word < m_bits.size(); ++word) {
      uint64_t value = m_bits[word];
      for (std::size_t byte = 0; byte < sizeof(uint64_t); ++byte) {
        bytes[word * sizeof(uint64_t) + byte] =
            static_cast<unsigned char>(value & 0xff);
        value >>= 8;
      }
    }
    return bytes;
  }

  static std::shared_ptr<const VfsArchiveMemberIndex> fromSerialized(
      std::size_t bit_count, std::size_t archive_count,
      std::size_t member_count, const std::vector<unsigned char>& bytes)
  {
    if (bit_count < 64 ||
        bytes.size() != ((bit_count + 63) / 64) * sizeof(uint64_t)) {
      return {};
    }
    auto index = std::make_shared<VfsArchiveMemberIndex>();
    index->m_bit_count = bit_count;
    index->m_archive_count = archive_count;
    index->m_member_count = member_count;
    index->m_complete = true;
    index->m_bits.assign(bytes.size() / sizeof(uint64_t), 0);
    for (std::size_t word = 0; word < index->m_bits.size(); ++word) {
      uint64_t value = 0;
      for (std::size_t byte = 0; byte < sizeof(uint64_t); ++byte) {
        value |= static_cast<uint64_t>(
                     bytes[word * sizeof(uint64_t) + byte])
                 << (byte * 8);
      }
      index->m_bits[word] = value;
    }
    const std::size_t used = bit_count % 64;
    if (used != 0 &&
        (index->m_bits.back() & (~uint64_t{0} << used)) != 0) {
      return {};
    }
    return index;
  }

private:
  static constexpr uint64_t kProbeCount = 7;

  static uint64_t mix(uint64_t value)
  {
    value ^= value >> 30;
    value *= 0xbf58476d1ce4e5b9ULL;
    value ^= value >> 27;
    value *= 0x94d049bb133111ebULL;
    value ^= value >> 31;
    return value;
  }

  static std::pair<uint64_t, uint64_t> hashes(std::string_view value)
  {
    uint64_t first = 1469598103934665603ULL;
    for (const unsigned char byte : value) {
      first ^= byte;
      first *= 1099511628211ULL;
    }
    // Double hashing supplies independent-looking Bloom probes without
    // hashing every long asset path seven times. Keep the step odd/non-zero.
    const uint64_t step = mix(first ^ 0x9e3779b97f4a7c15ULL) | 1ULL;
    return {mix(first), step};
  }

  std::size_t m_bit_count = 64;
  std::vector<uint64_t> m_bits;
  std::size_t m_archive_count = 0;
  std::size_t m_member_count = 0;
  bool m_complete = true;
};

#endif
