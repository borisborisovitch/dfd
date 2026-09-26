"""Drive Widevine audio playback and export with the researchers' CDM hook."""

from __future__ import annotations

import base64
import html
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

from mutagen.id3 import APIC, COMM, ID3, TCON, TDRC, TIT2, TPE1, TXXX, USLT, WOAS
from mutagen.mp4 import MP4, MP4Cover
from mutagen.mp3 import MP3

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as conditions
from selenium.webdriver.support.ui import WebDriverWait


class UdioMetadata(TypedDict):
    title: str
    artist: str
    image_url: str
    lyrics: str
    prompt: str
    description: str
    tags: list[str]
    published_at: str
    track_id: str


def api_json(
    driver: webdriver.Firefox, path: str, payload: dict[str, object] | None = None
) -> dict[str, Any]:
    response = driver.execute_async_script(
        """const [path, payload, done] = arguments;
        const options = {credentials: 'include', headers: {'Accept': 'application/json'}};
        if (payload !== null) {
            options.method = 'POST';
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(payload);
        }
        fetch(path, options).then(async response => {
            const body = await response.text();
            let data;
            try { data = JSON.parse(body); }
            catch (_) { done({status: response.status, error: 'non-JSON response'}); return; }
            done({status: response.status, data});
        }).catch(error => done({error: error.message}));""",
        path,
        payload,
    )
    if response.get("status") != 200 or not isinstance(response.get("data"), dict):
        raise RuntimeError(
            f"Udio API {path.partition('?')[0]} failed: HTTP "
            f"{response.get('status', 'unknown')} ({response.get('error', 'no data')})"
        )
    return response["data"]


def read_udio_metadata(
    driver: webdriver.Firefox, *, api_song: dict[str, Any] | None = None
) -> UdioMetadata:
    social = driver.execute_script(
        """return {
            title: document.querySelector('meta[property="og:title"]')?.content || '',
            image: document.querySelector('meta[property="og:image"]')?.content || ''
        };"""
    )
    candidates: list[dict[str, object]] = []
    source = html.unescape(driver.page_source)
    for script in re.findall(r"<script[^>]*>(.*?)</script>", source, re.DOTALL | re.IGNORECASE):
        normalized = script.replace(r'\"', '"')
        for match in re.finditer(r'"(?:track|song)"\s*:\s*', normalized):
            try:
                value, _ = json.JSONDecoder().raw_decode(normalized, match.end())
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("title") and value.get("artist"):
                candidates.append(value)
    social_title = social["title"].removesuffix(" | Udio")
    matching = [
        candidate for candidate in candidates
        if social_title == f"{candidate['artist']} - {candidate['title']}"
    ]
    track = max(
        matching or candidates,
        key=lambda candidate: sum(bool(candidate.get(key)) for key in
                                  ("lyrics", "image_path", "prompt", "tags")),
        default={},
    )
    track_id = str(track.get("id") or (api_song or {}).get("id") or "")
    if not track_id:
        raise RuntimeError("The song page did not expose its API identifier")
    if (
        api_song is None
        or api_song.get("id") != track_id
        or "lyrics" not in api_song
        or re.fullmatch(r"\$[A-Za-z]?\d+", str(api_song.get("lyrics") or ""))
    ):
        details = api_json(
            driver, f"/api/songs?songIds={quote(track_id, safe='')}&readOnly=true"
        )
        songs = details.get("songs")
        api_song = next(
            (
                song for song in songs
                if isinstance(song, dict) and song.get("id") == track_id
            ),
            None,
        ) if isinstance(songs, list) else None
        if api_song is None:
            raise RuntimeError("The song details API returned no matching song")
    track = {**track, **api_song}
    fallback_artist, separator, fallback_title = social_title.partition(" - ")
    lyrics = str(track.get("lyrics") or "").replace(r"\n", "\n")
    if re.fullmatch(r"\$[A-Za-z]?\d+", lyrics.strip()):
        lyrics = ""
    metadata: UdioMetadata = {
        "title": str(track.get("title") or (fallback_title if separator else social_title)),
        "artist": str(track.get("artist") or (fallback_artist if separator else "")),
        "image_url": str(track.get("image_path") or social["image"]),
        "lyrics": lyrics,
        "prompt": str(track.get("prompt") or "").replace(r"\n", "\n"),
        "description": str(track.get("description") or "").replace(r"\n", "\n"),
        "tags": [str(tag).replace(r"\n", " ").strip() for tag in
                 (track.get("tags") or []) if isinstance(tag, str)],
        "published_at": str(track.get("published_at") or track.get("created_at") or ""),
        "track_id": str(track.get("id") or ""),
    }
    if not metadata["title"] or not metadata["artist"]:
        raise RuntimeError("The song page did not expose a title and creator")
    print(
        f"[automation] Song metadata: {metadata['artist']} — {metadata['title']}; "
        f"lyrics={bool(metadata['lyrics'])}, cover={bool(metadata['image_url'])}, "
        f"tags={len(metadata['tags'])}",
        flush=True,
    )
    return metadata


