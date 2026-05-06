/*
Copyright (C) 2026 Florian Roudot, Mohamed Sabt

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

#include "log.h"

#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <ctime>

FILE* LOG_STREAM = NULL;

void init_log() {
  char* LOG_FILE = (char*)malloc(256);

  time_t logtime = time(NULL);
  struct tm* info;
  info = localtime(&logtime);

  char time_str[20];

  strftime(time_str, 20, "%d-%m-%y_%H-%M-%S", info);

  sprintf(LOG_FILE, LOG_FILE_BASE, time_str);

  LOG_STREAM = fopen(LOG_FILE, "ab");

  if (setvbuf(LOG_STREAM, NULL, _IONBF, 0) == -1) {
    perror("");
    exit(-1);
  }

  if (LOG_STREAM == NULL) {
    perror("");
    exit(-1);
  }
  free(LOG_FILE);
}

void log_time(FILE* stream) {
  time_t logtime = time(NULL);
  struct tm* info;
  info = localtime(&logtime);

  char time_str[30];

  strftime(time_str, 30, "[ %x %X ] ", info);

  fputs(time_str, stream);
}

void log(const char* fmt, ...) {
  va_list arg;
  va_start(arg, fmt);

  if (!LOG_STREAM) init_log();

  log_time(LOG_STREAM);
  vfprintf(LOG_STREAM, fmt, arg);
  va_end(arg);
}
