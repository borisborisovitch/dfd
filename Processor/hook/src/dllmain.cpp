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

#include <windows.h>

#include <atomic>
#include <fstream>
#include <thread>

#include "MinHook.h"
#include "content_decryption_module.h"
#include "log.h"
#include "processor.h"

#define DLL_PATH L"./x64/Release/hook.dll"

typedef FARPROC(WINAPI* GetProcAddress_t)(HMODULE, LPCSTR);
typedef BOOL(WINAPI* CreateProcessW_t)(LPCWSTR, LPWSTR, LPSECURITY_ATTRIBUTES,
                                       LPSECURITY_ATTRIBUTES, BOOL, DWORD,
                                       LPVOID, LPCWSTR, LPSTARTUPINFOW,
                                       LPPROCESS_INFORMATION);
typedef BOOL(WINAPI* CreateProcessAsUserW_t)(HANDLE, LPCWSTR, LPWSTR,
                                             LPSECURITY_ATTRIBUTES,
                                             LPSECURITY_ATTRIBUTES, BOOL, DWORD,
                                             LPVOID, LPCWSTR, LPSTARTUPINFOW,
                                             LPPROCESS_INFORMATION);
typedef void* (*CreateCdmInstance_t)(int, const char*, uint32_t, GetCdmHostFunc,
                                     void*);
typedef void (*TimerExpired_t)(cdm::ContentDecryptionModule_10*, void* context);

static GetProcAddress_t fpGetProcAddress = NULL;
static CreateProcessW_t fpCreateProcessW = NULL;
static CreateProcessAsUserW_t fpCreateProcessAsUserW = NULL;
static CreateCdmInstance_t create = NULL;
static TimerExpired_t fpTimerExpired = NULL;

std::atomic<bool> isCreated{false};
cdm::ContentDecryptionModule_10* gWidevine = nullptr;

void DetourTimerExpired(cdm::ContentDecryptionModule_10* cdm, void* context) {
    LOG("TimerExpired()\n");

    gWidevine = cdm;

    MH_DisableHook(MH_ALL_HOOKS);
    fpTimerExpired(cdm, context);
}

static DWORD WINAPI waitAndHook(LPVOID) {
  // Wait for CDM Create
  while (!isCreated.load(std::memory_order_acquire));

  // Wait for Update call
  Sleep(2000);
  LOG("Hooking Decrypt\n");
  // Hook Decrypt
  HMODULE hMod = GetModuleHandleA("widevinecdm.dll");

   void* target = (void*)((uintptr_t)hMod + 0x1D4E60);  // TimerExpired
  MH_CreateHook(target, &DetourTimerExpired,
      reinterpret_cast<LPVOID*>(&fpTimerExpired));
  MH_EnableHook(MH_ALL_HOOKS);

  LOG("Waiting for files\n");
  while (true) {
    if (gWidevine) {
      process_files();
    }
    Sleep(1000);
  }

  return 0;
}

void* DetourCreateCdmInstance(int cdm_interface_version, const char* key_system,
                              uint32_t key_system_size,
                              GetCdmHostFunc get_cdm_host_func,
                              void* user_data) {
  LOG("CreateCdmInstance()\n");
  if (cdm_interface_version != 10) {
    return nullptr;
  }
  isCreated = true;

  void* cdm = create(cdm_interface_version, key_system, key_system_size,
                     get_cdm_host_func, user_data);

  // We retrieve the offset of TimerExpired using the object virtual table.
  // One time operation per Widevine version. Otherwise, keep commented for VMP.

   //HMODULE hMod = GetModuleHandleA("widevinecdm.dll");
   //void** vtable = *(void***)cdm;
   //void* offset = vtable[8];
   //std::ofstream("offset.txt", std::ios::app) << "TimerExpired offset: "
   //<< (uintptr_t)offset - (uintptr_t)hMod << std::endl;

  return cdm;
}

static const wchar_t* GetCurrentProcessName() {
  wchar_t path[MAX_PATH]{};

  GetModuleFileNameW(nullptr, path, MAX_PATH);

  const wchar_t* name = wcsrchr(path, L'\\');
  name = name ? name + 1 : path;

  return name;
}

static BOOL injectDLL(HANDLE hProcess) {
  SIZE_T nLength;
  LPVOID lpLoadLibraryW;
  LPVOID lpRemoteString;

  HMODULE hKrnl = GetModuleHandle(L"KERNEL32.DLL");
  if (!hKrnl) {
    fprintf(stderr, "DLL INJECTION - Error on GetModuleHandle\n");
    return FALSE;
  }

  lpLoadLibraryW = GetProcAddress(hKrnl, "LoadLibraryW");
  if (!lpLoadLibraryW) {
    fprintf(stderr, "DLL INJECTION - Error on GetProcAddress\n");
    return FALSE;
  }

  nLength = wcslen(DLL_PATH) * sizeof(WCHAR);

  lpRemoteString =
      VirtualAllocEx(hProcess, NULL, nLength + 1, MEM_COMMIT, PAGE_READWRITE);
  if (!lpRemoteString) {
    fprintf(stderr, "DLL INJECTION - Error on VirtualAllocEx\n");
    return FALSE;
  }

  if (!WriteProcessMemory(hProcess, lpRemoteString, DLL_PATH, nLength, NULL)) {
    fprintf(stderr, "DLL INJECTION - Error on WriteProcessMemory\n");
    return FALSE;
  }

  HANDLE hThread = CreateRemoteThread(hProcess, NULL, NULL,
                                      (LPTHREAD_START_ROUTINE)lpLoadLibraryW,
                                      lpRemoteString, NULL, NULL);
  if (!hThread) {
    fprintf(stderr, "DLL INJECTION - Error on CreateRemoteThread\n");
    return FALSE;
  }

  WaitForSingleObject(hThread, INFINITE);
  VirtualFreeEx(hProcess, lpRemoteString, 0, MEM_RELEASE);
  CloseHandle(hThread);

  return TRUE;
}

