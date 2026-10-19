cmake_minimum_required(VERSION 3.19)
project(mmgpu)

set(TARGET mmgpu)

add_executable(${TARGET}
        src/main.cpp
        src/VulkanApi.cpp
        ${CMAKE_SOURCE_DIR}/third_party/glslang/glslang/ResourceLimits/ResourceLimits.cpp)

target_include_directories(${TARGET} PRIVATE
        src
        ${CMAKE_SOURCE_DIR}/libs/bluevk/include)

target_link_libraries(${TARGET} PRIVATE
        assimp
        glslang
        manymesh
        OSDependent
        SPIRV)

option(MMGPU_RENDERDOC "Enable optional RenderDoc frame capture support" OFF)
if (MMGPU_RENDERDOC)
    find_path(RENDERDOC_INCLUDE_DIR NAMES renderdoc_app.h
            HINTS ENV RENDERDOC_DIR ENV RENDERDOC_HOME
            PATH_SUFFIXES include .)
    if (NOT RENDERDOC_INCLUDE_DIR)
        message(FATAL_ERROR "MMGPU_RENDERDOC requires renderdoc_app.h; set RENDERDOC_DIR")
    endif()
    target_include_directories(${TARGET} PRIVATE ${RENDERDOC_INCLUDE_DIR})
    target_compile_definitions(${TARGET} PRIVATE MMGPU_HAS_RENDERDOC=1)
    message(STATUS "mmgpu: RenderDoc capture enabled (${RENDERDOC_INCLUDE_DIR})")
endif()

set_target_properties(${TARGET} PROPERTIES FOLDER Tools)

if(NOT MSVC)
    target_compile_options(${TARGET} PRIVATE -Wno-deprecated-register)
endif()

install(TARGETS ${TARGET} RUNTIME DESTINATION bin)
install(FILES README.md DESTINATION docs/ RENAME "${TARGET}.md")
