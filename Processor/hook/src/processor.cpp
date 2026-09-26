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

#include "processor.h"

#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavcodec/bsf.h>
#include <libavformat/avformat.h>
#include <libavutil/encryption_info.h>
#include <libavutil/macros.h>
}

#include "WdvUtils.h"
#include "encoder.h"
#include "log.h"
#include "muxer.h"

// #define REENCODE

int DecryptAndDecodeAndReencode(uint32_t cipher_type, const uint8_t* kid,
                                const uint8_t* iv, uint32_t iv_size,
                                uint8_t* input, uint32_t input_size,
                                uint32_t subsample_count,
                                AVSubsampleEncryptionInfo* subsamples,
                                int64_t timestamp) {
  cdm::InputBuffer_2 input_buffer = {
      .data = input,
      .data_size = input_size,
      .encryption_scheme = (cdm::EncryptionScheme)cipher_type,
      .key_id = kid,
      .key_id_size = kid ? 16U : 0U,
      .iv = iv,
      .iv_size = iv_size,
      .subsamples = (cdm::SubsampleEntry*)subsamples,
      .num_subsamples = subsample_count,
      .pattern = 0,
      .timestamp = timestamp};

  cdm::VideoFrame* frame = new WdvVideoFrame();
  if (!gWidevine->DecryptAndDecodeFrame(input_buffer, frame)) {
    encode(frame);
    frame->FrameBuffer()->Destroy();
  }
  return 1;
}

int DecryptAndRemux(uint32_t cipher_type, const uint8_t* kid, const uint8_t* iv,
                    uint32_t iv_size, uint8_t* input, uint32_t input_size,
                    uint32_t subsample_count,
                    AVSubsampleEncryptionInfo* subsamples, int64_t timestamp,
                    uint32_t crypt_byte_block = 0,
                    uint32_t skip_byte_block = 0) {
  cdm::SubsampleEntry* ss = nullptr;
  if (!subsample_count) {
    ss = (cdm::SubsampleEntry*)malloc(sizeof(cdm::SubsampleEntry));
    ss[0] = {1, input_size};
    subsample_count = 1;
  } else {
    subsamples[0].bytes_of_clear_data++;
  }

  uint8_t* buff = (uint8_t*)malloc(input_size + 1);
  buff[0] = 0xff;
  memcpy(buff + 1, input, input_size);

  cdm::InputBuffer_2 input_buffer = {
      .data = buff,
      .data_size = input_size + 1,
      .encryption_scheme = (cdm::EncryptionScheme)cipher_type,
      .key_id = kid,
      .key_id_size = kid ? 16U : 0U,
      .iv = iv,
      .iv_size = iv_size,
      .subsamples = ss ? ss : (cdm::SubsampleEntry*)subsamples,
      .num_subsamples = subsample_count,
      .pattern = {crypt_byte_block, skip_byte_block},
      .timestamp = timestamp};

  cdm::DecryptedBlock* output = new WdvDecryptedBlock();
  cdm::Status status = gWidevine->Decrypt(input_buffer, output);

  free(buff);
  if (ss) {
    free(ss);
  }

  if (status != cdm::kSuccess) {
    static bool reported_decrypt_failure = false;
    if (!reported_decrypt_failure) {
      LOG("Widevine decrypt returned status %u\n", status);
      reported_decrypt_failure = true;
    }
    return 0;
  }

  mux_packet(output->DecryptedBuffer()->Data() + 1, input_size);

  output->DecryptedBuffer()->Destroy();

  return 1;
}

