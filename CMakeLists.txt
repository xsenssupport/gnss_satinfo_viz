cmake_minimum_required(VERSION 3.8)
project(gnss_satinfo_viz)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# ── Dependencies ────────────────────────────────────────────────────────────
find_package(ament_cmake REQUIRED)
find_package(rclpy REQUIRED)
find_package(std_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

# ── Custom messages ──────────────────────────────────────────────────────────
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/GnssSatInfo.msg"
  DEPENDENCIES std_msgs
)

# ── Install Python node directly (avoids ament_cmake_python target clash) ───
install(PROGRAMS
  scripts/gnss_satinfo_viz_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME gnss_satinfo_viz_node
)

# ── Launch files ─────────────────────────────────────────────────────────────
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME}
  OPTIONAL
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
