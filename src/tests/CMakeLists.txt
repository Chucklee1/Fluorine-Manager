cmake_minimum_required(VERSION 3.16)

find_package(Qt6 REQUIRED COMPONENTS Core)
find_package(GTest REQUIRED)
find_package(SQLite3 REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter)

# ---------------------------------------------------------------------------
# OpenMW native config generation tests
# ---------------------------------------------------------------------------
add_test(
    NAME test_openmw_cfg
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/test_openmw_cfg.py
)
add_test(
    NAME test_flatpak_access
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/test_flatpak_access.py
)

# ---------------------------------------------------------------------------
# TES3 metadata and OpenMW Player stub parsing tests
# ---------------------------------------------------------------------------
add_executable(test_esptk_tes3 EXCLUDE_FROM_ALL
    test_esptk_tes3.cpp
)
set_target_properties(test_esptk_tes3 PROPERTIES
    AUTOMOC OFF
    CXX_STANDARD 23
    CXX_STANDARD_REQUIRED ON
)
target_link_libraries(test_esptk_tes3 PRIVATE
    mo2::esptk
    GTest::gtest
    GTest::gtest_main
)
add_test(NAME test_esptk_tes3 COMMAND test_esptk_tes3)

# ---------------------------------------------------------------------------
# Session-only plugin compatibility policy tests
# ---------------------------------------------------------------------------
add_executable(test_plugincompatibility EXCLUDE_FROM_ALL
    test_plugincompatibility.cpp
    ${CMAKE_SOURCE_DIR}/src/src/plugincompatibility.cpp
)
set_target_properties(test_plugincompatibility PROPERTIES
    AUTOMOC OFF
    CXX_STANDARD 23
    CXX_STANDARD_REQUIRED ON
)
target_include_directories(test_plugincompatibility PRIVATE
    ${CMAKE_SOURCE_DIR}/src/src
)
target_link_libraries(test_plugincompatibility PRIVATE
    Qt6::Core
    GTest::gtest
    GTest::gtest_main
)
add_test(NAME test_plugincompatibility COMMAND test_plugincompatibility)

# ---------------------------------------------------------------------------
# meta.ini case-normalization helper tests
# ---------------------------------------------------------------------------
add_executable(test_metainiutils EXCLUDE_FROM_ALL
    test_metainiutils.cpp
    ${CMAKE_SOURCE_DIR}/src/src/metainiutils.cpp
)
set_target_properties(test_metainiutils PROPERTIES
    AUTOMOC OFF
    CXX_STANDARD 23
    CXX_STANDARD_REQUIRED ON
)
target_include_directories(test_metainiutils PRIVATE
    ${CMAKE_SOURCE_DIR}/src/src
)
target_link_libraries(test_metainiutils PRIVATE
    Qt6::Core
    GTest::gtest
    GTest::gtest_main
)
add_test(NAME test_metainiutils COMMAND test_metainiutils)

# ---------------------------------------------------------------------------
# External directory mapping (SKSE Log Redirector style) tests
#
# Exercises the deploy/cleanup logic for `isDirectory && createTarget`
# mappings — directory-symlink path plus the per-file fallback when the
# destination already has real content. The behavior is mirrored from
# FuseConnector::deployExternalMappings so the test can run without
# bringing in libfuse or the rest of the organizer dependency tree.
# ---------------------------------------------------------------------------
add_executable(test_external_dir_mapping EXCLUDE_FROM_ALL
    test_external_dir_mapping.cpp
)
set_target_properties(test_external_dir_mapping PROPERTIES
    AUTOMOC OFF
    CXX_STANDARD 23
    CXX_STANDARD_REQUIRED ON
)
target_link_libraries(test_external_dir_mapping PRIVATE
    GTest::gtest
    GTest::gtest_main
)
add_test(NAME test_external_dir_mapping COMMAND test_external_dir_mapping)

# ---------------------------------------------------------------------------
# Overwrite duplicate scan tests
# ---------------------------------------------------------------------------
add_executable(test_overwrite_duplicates EXCLUDE_FROM_ALL
    test_overwrite_duplicates.cpp
    ${CMAKE_SOURCE_DIR}/src/src/vfs/trackedwrites.cpp
)
set_target_properties(test_overwrite_duplicates PROPERTIES
    AUTOMOC OFF
    CXX_STANDARD 23
    CXX_STANDARD_REQUIRED ON
)
target_include_directories(test_overwrite_duplicates PRIVATE
    ${CMAKE_SOURCE_DIR}/src/src
)
target_link_libraries(test_overwrite_duplicates PRIVATE
    GTest::gtest
    GTest::gtest_main
)
add_test(NAME test_overwrite_duplicates COMMAND test_overwrite_duplicates)

# ---------------------------------------------------------------------------
# VFS file-operation regression tests
# ---------------------------------------------------------------------------
add_executable(test_vfs_file_ops EXCLUDE_FROM_ALL
    test_vfs_file_ops.cpp
    ${CMAKE_SOURCE_DIR}/src/src/vfs/inodetable.cpp
    ${CMAKE_SOURCE_DIR}/src/src/vfs/overwritemanager.cpp
    ${CMAKE_SOURCE_DIR}/src/src/vfs/vfstree.cpp
)
set_target_properties(test_vfs_file_ops PROPERTIES
    AUTOMOC OFF
    CXX_STANDARD 23
    CXX_STANDARD_REQUIRED ON
)
target_include_directories(test_vfs_file_ops PRIVATE
    ${CMAKE_SOURCE_DIR}/src/src
)
target_link_libraries(test_vfs_file_ops PRIVATE
    GTest::gtest
    GTest::gtest_main
)
add_test(NAME test_vfs_file_ops COMMAND test_vfs_file_ops)

# ---------------------------------------------------------------------------
# Persistent VFS catalog / BLAKE3 verification tests
# ---------------------------------------------------------------------------
add_executable(test_vfs_catalog EXCLUDE_FROM_ALL
    test_vfs_catalog.cpp
    ${CMAKE_SOURCE_DIR}/src/src/vfs/vfscatalog.cpp
    ${CMAKE_SOURCE_DIR}/src/src/vfs/vfstree.cpp
    ${CMAKE_SOURCE_DIR}/src/src/fluorinepaths.cpp
    ${CMAKE_SOURCE_DIR}/src/src/fluorineconfig.cpp
)
set_target_properties(test_vfs_catalog PROPERTIES
    AUTOMOC OFF
    CXX_STANDARD 23
    CXX_STANDARD_REQUIRED ON
)
target_include_directories(test_vfs_catalog PRIVATE
    ${CMAKE_SOURCE_DIR}/src/src
    ${CMAKE_SOURCE_DIR}/libs/uibase/include
)
target_link_libraries(test_vfs_catalog PRIVATE
    Qt6::Core
    SQLite::SQLite3
    BLAKE3::blake3
    mo2::uibase
    GTest::gtest
    GTest::gtest_main
)
add_test(NAME test_vfs_catalog COMMAND test_vfs_catalog)

# Register a "fluorine-tests" umbrella target that builds every test exe.
add_custom_target(fluorine-tests
    DEPENDS test_esptk_tes3 test_plugincompatibility test_metainiutils
            test_external_dir_mapping test_overwrite_duplicates test_vfs_file_ops
            test_vfs_catalog)
