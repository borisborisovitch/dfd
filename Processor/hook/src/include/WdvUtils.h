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

#ifndef WDVUTILS_H_
#define WDVUTILS_H_

#include <cstdlib>

#include "content_decryption_module.h"

class WdvBuffer : public cdm::Buffer {
 public:
  WdvBuffer(size_t aSize);

  ~WdvBuffer() override;

  void Destroy() override;

  uint32_t Capacity() const override;

  uint8_t* Data() override;

  void SetSize(uint32_t aSize) override;

  uint32_t Size() const override;

 private:
  uint8_t* mData;
  uint32_t mSize;
};

class WdvDecryptedBlock : public cdm::DecryptedBlock {
 public:
  WdvDecryptedBlock();

  ~WdvDecryptedBlock();

  void SetDecryptedBuffer(cdm::Buffer* aBuffer) override;

  cdm::Buffer* DecryptedBuffer() override;

  void SetTimestamp(int64_t aTimestamp) override;

  int64_t Timestamp() const override;

 private:
  cdm::Buffer* mBuffer;
  int64_t mTimestamp;
};

class WdvVideoFrame : public cdm::VideoFrame {
 public:
  WdvVideoFrame();
  ~WdvVideoFrame();
  void SetFormat(cdm::VideoFormat format) override;
  cdm::VideoFormat Format() const override;

  void SetSize(cdm::Size size) override;
  cdm::Size Size() const override;

  void SetFrameBuffer(cdm::Buffer* frame_buffer) override;
  cdm::Buffer* FrameBuffer() override;

  void SetPlaneOffset(cdm::VideoPlane plane, uint32_t offset) override;
  uint32_t PlaneOffset(cdm::VideoPlane plane) override;

  void SetStride(cdm::VideoPlane plane, uint32_t stride) override;
  uint32_t Stride(cdm::VideoPlane plane) override;

  void SetTimestamp(int64_t timestamp) override;
  int64_t Timestamp() const override;

 private:
  cdm::VideoFormat format;
  cdm::Size size;
  cdm::Buffer* frame_buffer;
  uint32_t offsets[3] = {0};
  uint32_t strides[3] = {0};
  int64_t timestamp;
};

#endif  // WDVUTILS_H_
