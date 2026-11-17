cmake_minimum_required(VERSION 3.19)
project(mmgeo)

set(TARGET mmgeo)

# ==================================================================================================
# Sources
# ==================================================================================================
set(SRCS
        src/main.cpp
)

# ==================================================================================================
# Target definitions
# ==================================================================================================
add_executable(${TARGET} ${SRCS})

target_link_libraries(${TARGET} PRIVATE assimp image imageio manymesh utils meshoptimizer)
set_target_properties(${TARGET} PROPERTIES FOLDER Tools)

# Explicit research target: never changes mmgeo or the default simplification path.
add_executable(mm_boundary_bench EXCLUDE_FROM_ALL src/boundary_bench.cpp)
target_link_libraries(mm_boundary_bench PRIVATE manymesh)
set_target_properties(mm_boundary_bench PROPERTIES FOLDER Tools)

add_executable(mm_capture_candidates EXCLUDE_FROM_ALL src/capture_candidates.cpp)
target_link_libraries(mm_capture_candidates PRIVATE manymesh assimp)
set_target_properties(mm_capture_candidates PROPERTIES FOLDER Tools)

add_executable(mm_filter_energy_bench EXCLUDE_FROM_ALL src/filter_energy_bench.cpp)
target_link_libraries(mm_filter_energy_bench PRIVATE manymesh)
set_target_properties(mm_filter_energy_bench PROPERTIES FOLDER Tools)

if(NOT MSVC)
    target_compile_options(${TARGET} PRIVATE -Wno-deprecated-register)
endif()

# =================================================================================================
# Licenses
# ==================================================================================================
set(MODULE_LICENSES libassimp meshoptimizer)
set(GENERATION_ROOT ${CMAKE_CURRENT_BINARY_DIR}/generated)
list_licenses(${GENERATION_ROOT}/licenses/licenses.inc "${MODULE_LICENSES}")
target_include_directories(${TARGET} PRIVATE ${GENERATION_ROOT})

# ==================================================================================================
# Installation
# ==================================================================================================
install(TARGETS ${TARGET} RUNTIME DESTINATION bin)
install(FILES "README.md" DESTINATION docs/ RENAME "${TARGET}.md")