def fetch_udio_cover(metadata: UdioMetadata) -> tuple[bytes, str] | None:
    if not metadata["image_url"]:
        return None
    parsed = urlparse(metadata["image_url"])
    if parsed.scheme != "https" or parsed.hostname not in {
        "imagedelivery.net", "www.udio.com", "udio.com"
    }:
        raise RuntimeError("The song page supplied an unsupported cover image host")
    request = Request(
        metadata["image_url"],
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
            "Referer": "https://www.udio.com/",
        },
    )
    with urlopen(request, timeout=20) as response:
        image_data = response.read(5_000_001)
    if len(image_data) > 5_000_000:
        raise RuntimeError("The cover image exceeds the 5 MB limit")
    if image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime_type = "image/png"
    elif image_data.startswith(b"\xff\xd8\xff"):
        mime_type = "image/jpeg"
    else:
        raise RuntimeError("The song page supplied an unsupported cover image format")
    print(f"[automation] Fetched {len(image_data)} cover-art bytes", flush=True)
    return image_data, mime_type


def embed_udio_metadata(path: Path, metadata: UdioMetadata,
                        cover: tuple[bytes, str] | None, source_url: str) -> None:
    audio = MP3(path)
    tags = audio.tags if audio.tags is not None else ID3()
    tags.add(TIT2(encoding=3, text=metadata["title"]))
    tags.add(TPE1(encoding=3, text=metadata["artist"]))
    tags.add(WOAS(url=source_url))
    if metadata["lyrics"]:
        tags.add(USLT(encoding=3, lang="eng", desc="Lyrics", text=metadata["lyrics"]))
    if metadata["description"]:
        tags.add(COMM(encoding=3, lang="eng", desc="Description",
                      text=metadata["description"]))
    if metadata["prompt"]:
        tags.add(TXXX(encoding=3, desc="Udio prompt", text=metadata["prompt"]))
    if metadata["tags"]:
        tags.add(TCON(encoding=3, text=", ".join(metadata["tags"])))
    if metadata["published_at"]:
        tags.add(TDRC(encoding=3, text=metadata["published_at"][:10]))
    if metadata["track_id"]:
        tags.add(TXXX(encoding=3, desc="Udio track ID", text=metadata["track_id"]))
    if cover:
        tags.add(APIC(encoding=3, mime=cover[1], type=3,
                      desc="Front cover", data=cover[0]))
    tags.save(path, v2_version=3)


def embed_udio_m4a_metadata(path: Path, metadata: UdioMetadata,
                            cover: tuple[bytes, str] | None, source_url: str) -> None:
    audio = MP4(path)
    if audio.tags is None:
        audio.add_tags()
    audio["\xa9nam"] = [metadata["title"]]
    audio["\xa9ART"] = [metadata["artist"]]
    if metadata["lyrics"]:
        audio["\xa9lyr"] = [metadata["lyrics"]]
    if metadata["description"]:
        audio["\xa9cmt"] = [metadata["description"]]
    if metadata["prompt"]:
        audio["----:com.apple.iTunes:UDIO_PROMPT"] = [metadata["prompt"].encode()]
    if metadata["tags"]:
        audio["\xa9gen"] = [", ".join(metadata["tags"])]
    if metadata["published_at"]:
        audio["\xa9day"] = [metadata["published_at"][:10]]
    audio["----:com.apple.iTunes:SOURCE_URL"] = [source_url.encode()]
    if metadata["track_id"]:
        audio["----:com.apple.iTunes:UDIO_TRACK_ID"] = [metadata["track_id"].encode()]
    if cover:
        image_format = (MP4Cover.FORMAT_PNG if cover[1] == "image/png"
                        else MP4Cover.FORMAT_JPEG)
        audio["covr"] = [MP4Cover(cover[0], imageformat=image_format)]
    audio.save()


