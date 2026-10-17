cmake_minimum_required(VERSION 3.19)
project(manymesh)

set(TARGET manymesh)
set(PUBLIC_HDR_DIR include)

# ==================================================================================================
# Sources and headers
# ==================================================================================================
set(PUBLIC_HDRS
        include/manymesh/Cluster.h
        include/manymesh/Clusterizer.h
        include/manymesh/AttributeSimplifier.h
        include/manymesh/GeometryError.h
        include/manymesh/GpuLod.h
        include/manymesh/Grouper.h
        include/manymesh/LodGraph.h
        include/manymesh/Mesh.h
        include/manymesh/Quality.h
        include/manymesh/Simplifier.h
        include/manymesh/Streaming.h
        include/manymesh/VisibilityBuffer.h
)

set(SRCS
        src/Clusterizer.cpp
        src/AttributeSimplifier.cpp
        src/GeometryError.cpp
        src/GpuLod.cpp
        src/Grouper.cpp
        src/LodGraph.cpp
        src/Mesh.cpp
        src/Quality.cpp
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
    set_target_properties(${TARGET} PROPERTIES FOLDER Tests)
endif()