bool ParseSamples(AVFormatContext* fmt_ctx) {
  AVStream* stream = nullptr;
  for (unsigned int i = 0; i < fmt_ctx->nb_streams; i++) {
    AVMediaType type = fmt_ctx->streams[i]->codecpar->codec_type;
    if (type == AVMEDIA_TYPE_VIDEO || type == AVMEDIA_TYPE_AUDIO) {
      stream = fmt_ctx->streams[i];
      break;
    }
  }

  if (!stream) {
    return false;
  }
  AVCodecParameters* codecpar = stream->codecpar;

  bool isVideo = codecpar->codec_type == AVMEDIA_TYPE_VIDEO;
  const char* audio_limit = std::getenv("AUDIO_MAX_SECONDS");
  const int64_t max_audio_samples =
      !isVideo && audio_limit
          ? std::atoll(audio_limit) * codecpar->sample_rate
          : 0;
  int64_t processed_audio_samples = 0;
  int64_t decrypted_audio_packets = 0;

  AVPacket* pkt = av_packet_alloc();

#ifdef REENCODE
  const AVBitStreamFilter* bsf = nullptr;
  AVBSFContext* bsf_ctx = nullptr;
  AVPacket* filtered_pkt = nullptr;
  if (isVideo) {
    bsf = av_bsf_get_by_name("h264_mp4toannexb");
    av_bsf_alloc(bsf, &bsf_ctx);
    avcodec_parameters_copy(bsf_ctx->par_in, codecpar);
    av_bsf_init(bsf_ctx);
    filtered_pkt = av_packet_alloc();
  }
#endif
  av_seek_frame(fmt_ctx, stream->index, 0, 0);
  while (av_read_frame(fmt_ctx, pkt) >= 0) {
#ifdef REENCODE
    if (isVideo) {
      size_t size = pkt->size;
      av_bsf_send_packet(bsf_ctx, pkt);
      while (av_bsf_receive_packet(bsf_ctx, filtered_pkt) == 0) {
        AVEncryptionInfo* enc_info = nullptr;
        size_t side_data_size;
        uint8_t* side_data = av_packet_get_side_data(
            filtered_pkt, AV_PKT_DATA_ENCRYPTION_INFO, &side_data_size);
        if (side_data_size) {
          enc_info = reinterpret_cast<AVEncryptionInfo*>(
              av_encryption_info_get_side_data(side_data, side_data_size));
        }

        if (enc_info) {
          enc_info->subsamples[0].bytes_of_clear_data +=
              filtered_pkt->size - size;
          DecryptAndDecodeAndReencode(
              1, enc_info->key_id, enc_info->iv, enc_info->iv_size,
              filtered_pkt->data, filtered_pkt->size, enc_info->subsample_count,
              enc_info->subsamples, 0);
        } else {
          DecryptAndDecodeAndReencode(0, NULL, NULL, 0, filtered_pkt->data,
                                      filtered_pkt->size, 0, NULL, 0);
        }
        av_packet_unref(filtered_pkt);
      }
    } else {
#endif
      if (pkt->stream_index == stream->index) {
        AVEncryptionInfo* enc_info = nullptr;
        size_t side_data_size;
        uint8_t* side_data = av_packet_get_side_data(
            pkt, AV_PKT_DATA_ENCRYPTION_INFO, &side_data_size);
        if (side_data_size) {
          enc_info = reinterpret_cast<AVEncryptionInfo*>(
              av_encryption_info_get_side_data(side_data, side_data_size));
        }

        if (enc_info) {
          static bool reported_scheme = false;
          if (!reported_scheme) {
            LOG("Encrypted sample scheme: %c%c%c%c; pattern %u/%u; "
                "AAC frame size %d\n",
                (enc_info->scheme >> 24) & 0xff,
                (enc_info->scheme >> 16) & 0xff,
                (enc_info->scheme >> 8) & 0xff,
                enc_info->scheme & 0xff,
                enc_info->crypt_byte_block,
                enc_info->skip_byte_block,
                codecpar->frame_size);
            reported_scheme = true;
          }
        }

        int decrypted = 0;
        if (enc_info) {
          uint32_t cipher_type = 0;
          if (enc_info->scheme == MKBETAG('c', 'e', 'n', 'c')) {
            cipher_type = 1;
          } else if (enc_info->scheme == MKBETAG('c', 'b', 'c', 's')) {
            cipher_type = 2;
          } else {
            LOG("Unsupported encrypted sample scheme: %08x\n",
                enc_info->scheme);
            break;
          }
          decrypted = DecryptAndRemux(
              cipher_type, enc_info->key_id, enc_info->iv, enc_info->iv_size,
              pkt->data, pkt->size, enc_info->subsample_count,
              enc_info->subsamples, 0, enc_info->crypt_byte_block,
              enc_info->skip_byte_block);
        } else {
          decrypted = DecryptAndRemux(0, NULL, NULL, 0, pkt->data, pkt->size, 0,
                                      NULL, 0);
        }
        if (!isVideo && decrypted) {
          decrypted_audio_packets++;
          if (max_audio_samples > 0) {
            processed_audio_samples +=
                codecpar->frame_size > 0 ? codecpar->frame_size : 1024;
          }
        }
        av_packet_unref(pkt);
        if (max_audio_samples > 0 &&
            processed_audio_samples >= max_audio_samples) {
          LOG("Reached configured audio sample limit\n");
          break;
        }
      }
#ifdef REENCODE
    }
#endif
  }
  av_packet_free(&pkt);

#ifdef REENCODE
  if (isVideo) {
    av_packet_free(&filtered_pkt);
    av_bsf_free(&bsf_ctx);
  }
#endif

  if (!isVideo) {
    LOG("Decrypted %lld AAC packets\n",
        static_cast<long long>(decrypted_audio_packets));
  }
  return isVideo || decrypted_audio_packets > 0;
}