def accept_udio_consent(driver: webdriver.Firefox, *, timeout: float) -> bool:
    try:
        consent = WebDriverWait(driver, timeout).until(
            conditions.element_to_be_clickable((By.ID, "cookiescript_accept"))
        )
    except TimeoutException:
        return False
    consent.click()
    WebDriverWait(driver, 10).until(
        conditions.invisibility_of_element_located((By.ID, "cookiescript_accept"))
    )
    WebDriverWait(driver, 10).until(
        conditions.invisibility_of_element_located((By.ID, "cookiescript_injected_wrapper"))
    )
    print("[automation] Accepted Udio cookie consent", flush=True)
    return True


def fetch_in_player(driver: webdriver.Firefox, url: str, *, binary: bool) -> str | bytes:
    result = driver.execute_async_script(
        """const [url, binary, done] = arguments;
        fetch(url, {credentials: 'include'}).then(async response => {
            if (!response.ok) { done({status: response.status}); return; }
            if (!binary) { done({status: response.status, body: await response.text()}); return; }
            const reader = new FileReader();
            reader.onload = () => done({status: response.status, body: reader.result});
            reader.onerror = () => done({error: 'FileReader failed'});
            reader.readAsDataURL(await response.blob());
        }).catch(error => done({error: error.name}));""",
        url,
        binary,
    )
    if "body" not in result:
        raise RuntimeError(
            f"Player media request failed: HTTP {result.get('status', 'unknown')} "
            f"({result.get('error', 'no response')})"
        )
    if binary:
        return base64.b64decode(result["body"].partition(",")[2], validate=True)
    return result["body"]


def fetch_fragments_in_player(driver: webdriver.Firefox, urls: list[str]) -> list[bytes]:
    result = driver.execute_async_script(
        """const [urls, done] = arguments;
        Promise.all(urls.map(async url => {
            const response = await fetch(url, {credentials: 'include'});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const blob = await response.blob();
            return await new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(reader.result.split(',')[1]);
                reader.onerror = () => reject(new Error('FileReader failed'));
                reader.readAsDataURL(blob);
            });
        })).then(bodies => done({bodies})).catch(error => done({error: error.message}));""",
        urls,
    )
    if "bodies" not in result:
        raise RuntimeError(f"Player fragment batch failed: {result.get('error', 'no response')}")
    return [base64.b64decode(body, validate=True) for body in result["bodies"]]


