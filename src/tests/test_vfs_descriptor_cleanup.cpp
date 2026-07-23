#include "vfs/mo2filesystem.h"

#include <gtest/gtest.h>

#include <cerrno>
#include <fcntl.h>
#include <unistd.h>

namespace
{
int makeUnlinkedTemporaryFile()
{
  char path[] = "/tmp/fluorine-vfs-fd-XXXXXX";
  const int fd = ::mkstemp(path);
  if (fd >= 0) {
    (void)::unlink(path);
  }
  return fd;
}

void expectClosed(int fd)
{
  errno = 0;
  EXPECT_EQ(::fcntl(fd, F_GETFD), -1);
  EXPECT_EQ(errno, EBADF);
}
}

TEST(VfsDescriptorCleanup, ClosesDescriptorsAndForgetsLogicalHandles)
{
  const int readOnlyFd = makeUnlinkedTemporaryFile();
  const int writableFd = makeUnlinkedTemporaryFile();
  ASSERT_GE(readOnlyFd, 0);
  ASSERT_GE(writableFd, 0);

  Mo2FsContext context;
  context.open_files.emplace(
      1, Mo2FsContext::OpenFile{.fd=readOnlyFd, .writable=false});
  context.open_files.emplace(
      2, Mo2FsContext::OpenFile{.fd=writableFd, .writable=true});
  context.open_files.emplace(
      3, Mo2FsContext::OpenFile{.fd=-1, .writable=false});

  const Mo2OpenFileCleanupResult cleanup = mo2CloseOpenFiles(&context);
  EXPECT_EQ(cleanup.logical_handles, 3);
  EXPECT_EQ(cleanup.descriptors_closed, 2);
  EXPECT_EQ(cleanup.writable_descriptors_closed, 1);
  EXPECT_EQ(cleanup.close_errors, 0);
  EXPECT_TRUE(context.open_files.empty());
  expectClosed(readOnlyFd);
  expectClosed(writableFd);

  const Mo2OpenFileCleanupResult repeated = mo2CloseOpenFiles(&context);
  EXPECT_EQ(repeated.logical_handles, 0);
  EXPECT_EQ(repeated.descriptors_closed, 0);
  EXPECT_EQ(repeated.writable_descriptors_closed, 0);
  EXPECT_EQ(repeated.close_errors, 0);
}

TEST(VfsDescriptorCleanup, ContextDestructorIsAFallback)
{
  const int fd = makeUnlinkedTemporaryFile();
  ASSERT_GE(fd, 0);

  {
    Mo2FsContext context;
    context.open_files.emplace(
        1, Mo2FsContext::OpenFile{.fd=fd, .writable=false});
  }

  expectClosed(fd);
}

TEST(VfsDescriptorCleanup, NullContextIsSafe)
{
  const Mo2OpenFileCleanupResult cleanup = mo2CloseOpenFiles(nullptr);
  EXPECT_EQ(cleanup.logical_handles, 0);
  EXPECT_EQ(cleanup.descriptors_closed, 0);
  EXPECT_EQ(cleanup.writable_descriptors_closed, 0);
  EXPECT_EQ(cleanup.close_errors, 0);
}