// Metadata struct
struct metadata {
  AVMediaType type;
  AVCodecID codec;
  int profile;
  int level;
  uint8_t* extradata;
  uint32_t extradataSize;
  int width;
  int height;
  int bitrate;
  AVRational fps;
  int sample_rate;
  int frame_size;
  int nb_channels;
};

// Extract video metadata from FFmpeg
bool get_metadata(AVFormatContext* fmt_ctx, metadata& metadata) {
  AVStream* stream = nullptr;
  for (unsigned int i = 0; i < fmt_ctx->nb_streams; i++) {
    AVMediaType type = fmt_ctx->streams[i]->codecpar->codec_type;
    if (type == AVMEDIA_TYPE_VIDEO || type == AVMEDIA_TYPE_AUDIO) {
      stream = fmt_ctx->streams[i];
      metadata.type = type;
      break;
    }
  }

  if (!stream) {
    LOG("No video or audio stream found\n");
    return false;
  }

  AVCodecParameters* codecpar = stream->codecpar;

  // Check codec
  if (codecpar->codec_id != AV_CODEC_ID_H264 &&
      codecpar->codec_id != AV_CODEC_ID_AAC) {
    LOG("Not H264 or AAC\n");
    return false;
  }

  // Check if encrypted
  bool isEncrypted = av_packet_side_data_get(codecpar->coded_side_data,
                                             codecpar->nb_coded_side_data,
                                             AV_PKT_DATA_ENCRYPTION_INIT_INFO);

  // Extradata
  metadata.extradata = (uint8_t*)malloc(codecpar->extradata_size);
  memcpy(metadata.extradata, codecpar->extradata, codecpar->extradata_size);
  metadata.extradataSize = codecpar->extradata_size;

  if (metadata.type == AVMEDIA_TYPE_AUDIO) {
    metadata.sample_rate = codecpar->sample_rate;
    metadata.frame_size = codecpar->frame_size > 0 ? codecpar->frame_size : 1024;
    metadata.nb_channels = codecpar->ch_layout.nb_channels;
    return true;
  }

  const AVCodec* codec = avcodec_find_decoder(codecpar->codec_id);
  if (!codec) {
    LOG("Unsupported codec\n");
    return false;
  }

  // Open codec to get context info
  AVCodecContext* codec_ctx = avcodec_alloc_context3(codec);
  avcodec_parameters_to_context(codec_ctx, codecpar);
  if (avcodec_open2(codec_ctx, codec, nullptr) < 0) {
    LOG("Failed to open codec\n");
    return false;
  }

  // Fill metadata
  metadata.codec = codecpar->codec_id;
  metadata.profile = codecpar->profile;
  metadata.level = codecpar->level;
  metadata.width = codecpar->width;
  metadata.height = codecpar->height;

  // Frame Rate
  metadata.fps = av_guess_frame_rate(fmt_ctx, stream, nullptr);

  // Bitrate
  int64_t duration = stream->duration * av_q2d(stream->time_base);
  int64_t file_size = avio_size(fmt_ctx->pb);
  if (file_size <= 0 || duration <= 0) {
    metadata.bitrate = 0;
  } else {
    metadata.bitrate = (int64_t)((file_size * 8) / duration);
  }

  // Check Encryption at sample level
  if (!isEncrypted) {
    AVPacket* pkt = av_packet_alloc();
    while (av_read_frame(fmt_ctx, pkt) >= 0) {
      if (pkt->stream_index == stream->index) {
        size_t side_data_size;
        uint8_t* side_data = av_packet_get_side_data(
            pkt, AV_PKT_DATA_ENCRYPTION_INFO, &side_data_size);
        if (side_data_size) {
          isEncrypted = reinterpret_cast<AVEncryptionInfo*>(
              av_encryption_info_get_side_data(side_data, side_data_size));
          break;
        }
      }
      av_packet_unref(pkt);
    }
  }

  avcodec_free_context(&codec_ctx);

  if (!isEncrypted) {
    LOG("File is not ecrypted\n");
    return false;
  }

  return true;
}

