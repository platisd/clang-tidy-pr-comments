project(clang_tidy_pr_comments_test LANGUAGES CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_executable(clang_tidy_pr_comments_test
  main.cpp
  )

# run clang-tidy on this file
add_custom_command(TARGET clang-tidy
  COMMAND clang-tidy -p ${CMAKE_BINARY_DIR} ${CMAKE_CURRENT_SOURCE_DIR}/main.cpp --export-fixes=${CMAKE_BINARY_DIR}/fixes.yaml
  )
