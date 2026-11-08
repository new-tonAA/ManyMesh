cmake_minimum_required(VERSION 3.19)
project(mmdepth)

set(TARGET mmdepth)

set(SRCS
        src/main.cpp
)

add_executable(${TARGET} ${SRCS})

target_link_libraries(${TARGET} PRIVATE assimp)
set_target_properties(${TARGET} PROPERTIES FOLDER Tools)

if(NOT MSVC)
    target_compile_options(${TARGET} PRIVATE -Wno-deprecated-register)
endif()

install(TARGETS ${TARGET} RUNTIME DESTINATION bin)
