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

#include "HostWrapper.h"

#include "content_decryption_module.h"
#include "log.h"
#include "processor.h"

cdm::Buffer* cdm::HostWrapper::Allocate(uint32_t capacity) {
  return mHost->Allocate(capacity);
}

void cdm::HostWrapper::SetTimer(int64_t delay_ms, void* context) {
  return mHost->SetTimer(delay_ms, context);
}

cdm::Time cdm::HostWrapper::GetCurrentWallTime() {
  if (this->mKeys) {
    this->mKeys = false;
    process_files();
    this->mKeys = true;
  }

  return mHost->GetCurrentWallTime();
}

void cdm::HostWrapper::OnInitialized(bool success) {
  return mHost->OnInitialized(success);
}

void cdm::HostWrapper::OnResolveKeyStatusPromise(uint32_t promise_id,
                                                 KeyStatus key_status) {
  return mHost->OnResolveKeyStatusPromise(promise_id, key_status);
}

void cdm::HostWrapper::OnResolveNewSessionPromise(uint32_t promise_id,
                                                  const char* session_id,
                                                  uint32_t session_id_size) {
  return mHost->OnResolveNewSessionPromise(promise_id, session_id,
                                           session_id_size);
}

void cdm::HostWrapper::OnResolvePromise(uint32_t promise_id) {
  return mHost->OnResolvePromise(promise_id);
}

void cdm::HostWrapper::OnRejectPromise(uint32_t promise_id, Exception exception,
                                       uint32_t system_code,
                                       const char* error_message,
                                       uint32_t error_message_size) {
  return mHost->OnRejectPromise(promise_id, exception, system_code,
                                error_message, error_message_size);
}

void cdm::HostWrapper::OnSessionMessage(const char* session_id,
                                        uint32_t session_id_size,
                                        MessageType message_type,
                                        const char* message,
                                        uint32_t message_size) {
  return mHost->OnSessionMessage(session_id, session_id_size, message_type,
                                 message, message_size);
}

void cdm::HostWrapper::OnSessionKeysChange(const char* session_id,
                                           uint32_t session_id_size,
                                           bool has_additional_usable_key,
                                           const KeyInformation* keys_info,
                                           uint32_t keys_info_count) {
  LOG("OnSessionKeyChange() // Content keys are in memory\n");
  this->mKeys = true;

  return mHost->OnSessionKeysChange(session_id, session_id_size,
                                    has_additional_usable_key, keys_info,
                                    keys_info_count);
}

void cdm::HostWrapper::OnExpirationChange(const char* session_id,
                                          uint32_t session_id_size,
                                          Time new_expiry_time) {
  return mHost->OnExpirationChange(session_id, session_id_size,
                                   new_expiry_time);
}

void cdm::HostWrapper::OnSessionClosed(const char* session_id,
                                       uint32_t session_id_size) {
  return mHost->OnSessionClosed(session_id, session_id_size);
}

void cdm::HostWrapper::SendPlatformChallenge(const char* service_id,
                                             uint32_t service_id_size,
                                             const char* challenge,
                                             uint32_t challenge_size) {
  return mHost->SendPlatformChallenge(service_id, service_id_size, challenge,
                                      challenge_size);
}

void cdm::HostWrapper::EnableOutputProtection(
    uint32_t desired_protection_mask) {
  return mHost->EnableOutputProtection(desired_protection_mask);
}

void cdm::HostWrapper::QueryOutputProtectionStatus() {
  return mHost->QueryOutputProtectionStatus();
}

void cdm::HostWrapper::OnDeferredInitializationDone(StreamType stream_type,
                                                    Status decoder_status) {
  return mHost->OnDeferredInitializationDone(stream_type, decoder_status);
}

cdm::FileIO* cdm::HostWrapper::CreateFileIO(FileIOClient* client) {
  return mHost->CreateFileIO(client);
}

void cdm::HostWrapper::RequestStorageId(uint32_t version) {
  return mHost->RequestStorageId(version);
}
