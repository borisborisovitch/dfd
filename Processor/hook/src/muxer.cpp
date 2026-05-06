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

#include "muxer.h"

extern "C" {
#include <libavformat/avformat.h>
}

struct MuxState {
  AVFormatContext* fmt = nullptr;
  AVStream* vstream = nullptr;
  AVStream* astream = nullptr;
  AVRational timebase = {0, 0};
  int64_t video_pts = 0;
  int64_t audio_pts = 0;
} mux;

bool init_aac_muxer(const char* filename, int sample_rate, int frame_size,
                    int nb_channels, const uint8_t* aac_extradata,
                    int aac_extradata_size) {
  mux = MuxState();
  if (avformat_alloc_output_context2(&mux.fmt, nullptr, nullptr, filename) < 0)
    return false;

  mux.astream = avformat_new_stream(mux.fmt, nullptr);
  if (!mux.astream) return false;

  mux.astream->codecpar->codec_type = AVMEDIA_TYPE_AUDIO;
  mux.astream->codecpar->codec_id = AV_CODEC_ID_AAC;

  mux.astream->codecpar->sample_rate = sample_rate;
  mux.astream->codecpar->frame_size = frame_size;

  av_channel_layout_default(&mux.astream->codecpar->ch_layout, nb_channels);

  mux.astream->time_base = AVRational{1, sample_rate};
  mux.timebase = AVRational{1, sample_rate};

  mux.astream->codecpar->extradata = (uint8_t*)av_malloc(aac_extradata_size);
  memcpy(mux.astream->codecpar->extradata, aac_extradata, aac_extradata_size);
  mux.astream->codecpar->extradata_size = aac_extradata_size;

  if (!(mux.fmt->oformat->flags & AVFMT_NOFILE)) {
    if (avio_open(&mux.fmt->pb, filename, AVIO_FLAG_WRITE) < 0) return false;
  }

  if (avformat_write_header(mux.fmt, nullptr) < 0) return false;

  return true;
}

bool init_h264_muxer(const char* filename, int width, int height,
                     AVRational fps, const uint8_t* h264_extradata,
                     int h264_extradata_size) {
  mux = MuxState();
  if (avformat_alloc_output_context2(&mux.fmt, nullptr, nullptr, filename) < 0)
    return false;

  mux.vstream = avformat_new_stream(mux.fmt, nullptr);
  if (!mux.vstream) return false;

  mux.vstream->codecpar->codec_type = AVMEDIA_TYPE_VIDEO;
  mux.vstream->codecpar->codec_id = AV_CODEC_ID_H264;

  mux.vstream->codecpar->width = width;
  mux.vstream->codecpar->height = height;
  mux.timebase = av_inv_q(fps);

  mux.vstream->codecpar->extradata = (uint8_t*)av_malloc(h264_extradata_size);
  memcpy(mux.vstream->codecpar->extradata, h264_extradata, h264_extradata_size);
  mux.vstream->codecpar->extradata_size = h264_extradata_size;

  if (!(mux.fmt->oformat->flags & AVFMT_NOFILE)) {
    if (avio_open(&mux.fmt->pb, filename, AVIO_FLAG_WRITE) < 0) return false;
  }

  if (avformat_write_header(mux.fmt, nullptr) < 0) return false;

  return true;
}

bool mux_packet(const uint8_t* data, int size) {
  AVPacket* pkt = av_packet_alloc();

  pkt->data = (uint8_t*)data;
  pkt->size = size;

  if (mux.vstream) {
    pkt->stream_index = mux.vstream->index;
    pkt->pts = pkt->dts = mux.video_pts++;
    pkt->duration = 1;
    pkt->pos = -1;
    av_packet_rescale_ts(pkt, mux.timebase, mux.vstream->time_base);
  } else {
    pkt->stream_index = mux.astream->index;
    pkt->pts = pkt->dts = mux.audio_pts;
    pkt->duration = mux.astream->codecpar->frame_size;
    mux.audio_pts += pkt->duration;
    av_packet_rescale_ts(pkt, mux.timebase, mux.astream->time_base);
  }

  if (av_interleaved_write_frame(mux.fmt, pkt) < 0) return false;

  return true;
}

bool finish_mux() {
  if (!mux.fmt) return false;

  av_write_trailer(mux.fmt);

  if (!(mux.fmt->oformat->flags & AVFMT_NOFILE)) avio_closep(&mux.fmt->pb);

  avformat_free_context(mux.fmt);
  mux.fmt = nullptr;

  return true;
}