bool process_file(const char* input_file, const char* output_file) {
  AVFormatContext* fmt_ctx = nullptr;
  if (avformat_open_input(&fmt_ctx, input_file, nullptr, nullptr) < 0) {
    LOG("Cannot open file %s\n", input_file);
    return false;
  }
  if (avformat_find_stream_info(fmt_ctx, nullptr) < 0) {
    LOG("Cannot read stream info\n");
    return false;
  }

  metadata metadata;
  if (!get_metadata(fmt_ctx, metadata)) {
    LOG("Failed to get metadata or unsupported type of file\n");
    LOG("Supported files: MP4 / H264 or AAC / CENC Encrypted\n");
    return false;
  }

  bool isVideo = metadata.type == AVMEDIA_TYPE_VIDEO;

  if (isVideo) {
#ifdef REENCODE
    // Deinitialize Widevine Decoder
    gWidevine->ResetDecoder(cdm::StreamType::kStreamTypeVideo);
    gWidevine->DeinitializeDecoder(cdm::StreamType::kStreamTypeVideo);

    // Initialize Widevine Decoder
    cdm::VideoDecoderConfig_2 config = {
        .codec = cdm::VideoCodec::kCodecH264,
        .profile = getVideoProfile(metadata.profile),
        .format = cdm::VideoFormat::kUnknownVideoFormat,
        .coded_size = {metadata.width, metadata.height},
        .extra_data = (uint8_t*)metadata.extradata,
        .extra_data_size = metadata.extradataSize,
        .encryption_scheme = cdm::EncryptionScheme::kCenc};
    LOG("Initializing Widevine decoder for %s\n", output_file);
    gWidevine->InitializeVideoDecoder(config);
    LOG("Initializing FFmpeg encoder for %s\n", output_file);
    if (!init_encoder(output_file, metadata.width, metadata.height,
                      metadata.bitrate, metadata.fps)) {
      LOG("Failed to init encoder\n");
      avformat_close_input(&fmt_ctx);
      return false;
    }
#else
    LOG("Initializing muxer for %s\n", output_file);
    if (!init_h264_muxer(output_file, metadata.width, metadata.height,
                         metadata.fps, metadata.extradata,
                         metadata.extradataSize)) {
      LOG("Failed to init muxer\n");
      avformat_close_input(&fmt_ctx);
      return false;
    }
#endif
  } else {
    LOG("Initializing muxer for %s\n", output_file);
    if (!init_aac_muxer(output_file, metadata.sample_rate, metadata.frame_size,
                        metadata.nb_channels, metadata.extradata,
                        metadata.extradataSize)) {
      LOG("Failed to init muxer\n");
      avformat_close_input(&fmt_ctx);
      return false;
    }
  }

  LOG("Processing %s (this may take a few minutes)\n", output_file);
  const bool decrypted_samples = ParseSamples(fmt_ctx);
  LOG("Finished %s processing\n", output_file);

#ifdef REENCODE
  if (isVideo) {
    finish_encoding();
  } else {
    finish_mux();
  }
#else
  finish_mux();
#endif

  avformat_close_input(&fmt_ctx);

  if (!decrypted_samples) {
    std::filesystem::remove(output_file);
  }
  return decrypted_samples;
}

