## Fluorine Manager 0.3.3

### Highlights

- Added an optional experimental **USVFS backend** for Wine/Proton launches.
  FUSE remains the default, native Linux launches continue to use FUSE, and
  games such as OpenMW that manage their own VFS are unchanged.
- Reworked OpenMW plugin management around a canonical, transactional selection
  state. Plugin order, enabled state, groundcover, archives, profile switching,
  launch export, and native LOOT sorting now fail safely without silently
  rewriting the user's order.
- Added support for the Palworld client and dedicated server, including their
  configuration and world-save locations.
- Hardened prefix dependency downloads with atomic writes, timeouts, package
  validation, DirectX mirrors, .NET 9 x86/x64 support, and persistent installer
  diagnostics on failure.

### Fixes and improvements

- Fixed FOMOD extraction paths on case-sensitive Linux filesystems.
- Fixed BSA extraction path handling, nested directory creation, unsafe archive
  paths, and extraction error reporting.
- Fixed switching between Python plugins that expose packages with the same
  name across different instances.
- Fixed Kingdom Come: Deliverance II detection on Linux.
- Fixed relative image paths in QSS themes.
- Preserved mod-list column visibility, width, and ordering more reliably.
- Fixed false separator-name collision errors.
- Preserved OpenMW archive selection order and made LOOT sorting non-destructive.
- Improved Root Builder backup performance on copy-on-write filesystems.
- Added extensive OpenMW, USVFS, Palworld, BSA extraction, VFS, and Python
  plugin-switching tests.
- Removed the obsolete rolling `beta` compatibility publisher; rolling builds
  continue through the Nightly channel.
- Added USVFS benchmarking and profiling tools and updated build/CI packaging
  for the bundled Wine-side runtime.

### Notes

- USVFS is experimental and has not yet received broad modlist compatibility
  testing. Users who do not explicitly select it will continue using FUSE.

### Thanks

- [@Chucklee1](https://github.com/Chucklee1) for the Wayland runtime note and
  stylesheet resource-path fix.
- [@PublicVoidUpdate](https://github.com/PublicVoidUpdate) for the DirectX
  dependency-installer investigation.
- [@darkbasic](https://github.com/darkbasic) for the OpenMW plugin-state and
  native LOOT integration work.
