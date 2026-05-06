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

#ifndef HOSTWRAPPER_H_
#define HOSTWRAPPER_H_

#include "content_decryption_module.h"

namespace cdm {

class HostWrapper : public Host_10 {
 public:
  HostWrapper(Host_10* host)
      : mHost(host), mKeysInfo(nullptr), mAlloc(false), mKeys(false) {};

  Buffer* Allocate(uint32_t capacity) override;

  void SetTimer(int64_t delay_ms, void* context) override;

  Time GetCurrentWallTime() override;

  void OnInitialized(bool success) override;

  void OnResolveKeyStatusPromise(uint32_t promise_id,
                                 KeyStatus key_status) override;

  void OnResolveNewSessionPromise(uint32_t promise_id, const char* session_id,
                                  uint32_t session_id_size) override;

  void OnResolvePromise(uint32_t promise_id) override;

  void OnRejectPromise(uint32_t promise_id, Exception exception,
                       uint32_t system_code, const char* error_message,
                       uint32_t error_message_size) override;

  void OnSessionMessage(const char* session_id, uint32_t session_id_size,
                        MessageType message_type, const char* message,
                        uint32_t message_size) override;

  void OnSessionKeysChange(const char* session_id, uint32_t session_id_size,
                           bool has_additional_usable_key,
                           const KeyInformation* keys_info,
                           uint32_t keys_info_count) override;

  void OnExpirationChange(const char* session_id, uint32_t session_id_size,
                          Time new_expiry_time) override;

  void OnSessionClosed(const char* session_id,
                       uint32_t session_id_size) override;

  void SendPlatformChallenge(const char* service_id, uint32_t service_id_size,
                             const char* challenge,
                             uint32_t challenge_size) override;

  void EnableOutputProtection(uint32_t desired_protection_mask) override;

  void QueryOutputProtectionStatus() override;

  void OnDeferredInitializationDone(StreamType stream_type,
                                    Status decoder_status) override;

  FileIO* CreateFileIO(FileIOClient* client) override;

  void RequestStorageId(uint32_t version) override;

 private:
  Host_10* mHost;
  KeyInformation** mKeysInfo;
  bool mAlloc;
  bool mKeys;
};

}  // namespace cdm
#endif  // HOSTWRAPPER_H_
