cmake_minimum_required(VERSION 3.19)
project(manymesh)

find_package(Threads REQUIRED)

set(TARGET manymesh)
set(PUBLIC_HDR_DIR include)

# ==================================================================================================
# Sources and headers
# ==================================================================================================
set(PUBLIC_HDRS
        include/manymesh/AmbientOcclusion.h
        include/manymesh/AttributeSimplifier.h
        include/manymesh/Cluster.h
        include/manymesh/Clusterizer.h
        include/manymesh/CornerSimplifier.h
        include/manymesh/DetailBake.h
        include/manymesh/GeometryError.h
        include/manymesh/GpuLod.h
        include/manymesh/Grouper.h
        include/manymesh/LodGraph.h
        include/manymesh/Mesh.h
        include/manymesh/Quality.h
        include/manymesh/ShadingNormals.h
        include/manymesh/Simplifier.h
        include/manymesh/Streaming.h
        include/manymesh/VisibilityBuffer.h
)

set(SRCS
        src/AmbientOcclusion.cpp
        src/AttributeSimplifier.cpp
        src/Clusterizer.cpp
        src/CornerSimplifier.cpp
        src/DetailBake.cpp
        src/GeometryError.cpp
        src/GpuLod.cpp
        src/GpuLodCutShaders.h
        src/Grouper.cpp
        src/LodGraph.cpp
        src/Mesh.cpp
        src/Quality.cpp
        src/ShadingNormals.cpp
        src/Simplifier.cpp
        src/Streaming.cpp
        src/VisibilityBuffer.cpp
)

# ==================================================================================================
# Include and target definitions
# ==================================================================================================
include_directories(${PUBLIC_HDR_DIR})

add_library(${TARGET} STATIC ${PUBLIC_HDRS} ${SRCS})

target_link_libraries(${TARGET} PUBLIC math)
target_link_libraries(${TARGET} PRIVATE meshoptimizer)
target_link_libraries(${TARGET} PRIVATE Threads::Threads)
if (WIN32)
    target_link_libraries(${TARGET} PUBLIC winhttp)
    set(MANYMESH_HTTP_CIVETWEB_DEFAULT OFF)
else()
    set(MANYMESH_HTTP_CIVETWEB_DEFAULT ON)
endif()
option(MANYMESH_HTTP_CIVETWEB
        "Use the vendored CivetWeb client for HTTP Range requests" ${MANYMESH_HTTP_CIVETWEB_DEFAULT})
if (MANYMESH_HTTP_CIVETWEB)
    if (NOT TARGET civetweb)
        message(FATAL_ERROR "MANYMESH_HTTP_CIVETWEB requires the civetweb target")
    endif()
    target_compile_definitions(${TARGET} PRIVATE MANYMESH_HTTP_CIVETWEB=1)
    target_link_libraries(${TARGET} PRIVATE civetweb)
endif()

target_include_directories(${TARGET} PUBLIC ${PUBLIC_HDR_DIR})
set_target_properties(${TARGET} PROPERTIES FOLDER Libs)

# ==================================================================================================
# Installation
# ==================================================================================================
install(TARGETS ${TARGET} ARCHIVE DESTINATION lib/${DIST_DIR})
install(DIRECTORY ${PUBLIC_HDR_DIR}/manymesh DESTINATION include)

# ==================================================================================================
# Tests
# ==================================================================================================
if (FILAMENT_BUILD_TESTING AND NOT ANDROID AND NOT WASM AND NOT IOS)
    set(TARGET test_manymesh)
    add_executable(${TARGET} tests/test_manymesh.cpp)
    target_link_libraries(${TARGET} PRIVATE manymesh gtest)
    if (MANYMESH_HTTP_CIVETWEB)
        target_compile_definitions(${TARGET} PRIVATE MANYMESH_HTTP_CIVETWEB=1)
    endif()
    set_target_properties(${TARGET} PROPERTIES FOLDER Tests)
endif()
