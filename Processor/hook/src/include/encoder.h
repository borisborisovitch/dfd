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

#ifndef ENCODER_H_
#define ENCODER_H_

extern "C" {
#include <libavutil/rational.h>
}

#include "content_decryption_module.h"

cdm::VideoCodecProfile getVideoProfile(int profile);

bool init_encoder(const char* filename, int width, int height, int bitrate,
                  AVRational fps);

bool encode(cdm::VideoFrame* video_frame);

bool finish_encoding();

#endif  // ENCODER_H_