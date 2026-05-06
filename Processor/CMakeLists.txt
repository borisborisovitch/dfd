cmake_minimum_required(VERSION 3.10)

project(DefectiveByDesign)

option(REENCODE "Enable reencoding" OFF)
if (REENCODE)
  add_definitions(-DREENCODE)
endif()

include_directories(hook/lib/distorm3/include)
include_directories(hook/lib/funchook/include)

include_directories(hook/include)
include_directories(hook/src/include)
include_directories(hook/src/util/include)

set(CMAKE_CXX_FLAGS "-fPIC -g")

set(LIBNAME "hook")

set(FFMPEG_LIBS
    avcodec
    avformat
    avutil
    swscale
)

add_library(${LIBNAME} SHARED 
  hook/src/hook.cpp
  hook/src/encoder.cpp
  hook/src/muxer.cpp
  hook/src/HostWrapper.cpp
  hook/src/processor.cpp
  hook/src/WdvUtils.cpp
  hook/src/util/log.cpp)

target_link_libraries(${LIBNAME} ${CMAKE_SOURCE_DIR}/hook/lib/funchook/lib/libfunchook.a)
target_link_libraries(${LIBNAME} ${CMAKE_SOURCE_DIR}/hook/lib/distorm3/lib/libdistorm3.a)

target_link_libraries(${LIBNAME} ${FFMPEG_LIBS})
