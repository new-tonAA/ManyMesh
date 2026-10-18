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

set_target_properties(${TARGET} PROPERTIES FOLDER Tools)

if(NOT MSVC)
    target_compile_options(${TARGET} PRIVATE -Wno-deprecated-register)
endif()

install(TARGETS ${TARGET} RUNTIME DESTINATION bin)
install(FILES README.md DESTINATION docs/ RENAME "${TARGET}.md")
