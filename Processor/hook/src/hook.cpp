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

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

#include "HostWrapper.h"
#include "content_decryption_module.h"
#include "funchook.h"
#include "log.h"

typedef void* (*CreateCdmInstance_t)(int, const char*, uint32_t, GetCdmHostFunc,
                                     void*);
typedef void* (*dlsym_t)(void*, const char*);

static CreateCdmInstance_t create = NULL;
static dlsym_t dlsym_fp = NULL;

cdm::ContentDecryptionModule_10* gWidevine;

void* my_create(int cdm_interface_version, const char* key_system,
                uint32_t key_system_size, GetCdmHostFunc get_cdm_host_func,
                void* user_data) {
  LOG("CreateCdmInstance()\n");
  if (cdm_interface_version != 10) {
    return nullptr;
  }

  cdm::HostWrapper* host_wrapper =
      new cdm::HostWrapper((cdm::Host_10*)user_data);

  auto* cdm = (cdm::ContentDecryptionModule_10*)create(
      cdm_interface_version, key_system, key_system_size, get_cdm_host_func,
      host_wrapper);

  gWidevine = cdm;

  return gWidevine;
}

static void* my_dlsym(void* handle, const char* symbol) {
  void* ret = dlsym_fp(handle, symbol);

  if (strcmp(symbol, "CreateCdmInstance") == 0) {
    LOG("dlsym(\"CreateCdmInstance\")\n");
    create = (CreateCdmInstance_t)ret;
    ret = (void*)my_create;
  }

  return ret;
}

__attribute__((constructor)) static void install_hooks(void) {
  funchook_t* fh = funchook_create();

  dlsym_fp = (dlsym_t)dlsym(RTLD_NEXT, "dlsym");

  funchook_prepare(fh, (void**)&dlsym_fp, (void*)my_dlsym);
  funchook_install(fh, 0);
}