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

#include "WdvUtils.h"

WdvBuffer::WdvBuffer(size_t aSize) : mSize(aSize) {
  this->mData = (uint8_t*)malloc(this->mSize * sizeof(uint8_t));
}

WdvBuffer::~WdvBuffer() { free(this->mData); }

void WdvBuffer::Destroy() { delete this; }

uint32_t WdvBuffer::Capacity() const { return this->mSize; }

uint8_t* WdvBuffer::Data() { return this->mData; }

void WdvBuffer::SetSize(uint32_t aSize) {
  this->mSize = aSize;
  this->mData = (uint8_t*)realloc(this->mData, this->mSize);
}

uint32_t WdvBuffer::Size() const { return this->mSize; }

WdvDecryptedBlock::WdvDecryptedBlock() : mBuffer(nullptr), mTimestamp(0) {}

WdvDecryptedBlock::~WdvDecryptedBlock() {
  this->mBuffer->Destroy();
  this->mTimestamp = 0;
}

void WdvDecryptedBlock::SetDecryptedBuffer(cdm::Buffer* aBuffer) {
  this->mBuffer = aBuffer;
}

cdm::Buffer* WdvDecryptedBlock::DecryptedBuffer() { return this->mBuffer; }

void WdvDecryptedBlock::SetTimestamp(int64_t aTimestamp) {
  this->mTimestamp = aTimestamp;
}

int64_t WdvDecryptedBlock::Timestamp() const { return this->mTimestamp; }

WdvVideoFrame::WdvVideoFrame() {}

WdvVideoFrame::~WdvVideoFrame() {};
void WdvVideoFrame::SetFormat(cdm::VideoFormat format) {
  this->format = format;
}
cdm::VideoFormat WdvVideoFrame::Format() const { return this->format; }

void WdvVideoFrame::SetSize(cdm::Size size) { this->size = size; }
cdm::Size WdvVideoFrame::Size() const { return this->size; }

void WdvVideoFrame::SetFrameBuffer(cdm::Buffer* frame_buffer) {
  this->frame_buffer = frame_buffer;
}
cdm::Buffer* WdvVideoFrame::FrameBuffer() { return this->frame_buffer; }

void WdvVideoFrame::SetPlaneOffset(cdm::VideoPlane plane, uint32_t offset) {
  this->offsets[plane] = offset;
}
uint32_t WdvVideoFrame::PlaneOffset(cdm::VideoPlane plane) {
  return this->offsets[plane];
}

void WdvVideoFrame::SetStride(cdm::VideoPlane plane, uint32_t stride) {
  this->strides[plane] = stride;
}

uint32_t WdvVideoFrame::Stride(cdm::VideoPlane plane) {
  return this->strides[plane];
}

void WdvVideoFrame::SetTimestamp(int64_t timestamp) {
  this->timestamp = timestamp;
}
int64_t WdvVideoFrame::Timestamp() const { return this->timestamp; }