FARPROC WINAPI DetourGetProcAddress(HMODULE hModule, LPCSTR lpProcName) {
  if (strcmp(lpProcName, "CreateCdmInstance") == 0) {
    LOG("Hooking CreateCdmInstance()\n");
    create = (CreateCdmInstance_t)fpGetProcAddress(hModule, lpProcName);
    return (FARPROC)DetourCreateCdmInstance;
  }
  return fpGetProcAddress(hModule, lpProcName);
}

BOOL DetourCreateProcessW(LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
                          LPSECURITY_ATTRIBUTES lpProcessAttributes,
                          LPSECURITY_ATTRIBUTES lpThreadAttributes,
                          BOOL bInheritHandles, DWORD dwCreationFlags,
                          LPVOID lpEnvironment, LPCWSTR lpCurrentDirectory,
                          LPSTARTUPINFOW lpStartupInfo,
                          LPPROCESS_INFORMATION lpProcessInformation) {
  bool inject =
      lpCommandLine != NULL && (wcsstr(lpCommandLine, L"firefox.exe") ||
                                wcsstr(lpCommandLine, L"plugin-container.exe"));

  if (inject) {
    dwCreationFlags |= CREATE_SUSPENDED;
  }

  BOOL result = fpCreateProcessW(
      lpApplicationName, lpCommandLine, lpProcessAttributes, lpThreadAttributes,
      bInheritHandles, dwCreationFlags, lpEnvironment, lpCurrentDirectory,
      lpStartupInfo, lpProcessInformation);

  if (!result) {
    return result;
  }

  if (inject) {
    injectDLL(lpProcessInformation->hProcess);
    ResumeThread(lpProcessInformation->hThread);
  }

  return result;
}

BOOL DetourCreateProcessAsUserW(
    HANDLE hToken, LPCWSTR lpApplicationName, LPWSTR lpCommandLine,
    LPSECURITY_ATTRIBUTES lpProcessAttributes,
    LPSECURITY_ATTRIBUTES lpThreadAttributes, BOOL bInheritHandles,
    DWORD dwCreationFlags, LPVOID lpEnvironment, LPCWSTR lpCurrentDirectory,
    LPSTARTUPINFOW lpStartupInfo, LPPROCESS_INFORMATION lpProcessInformation) {
  bool inject =
      lpCommandLine != NULL && wcsstr(lpCommandLine, L"plugin-container.exe");

  if (inject) {
    dwCreationFlags |= CREATE_SUSPENDED;
  }

  BOOL result = fpCreateProcessAsUserW(
      hToken, lpApplicationName, lpCommandLine, lpProcessAttributes,
      lpThreadAttributes, bInheritHandles, dwCreationFlags, lpEnvironment,
      lpCurrentDirectory, lpStartupInfo, lpProcessInformation);

  if (!result) {
    return result;
  }

  if (inject) {
    injectDLL(lpProcessInformation->hProcess);
    ResumeThread(lpProcessInformation->hThread);
  }

  return result;
}

static void WINAPI MainThread(void) {
  // Initialize MinHook.
  if (MH_Initialize() != MH_OK) {
    return;
  }

  HMODULE hKernel = GetModuleHandleW(L"KERNEL32.dll");

  bool isWdv = wcsstr(GetCurrentProcessName(), L"plugin-container.exe");
  if (isWdv) {
    LOG("Hooking Widevine\n");
    CreateThread(nullptr, 0, waitAndHook, nullptr, 0, nullptr);

    MH_CreateHook(GetProcAddress(hKernel, "GetProcAddress"),
                  &DetourGetProcAddress,
                  reinterpret_cast<LPVOID*>(&fpGetProcAddress));
  } else {
    HMODULE hAdv = GetModuleHandleW(L"Advapi32.dll");
    MH_CreateHook(GetProcAddress(hKernel, "CreateProcessW"),
                  &DetourCreateProcessW,
                  reinterpret_cast<LPVOID*>(&fpCreateProcessW));
    MH_CreateHook(GetProcAddress(hAdv, "CreateProcessAsUserW"),
                  &DetourCreateProcessAsUserW,
                  reinterpret_cast<LPVOID*>(&fpCreateProcessAsUserW));
  }

  // Enable hooks.
  if (MH_EnableHook(MH_ALL_HOOKS) != MH_OK) {
    return;
  }
}

BOOL WINAPI DllMain(HINSTANCE hInstance, DWORD fdwReason, LPVOID lpvReserved) {
  if (fdwReason == DLL_PROCESS_ATTACH) {
    MainThread();
  }

  return TRUE;
}
