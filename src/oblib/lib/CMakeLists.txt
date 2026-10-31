add_subdirectory(compress)
add_subdirectory(restore)

seekdb_apply_unity_inventory(oblib_lib SEEKDB_OBLIB_LIB_UNITY)
# Bazel deliberately compiles the compression implementation outside its
# historical OBLib Unity group; preserve that action boundary here.
set_source_files_properties(
  ${CMAKE_SOURCE_DIR}/src/oblib/lib/oblog/ob_log_compressor.cpp
  PROPERTIES SKIP_UNITY_BUILD_INCLUSION ON)
ob_lib_add_target(oblib_lib)

seekdb_apply_unity_inventory(oblib_lib_simd SEEKDB_OBLIB_SIMD_UNITY)
ob_lib_add_target(oblib_lib_simd)
if(ARCHITECTURE STREQUAL "x86_64")
  target_compile_options(oblib_lib_simd PRIVATE -mavx2 -mssse3)
elseif(ARCHITECTURE STREQUAL "amd64")
  target_compile_options(oblib_lib_simd PRIVATE
    -mavx2 -mssse3 -msse3 -msse4.1)
endif()

seekdb_apply_unity_inventory(oblib_lib_bitmap SEEKDB_OBLIB_BITMAP_UNITY)
ob_lib_add_target(oblib_lib_bitmap)

seekdb_apply_unity_inventory(ob_malloc_object SEEKDB_OBLIB_MALLOC_UNITY)
ob_add_new_object_target(ob_malloc_object ob_malloc_object)
target_link_libraries(ob_malloc_object oblib_base_without_pass)
add_library(ob_malloc STATIC)
target_link_libraries(ob_malloc ob_malloc_object)
if(OB_HAVE_BUNDLED_JEMALLOC)
  target_link_libraries(ob_malloc_object seekdb_jemalloc)
  target_link_libraries(ob_malloc seekdb_jemalloc)
endif()

# malloc_hook is only part of the Linux production runtime.
if(NOT APPLE AND NOT WIN32 AND NOT ANDROID)
  add_library(malloc_hook STATIC ${SEEKDB_OBLIB_MALLOC_HOOK_STANDALONE})
  target_link_libraries(malloc_hook oblib_base)
  if(OB_HAVE_BUNDLED_JEMALLOC)
    target_link_libraries(malloc_hook seekdb_jemalloc)
  endif()
endif()

if(WIN32)
  set(VCPKG_LIB_DIR "${OB_VCPKG_DIR}/lib")
  target_link_libraries(oblib_lib
    PUBLIC ob_malloc compress restore
    ${VCPKG_LIB_DIR}/libxml2.lib)
else()
  target_link_libraries(oblib_lib
    PUBLIC ob_malloc compress restore
    ${DEP_DIR}/lib/libxml2.a
    ${DEP_DIR}/lib/liblzma.a)
endif()

if(ANDROID)
  # Android dependencies are installed directly under DEP_DIR/lib.
  target_link_directories(oblib_lib PUBLIC ${DEP_DIR}/lib)
  target_compile_options(oblib_lib PUBLIC -fopenmp)
  target_link_libraries(oblib_lib PUBLIC
    libvsag_static.a
    libantlr4-autogen.a
    libantlr4-runtime.a
    libdiskann.a
    libsimd.a
    libcpuinfo.a
    libfmt.a
    libopenblas.a
    libspdlog.a
    libroaring.a
    -fopenmp -static-openmp)
