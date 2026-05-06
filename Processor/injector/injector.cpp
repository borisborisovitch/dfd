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
#include <tlhelp32.h>

#include <cstdio>
#include <string>

#define DLL_PATH L"./x64/Release/hook.dll"

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

int wmain(int argc, wchar_t** argv) {
  if (argc < 2) {
    fwprintf(stderr,
             L"Missing Firefox binary path\n"
             L"USAGE: %ls <PATH/TO/firefox.exe> [args...]\n",
             argv[0]);
    exit(EXIT_FAILURE);
  }

  STARTUPINFO si;
  PROCESS_INFORMATION pi;

  ZeroMemory(&si, sizeof(si));
  si.cb = sizeof(si);
  ZeroMemory(&pi, sizeof(pi));

  wchar_t cmdline[4096];
  size_t pos = 0;

  pos += swprintf(cmdline, 4096, L"\"%ls\"", argv[1]);

  for (int i = 2; i < argc; i++) {
    pos += swprintf(cmdline + pos, 4096 - pos, L" %ls", argv[i]);
  }

  if (!CreateProcessW(NULL, cmdline, NULL, NULL, FALSE, CREATE_SUSPENDED, NULL,
                      NULL, &si, &pi)) {
    fwprintf(stderr, L"Failed to launch Firefox\n");
    exit(EXIT_FAILURE);
  }

  if (!injectDLL(pi.hProcess)) {
    fprintf(stderr, "Failed to inject DLL\n");
    exit(EXIT_FAILURE);
  }

  ResumeThread(pi.hThread);
  CloseHandle(pi.hProcess);
  CloseHandle(pi.hThread);

  printf("DLL injected\n");
}