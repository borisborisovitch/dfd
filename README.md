# dfd: 'Defective by Design' Widevine toolkit

This repository applies the [Defective by Design research and code](https://github.com/froud0t/DefectiveByDesign) to Udio's public song player. [Original paper.](https://www.usenix.org/system/files/woot26-roudot.pdf)

This implementation uses Docker to help fellow cybersecurity researchers reproduce their interception technique on Udio songs.

## Setup

1. Install Docker:

   - macOS: Install [Docker Desktop](https://docs.docker.com/desktop/).
   - Linux: Install [Docker Engine with Compose](https://docs.docker.com/compose/install/linux/).
   - Windows: Install [Docker Desktop](https://docs.docker.com/desktop/) and enable [WSL2 integration](https://docs.docker.com/desktop/features/wsl/), then run the commands from a WSL2 shell.

2. Clone this repository:

   ```bash
   git clone https://github.com/borisborisovitch/dfd
   ```

3. Run:

   ```bash
   ./dfd.sh --url=https://www.udio.com/songs/xxx
   ```

- Replace the URL with a public `/songs/`, `/playlists/`, or `/creators/` link.
- Use `--parallelism=4` to use multiple Firefox workers. Default is 4. Avoid high values.
- Use `--output-path=/path/to/folder` to change the default `output/` folder.
- The default format is `mp3`. Use `--format=m4a` to keep the original AAC stream data. You can also use `--format=wav` or `--format=flac`; these convert the streamed AAC. Other values are passed to ffmpeg as output formats.

Completed files are named `Artist - Song.<format>`. MP3 is encoded at 320 kbps. Available page metadata (artist, song name, lyrics) and cover art are embedded in MP3, M4A, WAV, and FLAC files.

## Structure

The container builds the original processor and extension, installs Firefox and Python dependencies through a locked [uv script](https://docs.astral.sh/uv/guides/scripts/), and uses `linux/amd64` on macOS, Linux, and Windows. It runs natively on x86-64 hosts; ARM hosts need Docker's amd64 emulation.

`output/index.md` lists every explored source and song link with its artist, title, and export status. `output/index.yml` lets later runs skip files still present in the selected format. Deleted files are exported again.

Single songs go in `output/singles/`, while playlists and creator pages each get a folder named after the playlist or creator. Files appear in the mounted output folder as each export completes. The final CLI summary reports exported, already present, and failed song counts.

## Disclaimer

This repository is intended for research and personal use only. It is provided as is, without warranties or guarantees.

Excessive or abusive use may cause Udio to restrict or ban your streaming access. Keep `--parallelism` low and be respectful of the platform!

## Attribution and license

The Widevine processor and extension originate from [froud0t/DefectiveByDesign](https://github.com/froud0t/DefectiveByDesign). The [GPL-3.0 license](LICENSE.md) applies.