else()
  target_link_directories(oblib_lib PUBLIC
    ${DEP_DIR}/lib ${DEP_DIR}/lib/vsag_lib)
  if(CMAKE_SYSTEM_NAME STREQUAL "iOS")
    # Apple Clang accepts OpenMP in its frontend; the iOS runtime is linked separately.
    target_compile_options(oblib_lib PUBLIC "SHELL:-Xpreprocessor -fopenmp")
  elseif(UNIX AND CMAKE_CXX_COMPILER_ID STREQUAL "AppleClang")
    # AppleClang's driver does not expose -fopenmp, but its frontend does.
    # Keep using the libomp runtime packaged with the arm64 VSAG libraries.
    target_compile_options(oblib_lib PUBLIC "SHELL:-Xclang -fopenmp")
  elseif(UNIX)
    target_compile_options(oblib_lib PUBLIC -fopenmp)
  endif()

  if(CMAKE_SYSTEM_PROCESSOR STREQUAL "x86_64")
    target_link_libraries(oblib_lib PUBLIC
      libcpuinfo.a
      libsimd.a
      libvsag_static.a
      libdiskann.a
      libopenblas.a
      libgfortran_static.a
      libquadmath_static.a
      libgomp_static.a
      libroaring.a
      libantlr4-runtime.a
      libantlr4-autogen.a
      libfmt.a)
    # Optional hipVS bridge is linked below, after architecture selection.
    # GPU support must also define OB_BUILD_CUVS for the C++ adaptor.
  elseif(CMAKE_SYSTEM_PROCESSOR STREQUAL "aarch64")
    target_link_libraries(oblib_lib PUBLIC
      libcpuinfo.a
      libsimd.a
      libvsag_static.a
      libdiskann.a
      libopenblas.a
      libgfortran_static.a
      libgomp_static.a
      libroaring.a
      libantlr4-runtime.a
      libantlr4-autogen.a
      libfmt.a)
  elseif(CMAKE_SYSTEM_PROCESSOR STREQUAL "arm64")
    target_link_libraries(oblib_lib PUBLIC
      libcpuinfo.a
      libsimd.a
      libvsag_static.a
      libdiskann.a
      libio.a
      libroaring.a
      libantlr4-runtime.a
      libantlr4-autogen.a
      libfmt.a)
    if(CMAKE_SYSTEM_NAME STREQUAL "iOS")
      target_link_libraries(oblib_lib PUBLIC
        libomp.a liblapacke.a "-framework Accelerate")
    else()
      target_link_libraries(oblib_lib PUBLIC
        libgfortran_static.a libquadmath_static.a libgcc.a
        libomp_static.a libopenblas.a)
    endif()
  elseif(CMAKE_SYSTEM_PROCESSOR STREQUAL "AMD64")
    target_link_directories(oblib_lib PUBLIC ${OB_VSAG_DIR}/lib)
    target_include_directories(oblib_lib PUBLIC ${OB_VSAG_DIR}/include)
    target_link_libraries(oblib_lib PUBLIC
      cpuinfo.lib
      simd.lib
      vsag_static.lib
      diskann.lib
      openblas.lib
      libomp.lib
      roaring.lib
      antlr4-runtime-static.lib
      antlr4-autogen.lib
      fmt.lib)
  else()
    message(FATAL_ERROR "Unsupported architecture: ${CMAKE_SYSTEM_PROCESSOR}")
  endif()
endif()


# [hipVS/cuVS] Building with -DOB_BUILD_CUVS=ON MUST compile the
# matching C++ implementation. Previously only the bridge was linked, so the
# preprocessor used the inert #else stubs and GPU acceleration never ran.
if(OB_BUILD_CUVS)
  if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR
     NOT CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|amd64)$")
    message(FATAL_ERROR "hipVS/cuVS GPU backend currently requires Linux x86_64")
  endif()
  if(NOT CUVS_BRIDGE_LIB OR NOT EXISTS "${CUVS_BRIDGE_LIB}")
    message(FATAL_ERROR
      "OB_BUILD_CUVS=ON requires -DCUVS_BRIDGE_LIB=/absolute/path/to/libseekdb_cuvs_bridge.so; build it with tools/hipvs_bridge/build.sh")
  endif()
  get_filename_component(SEEKDB_CUVS_BRIDGE_ABS "${CUVS_BRIDGE_LIB}" ABSOLUTE)
  target_compile_definitions(oblib_lib PRIVATE OB_BUILD_CUVS=1)
  target_link_libraries(oblib_lib PUBLIC "${SEEKDB_CUVS_BRIDGE_ABS}")
  message(STATUS "AMD hipVS/cuVS enabled: ${SEEKDB_CUVS_BRIDGE_ABS}")
endif()

# Developer instrumentation is independently opt-in and must be propagated
# to the compiled vector adaptor (not merely defined as a CMake variable).
if(OB_BUILD_CUVS_TRACE)
  target_compile_definitions(oblib_lib PRIVATE OB_BUILD_CUVS_TRACE=1)
endif()