def main() -> None:
    target_url = os.environ.get("TARGET_URL", "")
    parsed = urlparse(target_url)
    is_udio = parsed.hostname == "www.udio.com" and parsed.path.startswith("/songs/")
    if parsed.scheme != "https" or not (
        is_udio or target_url == "https://integration.widevine.com/player/"
    ):
        raise ValueError("--url must be the public Widevine demo or an HTTPS Udio song page")
    if is_udio:
        os.environ["AUDIO_MAX_SECONDS"] = "0"
    profile = Path("/home/researcher/profile")
    output = Path(os.environ["CONTENT_DIR"])
    initial_files = {path.name for path in output.glob("*_decrypted.mp4")}
    initial_notifications = {path.name for path in output.glob("notification*.txt")}
    expected_audio_seconds: float | None = None
    song_metadata: UdioMetadata | None = None
    cover: tuple[bytes, str] | None = None
    encrypted: Path | None = None
    partial: Path | None = None
    decrypted_aac: Path | None = None
    notification: Path | None = None
    m4a_partial: Path | None = None
    mp3_partial: Path | None = None

    options = Options()
    options.binary_location = "/opt/processor/RUN.sh"
    options.add_argument("--profile")
    options.add_argument(str(profile))
    options.set_preference("browser.download.folderList", 2)
    options.set_preference("browser.download.dir", str(output.parent))
    options.set_preference("browser.download.useDownloadDir", True)
    options.set_preference("browser.download.alwaysOpenPanel", False)
    if not list(profile.glob("gmp-widevinecdm/*/libwidevinecdm.so")):
        options.set_preference("media.gmp-manager.updateEnabled", True)
        options.set_preference("media.gmp-manager.lastCheck", 0)
        options.set_preference("media.gmp-manager.lastEmptyCheck", 0)
    options.set_preference(
        "browser.helperApps.neverAsk.saveToDisk",
        "application/octet-stream,audio/mp4,video/mp4,text/plain",
    )

    print("[automation] Starting Firefox ESR through Processor/RUN.sh", flush=True)
    service = Service(
        executable_path="/usr/local/bin/geckodriver",
        service_args=["--marionette-port", "2828"],
        log_output=sys.stdout,
    )
    firefox_started = time.monotonic()
    driver = webdriver.Firefox(options=options, service=service)
    try:
        driver.set_page_load_timeout(60)
        driver.set_script_timeout(120)
        driver.get(target_url)

        print("[automation] Waiting for Firefox to install Widevine", flush=True)
        deadline = time.monotonic() + 180
        while not list(profile.glob("gmp-widevinecdm/*/libwidevinecdm.so")):
            if time.monotonic() >= deadline:
                raise RuntimeError("Firefox did not install its Widevine CDM within 180 seconds")
            time.sleep(2)

        if is_udio:
            song_metadata = read_udio_metadata(driver)
            cover = fetch_udio_cover(song_metadata)
            accept_udio_consent(driver, timeout=15)
            capability = driver.execute_async_script(
                """const done = arguments[arguments.length - 1];
                navigator.requestMediaKeySystemAccess('com.widevine.alpha', [{
                    initDataTypes: ['cenc'], audioCapabilities: [{
                        contentType: 'audio/mp4; codecs="mp4a.40.2"',
                        robustness: 'SW_SECURE_CRYPTO'
                    }]
                }]).then(() => done(true), error => done(error.message));"""
            )
            if capability is not True:
                raise RuntimeError(f"Firefox Widevine audio capability check failed: {capability}")
            play = WebDriverWait(driver, 60).until(
                conditions.element_to_be_clickable((By.CSS_SELECTOR, 'button[aria-label="Play"]'))
            )
            play.click()
            print("[automation] Clicked Udio Play", flush=True)
            playback_deadline = time.monotonic() + 45
            playback_state: dict[str, object] = {}
            while time.monotonic() < playback_deadline:
                playback_state = driver.execute_script(
                    """const audio = document.querySelector('audio');
                    const pause = [...document.querySelectorAll('button[aria-label="Pause"]')]
                        .some(button => button.getClientRects().length > 0 &&
                            getComputedStyle(button).visibility !== 'hidden');
                    const consent = document.querySelector('#cookiescript_accept');
                    return {
                        consentVisible: Boolean(consent && consent.getClientRects().length),
                        readyState: audio?.readyState ?? 0,
                        duration: audio?.duration ?? null,
                        paused: audio?.paused ?? true,
                        currentTime: audio?.currentTime ?? 0,
                        errorCode: audio?.error?.code ?? null,
                        pauseVisible: pause,
                    };"""
                )
                if playback_state["consentVisible"]:
                    accept_udio_consent(driver, timeout=5)
                    if driver.execute_script(
                        "return document.querySelector('audio')?.paused ?? true"
                    ):
                        WebDriverWait(driver, 10).until(
                            conditions.element_to_be_clickable(
                                (By.CSS_SELECTOR, 'button[aria-label="Play"]')
                            )
                        ).click()
                        print("[automation] Clicked Udio Play after consent", flush=True)
                if (
                    int(playback_state["readyState"]) >= 2
                    and isinstance(playback_state["duration"], (int, float))
                    and float(playback_state["duration"]) > 0
                    and not playback_state["paused"]
                    and float(playback_state["currentTime"]) > 0.1
                    and playback_state["pauseVisible"]
                ):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError(
                    "Udio playback did not advance after Play; "
                    f"state={playback_state}"
                )
            print("[automation] Udio audio playback is advancing", flush=True)
        else:
            extension_uuid: str | None = None
            deadline = time.monotonic() + 90
            while extension_uuid is None:
                if profile.joinpath("prefs.js").exists():
                    for line in profile.joinpath("prefs.js").read_text().splitlines():
                        if line.startswith('user_pref("extensions.webextensions.uuids", '):
                            value = line.partition(", ")[2].removesuffix(");")
                            extension_uuid = json.loads(json.loads(value)).get(
                                "WidevineDownloader@WidevineDownloader"
                            )
                            break
                if extension_uuid is not None:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Firefox did not install the researchers' extension")
                time.sleep(2)
            player_window = driver.current_window_handle
            driver.switch_to.new_window("tab")
            driver.get(f"moz-extension://{extension_uuid}/popup.html")
            driver.find_element(By.ID, "clear").click()
            WebDriverWait(driver, 10).until(
                lambda browser: "No tracks available" in browser.find_element(By.ID, "trackList").text
            )
            driver.switch_to.window(player_window)
            driver.refresh()
            play = WebDriverWait(driver, 60).until(
                conditions.element_to_be_clickable(
                    (By.XPATH, "//button[.//mat-icon[@aria-label='Play']]")
                )
            )
            play.click()
            print("[automation] Playing the H.264 Widevine demonstration", flush=True)
        if is_udio:
            resource_urls = driver.execute_script(
                "return performance.getEntriesByType('resource').map(entry => entry.name)"
            )
            manifest_url = next(
                (
                    url for url in resource_urls
                    if urlparse(url).hostname == "stream.udio.com"
                    and urlparse(url).path.endswith("/manifest.m3u8")
                ),
                None,
            )
            if manifest_url is None:
                raise RuntimeError("Udio playback exposed no HLS audio manifest")
            for _ in range(2):
                playlist = fetch_in_player(driver, manifest_url, binary=False)
                assert isinstance(playlist, str)
                if "#EXT-X-MAP:" in playlist:
                    break
                lines = [line.strip() for line in playlist.splitlines() if line.strip()]
                variant = next(
                    (lines[index + 1] for index, line in enumerate(lines[:-1])
                     if line.startswith("#EXT-X-STREAM-INF:")),
                    None,
                )
                if variant is None:
                    raise RuntimeError("Udio HLS manifest has no fMP4 audio track")
                manifest_url = urljoin(manifest_url, variant)
            init_match = re.search(r'#EXT-X-MAP:.*URI="([^"]+)"', playlist)
            if init_match is None:
                raise RuntimeError("Udio HLS manifest has no fMP4 initialization segment")
            segments: list[str] = []
            segment_seconds = 0.0
            lines = [line.strip() for line in playlist.splitlines() if line.strip()]
            for index, line in enumerate(lines[:-1]):
                if not line.startswith("#EXTINF:"):
                    continue
                segment_seconds += float(line.partition(":")[2].partition(",")[0])
                segment = lines[index + 1]
                if segment.startswith("#"):
                    raise RuntimeError("Udio HLS manifest has a missing audio segment")
                segments.append(urljoin(manifest_url, segment))
            if not segments:
                raise RuntimeError("Udio HLS manifest has no audio segments")
            expected_audio_seconds = segment_seconds
            print(
                f"[automation] Downloading encrypted Udio HLS audio: "
                f"init + {len(segments)} segments ({segment_seconds:.1f}s)",
                flush=True,
            )
            fragments_started = time.monotonic()
            encrypted = Path("/dev/shm") / (
                f"audio_udio_{parsed.path.rsplit('/', 1)[-1]}_{time.time_ns()}.mp4"
            )
            decrypted_aac = encrypted.with_suffix(".aac")
            partial = encrypted.with_suffix(".part")
            with partial.open("wb") as sink:
                init = fetch_in_player(driver, urljoin(manifest_url, init_match.group(1)), binary=True)
                assert isinstance(init, bytes)
                sink.write(init)
                for start in range(0, len(segments), 16):
                    batch = fetch_fragments_in_player(driver, segments[start:start + 16])
                    for fragment in batch:
                        sink.write(fragment)
                    print(
                        f"[automation] Downloaded encrypted segments "
                        f"{start + 1}-{start + len(batch)}/{len(segments)}",
                        flush=True,
                    )
            partial.replace(encrypted)
            print(
                f"[automation] Collected {encrypted.stat().st_size} encrypted bytes "
                f"in {time.monotonic() - fragments_started:.1f}s",
                flush=True,
            )
            notification = output / f"notification-udio-{time.time_ns()}.txt"
            notification.write_text(f"{encrypted}\n{decrypted_aac}\n")
        else:
            driver.switch_to.window(driver.window_handles[-1])
            deadline = time.monotonic() + 90
            audio_tracks: list = []
            while not audio_tracks:
                tracks = driver.find_elements(By.CSS_SELECTOR, "#trackList .track")
                audio_tracks = [track for track in tracks if "Audio Track" in track.text]
                if audio_tracks:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("The researchers' extension found no audio track for this page")
                driver.find_element(By.ID, "refresh").click()
                time.sleep(2)
            print(
                f"[automation] Downloading {audio_tracks[0].text.replace(chr(10), ' ')}",
                flush=True,
            )
            audio_tracks[0].find_element(By.CSS_SELECTOR, "button.download").click()
            driver.switch_to.window(player_window)

        print("[automation] Waiting for the hook to decrypt the audio track", flush=True)
        if is_udio:
            assert encrypted is not None and decrypted_aac is not None
            assert notification is not None and song_metadata is not None
            print(
                f"[automation] Firefox launch to completed audio download: "
                f"{time.monotonic() - firefox_started:.1f}s",
                flush=True,
            )
            deadline = time.monotonic() + 1200
            while True:
                if decrypted_aac.exists() and not encrypted.exists() and not notification.exists():
                    break
                if not notification.exists() and not encrypted.exists():
                    raise RuntimeError("The CDM hook did not produce decrypted AAC")
                if time.monotonic() >= deadline:
                    raise RuntimeError("The CDM hook did not finish within 20 minutes")
                time.sleep(0.5)
            print(
                f"[automation] Firefox launch to decrypted AAC: "
                f"{time.monotonic() - firefox_started:.1f}s",
                flush=True,
            )
            stem = encrypted.stem
            filename = re.sub(
                r'[<>:"/\\|?*\x00-\x1f]', " ",
                f"{song_metadata['artist']} - {song_metadata['title']}",
            )
            filename = re.sub(r"\s+", " ", filename).strip(" .")
            filename = filename.encode("utf-8")[:180].decode("utf-8", "ignore").rstrip(" .")
            if not filename:
                filename = stem
            base_filename = filename
            suffix = 2
            while (output / f"{filename}.m4a").exists() or (output / f"{filename}.mp3").exists():
                filename = f"{base_filename} ({suffix})"
                suffix += 1
            m4a = output / f"{filename}.m4a"
            mp3 = output / f"{filename}.mp3"
            m4a_partial = output / f"{stem}.part.m4a"
            mp3_partial = output / f"{stem}.part.mp3"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info", "-xerror",
                 "-i", str(decrypted_aac), "-map", "0:a:0", "-c:a", "copy",
                 "-movflags", "+faststart", "-y", str(m4a_partial)],
                check=True,
            )
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info", "-xerror",
                 "-i", str(decrypted_aac), "-map", "0:a:0", "-c:a", "libmp3lame",
                 "-b:a", "320k", "-id3v2_version", "3", "-y", str(mp3_partial)],
                check=True,
            )
            embed_udio_m4a_metadata(m4a_partial, song_metadata, cover, target_url)
            embed_udio_metadata(mp3_partial, song_metadata, cover, target_url)
            m4a_info = MP4(m4a_partial)
            mp3_info = MP3(mp3_partial)
            if m4a_info.info.length <= 0 or mp3_info.info.length <= 0:
                raise RuntimeError("The audio exports have no playable duration")
            if mp3_info.info.bitrate != 320_000:
                raise RuntimeError(
                    f"The MP3 bitrate is {mp3_info.info.bitrate}, expected 320000 bps"
                )
            if not m4a_info.get("\xa9nam") or not mp3_info.tags.getall("TIT2"):
                raise RuntimeError("The exported files are missing the song title")
            if cover and (not m4a_info.get("covr") or not mp3_info.tags.getall("APIC")):
                raise RuntimeError("The exported files are missing cover artwork")
            if song_metadata["lyrics"] and (
                not m4a_info.get("\xa9lyr") or not mp3_info.tags.getall("USLT")
            ):
                raise RuntimeError("The exported files are missing page lyrics")
            m4a_partial.replace(m4a)
            mp3_partial.replace(mp3)
            print(
                f"[automation] Exported M4A {m4a_info.info.length:.3f}s (AAC copy) "
                f"and MP3 {mp3_info.info.length:.3f}s at "
                f"{mp3_info.info.bitrate // 1000} kbps",
                flush=True,
            )
            print(
                f"[automation] Firefox launch to both tagged files: "
                f"{time.monotonic() - firefox_started:.1f}s",
                flush=True,
            )
            print(f"[automation] Ready: {m4a} ({m4a.stat().st_size} bytes)", flush=True)
            print(f"[automation] Ready: {mp3} ({mp3.stat().st_size} bytes)", flush=True)
            return

        deadline = time.monotonic() + 1200
        last_report = 0.0
        download_reported = False
        while True:
            if not download_reported and any(
                path.name not in initial_notifications
                for path in output.glob("notification*.txt")
            ):
                print(
                    f"[automation] Firefox launch to completed audio download: "
                    f"{time.monotonic() - firefox_started:.1f}s",
                    flush=True,
                )
                download_reported = True
            completed = [
                path
                for path in output.glob("*_decrypted.mp4")
                if path.name not in initial_files
                and path.stat().st_size > 0
                and not path.with_name(path.name.replace("_decrypted.mp4", ".mp4")).exists()
            ]
            audio = next((path for path in completed if path.name.startswith("audio_")), None)
            if audio is not None:
                print(
                    f"[automation] Firefox launch to decrypted audio: "
                    f"{time.monotonic() - firefox_started:.1f}s",
                    flush=True,
                )
                exported = audio.with_name(audio.name.replace("_decrypted.mp4", ".m4a"))
                print(f"[automation] Exporting AAC audio to {exported}", flush=True)
                subprocess.run(
                    [
                        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info", "-xerror",
                        "-i", str(audio), "-map", "0:a:0", "-c:a", "copy",
                        "-movflags", "+faststart", "-y", str(exported),
                    ],
                    check=True,
                )
                probe = subprocess.run(
                    [
                        "ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_name:format=duration", "-of", "json", str(exported),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                media_info = json.loads(probe.stdout)
                if not media_info["streams"] or media_info["streams"][0]["codec_name"] != "aac":
                    raise RuntimeError("The exported audio is not AAC")
                seconds = float(media_info["format"]["duration"])
                if seconds < 20:
                    raise RuntimeError(
                        f"Only {seconds:.3f} seconds of audio decoded; 20 seconds are required"
                    )
                if expected_audio_seconds is not None and seconds < expected_audio_seconds - 2:
                    raise RuntimeError(
                        f"Only {seconds:.3f} of {expected_audio_seconds:.3f} expected "
                        "seconds decoded from the Udio playlist"
                    )
                subprocess.run(
                    [
                        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                        "-xerror", "-i", str(exported), "-map", "0:a:0", "-f", "null", "-",
                    ],
                    check=True,
                )
                if is_udio:
                    audio.unlink()
                print(f"[automation] Verified {seconds:.3f} seconds of decoded AAC audio", flush=True)
                print(
                    f"[automation] Firefox launch to verified AAC file: "
                    f"{time.monotonic() - firefox_started:.1f}s",
                    flush=True,
                )
                print(f"[automation] Ready: {exported} ({exported.stat().st_size} bytes)", flush=True)
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "The processor did not produce decrypted audio within 20 minutes; "
                    "inspect the processor logs in the output folder"
                )
            if time.monotonic() - last_report > 30:
                print(
                    "[automation] Decrypted files so far: "
                    + (", ".join(path.name for path in completed) or "none"),
                    flush=True,
                )
                last_report = time.monotonic()
            time.sleep(2)
    finally:
        driver.quit()
        for transient in (partial, encrypted, decrypted_aac, notification,
                          notification.with_name("processing-" + notification.name)
                          if notification is not None else None,
                          m4a_partial, mp3_partial):
            if transient is not None:
                transient.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
