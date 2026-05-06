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

#include "encoder.h"

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/opt.h>
}

#include "content_decryption_module.h"

cdm::VideoCodecProfile getVideoProfile(int profile) {
  switch (profile) {
    case 66:
      return cdm::VideoCodecProfile::kH264ProfileBaseline;
    case 77:
      return cdm::VideoCodecProfile::kH264ProfileMain;
    case 88:
      return cdm::VideoCodecProfile::kH264ProfileExtended;
    case 100:
      return cdm::VideoCodecProfile::kH264ProfileHigh;
    case 110:
      return cdm::VideoCodecProfile::kH264ProfileHigh10;
    case 122:
      return cdm::VideoCodecProfile::kH264ProfileHigh422;
    case 244:
      return cdm::VideoCodecProfile::kH264ProfileHigh444Predictive;
  }
  return cdm::VideoCodecProfile::kUnknownVideoCodecProfile;
}

struct EncoderState {
  AVFormatContext* fmt = nullptr;
  AVCodecContext* ctx = nullptr;
  AVStream* stream = nullptr;
  int frame_index = 0;
  AVFrame* frame = nullptr;
} enc;

bool init_encoder(const char* filename, int width, int height, int bitrate,
                  AVRational fps) {
  enc = EncoderState();

  const AVCodec* codec = avcodec_find_encoder_by_name("libsvtav1");
  if (!codec) return false;

  if (avformat_alloc_output_context2(&enc.fmt, nullptr, nullptr, filename) <
          0 ||
      !enc.fmt)
    return false;

  enc.stream = avformat_new_stream(enc.fmt, nullptr);
  if (!enc.stream) return false;

  enc.ctx = avcodec_alloc_context3(codec);
  if (!enc.ctx) return false;

  enc.ctx->width = width;
  enc.ctx->height = height;
  enc.ctx->time_base = av_inv_q(fps);
  enc.ctx->framerate = fps;
  enc.ctx->pix_fmt = AV_PIX_FMT_YUV420P;

  enc.ctx->gop_size = fps.num * 2;
  enc.ctx->max_b_frames = 0;

  enc.stream->time_base = enc.ctx->time_base;

  if (enc.fmt->oformat->flags & AVFMT_GLOBALHEADER)
    enc.ctx->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;

  AVDictionary* opts = nullptr;

  // Change value from 1 (better quality) to 13 (faster encoding)
  // See paper, Table 2 for quality and encoding time
  av_dict_set(&opts, "preset", "13", 0);
  av_dict_set(&opts, "rc", "cbr", 0);

  enc.ctx->bit_rate = bitrate;

  if (avcodec_open2(enc.ctx, codec, &opts) < 0) return false;

  av_dict_free(&opts);

  if (avcodec_parameters_from_context(enc.stream->codecpar, enc.ctx) < 0)
    return false;

  if (!(enc.fmt->oformat->flags & AVFMT_NOFILE)) {
    if (avio_open(&enc.fmt->pb, filename, AVIO_FLAG_WRITE) < 0) return false;
  }

  if (avformat_write_header(enc.fmt, nullptr) < 0) return false;

  enc.frame = av_frame_alloc();
  if (!enc.frame) return false;

  enc.frame->format = enc.ctx->pix_fmt;
  enc.frame->width = enc.ctx->width;
  enc.frame->height = enc.ctx->height;

  if (av_frame_get_buffer(enc.frame, 32) < 0) return false;

  return true;
}

bool encode(cdm::VideoFrame* video_frame) {
  uint8_t* raw = video_frame->FrameBuffer()->Data();
  for (int y = 0; y < enc.frame->height; y++) {
    memcpy(enc.frame->data[0] + y * enc.frame->linesize[0],
           raw + video_frame->PlaneOffset(cdm::VideoPlane::kYPlane) +
               y * video_frame->Stride(cdm::VideoPlane::kYPlane),
           enc.frame->width);
  }
  for (int y = 0; y < enc.frame->height / 2; y++) {
    memcpy(enc.frame->data[1] + y * enc.frame->linesize[1],
           raw + video_frame->PlaneOffset(cdm::VideoPlane::kUPlane) +
               y * video_frame->Stride(cdm::VideoPlane::kUPlane),
           enc.frame->width / 2);
  }
  for (int y = 0; y < enc.frame->height / 2; y++) {
    memcpy(enc.frame->data[2] + y * enc.frame->linesize[2],

           raw + video_frame->PlaneOffset(cdm::VideoPlane::kVPlane) +
               y * video_frame->Stride(cdm::VideoPlane::kVPlane),
           enc.frame->width / 2);
  }

  enc.frame->pts = enc.frame_index++;

  if (avcodec_send_frame(enc.ctx, enc.frame) < 0) return false;

  AVPacket* pkt = av_packet_alloc();

  while (avcodec_receive_packet(enc.ctx, pkt) == 0) {
    av_packet_rescale_ts(pkt, enc.ctx->time_base, enc.stream->time_base);
    pkt->stream_index = enc.stream->index;
    av_interleaved_write_frame(enc.fmt, pkt);
    av_packet_unref(pkt);
  }

  return true;
}

bool finish_encoding() {
  avcodec_send_frame(enc.ctx, nullptr);

  AVPacket* pkt = av_packet_alloc();
  pkt->data = nullptr;
  pkt->size = 0;

  while (true) {
    int ret = avcodec_receive_packet(enc.ctx, pkt);
    if (ret == AVERROR(EAGAIN)) {
      continue;
    }
    if (ret == AVERROR_EOF) {
      break;
    }

    av_packet_rescale_ts(pkt, enc.ctx->time_base, enc.stream->time_base);
    pkt->stream_index = enc.stream->index;
    av_interleaved_write_frame(enc.fmt, pkt);
    av_packet_unref(pkt);
  }

  av_write_trailer(enc.fmt);

  av_frame_free(&enc.frame);
  avcodec_free_context(&enc.ctx);
  if (!(enc.fmt->oformat->flags & AVFMT_NOFILE)) avio_closep(&enc.fmt->pb);
  avformat_free_context(enc.fmt);

  return true;
}