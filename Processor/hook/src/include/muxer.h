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

#ifndef MUXER_H_
#define MUXER_H_

extern "C" {
#include <libavutil/rational.h>
}

bool init_aac_muxer(const char* filename, int sample_rate, int frame_size,
                    int nb_channels, const uint8_t* aac_extradata,
                    int aac_extradata_size);

bool init_h264_muxer(const char* filename, int width, int height,
                     AVRational fps, const uint8_t* h264_extradata,
                     int h264_extradata_size);

bool mux_packet(const uint8_t* data, int size);

bool finish_mux();

#endif  // MUXER_H_