cmake_minimum_required(VERSION 3.22.1)
project(allocator)
add_library(allocator SHARED allocator.cpp)
target_link_libraries(allocator log)