bool process_files() {
  static std::string dirPath;
  static bool isInitialized = false;

  if (!isInitialized) {
    const char* env_dir = std::getenv("CONTENT_DIR");
    if (env_dir != nullptr) {
      dirPath = env_dir;
      isInitialized = true;
      LOG("Searching files in: %s\n", env_dir);
    } else {
      LOG("CONTENT_DIR not initialized\n");
      return false;
    }
  }

  if (!std::filesystem::exists(dirPath) ||
      !std::filesystem::is_directory(dirPath)) {
    return false;
  }

  for (const auto& entry : std::filesystem::directory_iterator(dirPath)) {
    const auto& path = entry.path();
    const std::string filename = path.filename().string();

    if (filename.rfind("notification", 0) != 0) {
      continue;
    }

    // A CDM may invoke several HostWrapper callbacks concurrently. Claim the
    // notification atomically so only one callback processes its media.
    const auto claimedPath = path.parent_path() / ("processing-" + filename);
    std::error_code claim_error;
    std::filesystem::rename(path, claimedPath, claim_error);
    if (claim_error) {
      continue;
    }
    LOG("Found %s\n", filename.c_str());

    std::ifstream notifFile(claimedPath);
    if (!notifFile.is_open()) {
      LOG("Failed to open %s\n", filename.c_str());
      std::filesystem::remove(claimedPath);
      continue;
    }

    std::string encryptedFile;
    if (std::getline(notifFile, encryptedFile)) {
      LOG("Decrypting file: %s\n", encryptedFile.c_str());
      std::string decryptedFile;
      if (!std::getline(notifFile, decryptedFile) || decryptedFile.empty()) {
        decryptedFile =
            encryptedFile.substr(0, encryptedFile.find(".mp4")) +
            "_decrypted.mp4";
      }
      if (std::filesystem::exists(decryptedFile)) {
        const std::filesystem::path encryptedPath(encryptedFile);
        const std::string uniqueStem =
            encryptedPath.stem().string() + "_" +
            std::to_string(std::chrono::steady_clock::now()
                               .time_since_epoch()
                               .count());
        const std::filesystem::path uniqueEncrypted =
            encryptedPath.parent_path() / (uniqueStem + ".mp4");
        std::filesystem::rename(encryptedPath, uniqueEncrypted);
        encryptedFile = uniqueEncrypted.string();
        decryptedFile =
            (encryptedPath.parent_path() / (uniqueStem + "_decrypted.mp4"))
                .string();
        LOG("Previous output exists; using %s for this run\n",
            decryptedFile.c_str());
      }
      if (process_file(encryptedFile.c_str(), decryptedFile.c_str())) {
        LOG("Decrypted file: %s\n", decryptedFile.c_str());
      } else {
        LOG("Failed to decrypt: %s\n", encryptedFile.c_str());
      }
    }

    notifFile.close();
    std::filesystem::remove(encryptedFile);
    std::filesystem::remove(claimedPath);
  }

  return true;
}
