# /// script
# requires-python = ">=3.10"
# dependencies = ["selenium==4.49.0", "mutagen==1.47.0", "PyYAML==6.0.3"]
# ///
"""Enumerate public Udio links and run isolated Firefox/CDM audio workers."""

from __future__ import annotations

import base64
import fcntl
import html
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urljoin, urlparse

import yaml
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, COMM, TCON, TDRC, TIT2, TPE1, TXXX, USLT, WOAS
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.wave import WAVE
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as conditions
from selenium.webdriver.support.ui import WebDriverWait

from automate import (
    UdioMetadata,
    accept_udio_consent,
    api_json,
    embed_udio_m4a_metadata,
    embed_udio_metadata,
    fetch_fragments_in_player,
    fetch_in_player,
    fetch_udio_cover,
    read_udio_metadata,
)


class SongRef(TypedDict):
    id: str
    url: str
    artist: str
    title: str
    api_song: dict[str, Any] | None


def safe_filename(value: str, fallback: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    name = re.sub(r"\s+", " ", name).strip(" .")
    name = name.encode("utf-8")[:180].decode("utf-8", "ignore").rstrip(" .")
    if not name or name.upper().split(".")[0] in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        return fallback
    return name


def file_extension(format_name: str) -> str:
    extension = re.sub(r"[^A-Za-z0-9._+-]", "_", format_name).strip("._")[:32]
    if not extension:
        raise ValueError("--format must contain a filename-safe character")
    return extension


def embed_udio_flac_metadata(
    path: Path, metadata: UdioMetadata, cover: tuple[bytes, str] | None,
    source_url: str,
) -> None:
    audio = FLAC(path)
    audio["title"] = metadata["title"]
    audio["artist"] = metadata["artist"]
    audio["source"] = source_url
    if metadata["lyrics"]:
        audio["lyrics"] = metadata["lyrics"]
    if metadata["description"]:
        audio["description"] = metadata["description"]
    if metadata["prompt"]:
        audio["udio_prompt"] = metadata["prompt"]
    if metadata["tags"]:
        audio["genre"] = metadata["tags"]
    if metadata["published_at"]:
        audio["date"] = metadata["published_at"][:10]
    if metadata["track_id"]:
        audio["udio_track_id"] = metadata["track_id"]
    if cover:
        picture = Picture()
        picture.type = 3
        picture.mime = cover[1]
        picture.desc = "Front cover"
        picture.data = cover[0]
        audio.add_picture(picture)
    audio.save()


def embed_udio_wav_metadata(
    path: Path, metadata: UdioMetadata, cover: tuple[bytes, str] | None,
    source_url: str,
) -> None:
    audio = WAVE(path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags.add(TIT2(encoding=3, text=metadata["title"]))
    audio.tags.add(TPE1(encoding=3, text=metadata["artist"]))
    audio.tags.add(WOAS(url=source_url))
    if metadata["lyrics"]:
        audio.tags.add(USLT(encoding=3, lang="eng", desc="Lyrics",
                            text=metadata["lyrics"]))
    if metadata["description"]:
        audio.tags.add(COMM(encoding=3, lang="eng", desc="Description",
                            text=metadata["description"]))
    if metadata["prompt"]:
        audio.tags.add(TXXX(encoding=3, desc="Udio prompt", text=metadata["prompt"]))
    if metadata["tags"]:
        audio.tags.add(TCON(encoding=3, text=", ".join(metadata["tags"])))
    if metadata["published_at"]:
        audio.tags.add(TDRC(encoding=3, text=metadata["published_at"][:10]))
    if metadata["track_id"]:
        audio.tags.add(TXXX(encoding=3, desc="Udio track ID",
                            text=metadata["track_id"]))
    if cover:
        audio.tags.add(APIC(encoding=3, mime=cover[1], type=3,
                            desc="Front cover", data=cover[0]))
    audio.save()


def classify_url(url: str) -> tuple[str, str, str]:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"udio.com", "www.udio.com"}
        or len(parts) != 2
        or parts[0] not in {"songs", "playlists", "creators"}
        or not parts[1]
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "--url must be a public HTTPS Udio song, playlist, or creator link"
        )
    kind = {"songs": "song", "playlists": "playlist", "creators": "creator"}[parts[0]]
    normalized = f"https://www.udio.com/{parts[0]}/{parts[1]}"
    return kind, parts[1], normalized


def page_uuid(source: str, kind: str) -> str:
    normalized = html.unescape(source)
    for _ in range(3):
        normalized = normalized.replace(r"\"", '"')
    if kind == "creator":
        patterns = [
            r'"profile"\s*:\s*\{\s*"id"\s*:\s*"([0-9a-fA-F-]{36})"',
            r'"userId"\s*:\s*"([0-9a-fA-F-]{36})"',
        ]
    else:
        patterns = [r'"playlistId"\s*:\s*"([0-9a-fA-F-]{36})"']
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return match.group(1)
    raise RuntimeError(f"The public {kind} page did not expose its API identifier")


def ref_from_song(raw: dict[str, Any]) -> SongRef | None:
    song_id = raw.get("id")
    if not isinstance(song_id, str) or not song_id:
        return None
    return {
        "id": song_id,
        "url": f"https://www.udio.com/songs/{song_id}",
        "artist": str(raw.get("artist") or "Unknown artist"),
        "title": str(raw.get("title") or "Unknown song"),
        "api_song": raw,
    }


def discover_songs(url: str, kind: str, path_id: str) -> tuple[str, list[SongRef]]:
    if kind == "song":
        return "singles", [
            {
                "id": path_id,
                "url": url,
                "artist": "Unknown artist",
                "title": "Unknown song",
                "api_song": None,
            }
        ]

    options = Options()
    options.binary_location = "/usr/bin/firefox-esr"
    options.add_argument("--headless")
    print(f"[catalog] Opening {kind} page to read its API identifier", flush=True)
    driver = webdriver.Firefox(
        options=options,
        service=Service(
            executable_path="/usr/local/bin/geckodriver", log_output=sys.stdout
        ),
    )
    try:
        driver.set_page_load_timeout(60)
        driver.set_script_timeout(60)
        driver.get(url)
        accept_udio_consent(driver, timeout=5)
        identifier = page_uuid(driver.page_source, kind)
        source_name = driver.execute_script(
            """return document.querySelector('h1')?.textContent?.trim() ||
                document.querySelector('meta[property="og:title"]')?.content?.trim() ||
                document.title?.trim() || '';"""
        )
        source_name = re.sub(r"\s*[|–-]\s*Udio\s*$", "", source_name).strip()
        if not source_name or source_name.lower() == "udio":
            source_name = path_id
        print(f"[catalog] {kind} API identifier: {identifier}", flush=True)
        expected_ids: list[str] = []
        if kind == "playlist":
            try:
                details = api_json(driver, f"/api/playlists?id={identifier}")
                playlists = details.get("playlists")
                if (
                    isinstance(playlists, list)
                    and playlists
                    and isinstance(playlists[0], dict)
                ):
                    source_name = str(
                        playlists[0].get("title")
                        or playlists[0].get("name")
                        or source_name
                    )
                    song_list = playlists[0].get("song_list")
                    if isinstance(song_list, list):
                        for song in song_list:
                            song_id = (
                                song
                                if isinstance(song, str)
                                else (
                                    song.get("id") if isinstance(song, dict) else None
                                )
                            )
                            if (
                                isinstance(song_id, str)
                                and song_id
                                and song_id not in expected_ids
                            ):
                                expected_ids.append(song_id)
            except RuntimeError as error:
                print(
                    f"[catalog] Playlist details unavailable; using paginated search: "
                    f"{error}",
                    flush=True,
                )
            print(
                f"[catalog] Playlist details list {len(expected_ids)} song IDs",
                flush=True,
            )

        refs: dict[str, SongRef] = {}
        cursor = 0
        seen_pages: set[tuple[str, ...]] = set()
        page_number = 0
        while True:
            page_number += 1
            search = (
                {"sort": "playlist", "playlistId": identifier}
                if kind == "playlist"
                else {"sort": "recent", "userId": identifier}
            )
            data = api_json(
                driver,
                "/api/songs/search",
                {
                    "searchQuery": search,
                    "pageSize": 20,
                    "pageParam": cursor,
                    "readOnly": True,
                },
            )
            songs = data.get("data")
            if not isinstance(songs, list):
                raise RuntimeError("Udio song search returned no song list")
            page_ids = tuple(
                str(song.get("id")) for song in songs if isinstance(song, dict)
            )
            if page_ids and page_ids in seen_pages:
                raise RuntimeError(
                    "Udio song search repeated a page before reaching the end"
                )
            seen_pages.add(page_ids)
            for raw in songs:
                if isinstance(raw, dict):
                    ref = ref_from_song(raw)
                    if ref:
                        refs[ref["id"]] = ref
            print(
                f"[catalog] API page {page_number}: {len(songs)} rows, "
                f"{len(refs)} unique song IDs",
                flush=True,
            )
            if (
                not songs
                or len(songs) < 20
                or (expected_ids and set(expected_ids).issubset(refs))
            ):
                break
            next_cursor = data.get("cursor")
            if (
                isinstance(next_cursor, int)
                and not isinstance(next_cursor, bool)
                and next_cursor > cursor
            ):
                cursor = next_cursor
            elif (
                isinstance(next_cursor, str)
                and next_cursor.isdigit()
                and int(next_cursor) > cursor
            ):
                cursor = int(next_cursor)
            else:
                cursor += 20

        missing = [song_id for song_id in expected_ids if song_id not in refs]
        for start in range(0, len(missing), 20):
            batch = missing[start : start + 20]
            details = api_json(
                driver, f"/api/songs?songIds={','.join(batch)}&readOnly=true"
            )
            candidates = details.get("songs")
            if isinstance(candidates, list):
                for raw in candidates:
                    if isinstance(raw, dict):
                        ref = ref_from_song(raw)
                        if ref:
                            refs[ref["id"]] = ref
        for song_id in missing:
            refs.setdefault(
                song_id,
                {
                    "id": song_id,
                    "url": f"https://www.udio.com/songs/{song_id}",
                    "artist": "Unknown artist",
                    "title": "Unknown song",
                    "api_song": None,
                },
            )
        ordered = (
            [refs[song_id] for song_id in expected_ids]
            if expected_ids
            else list(refs.values())
        )
        print(
            f"[catalog] Discovered {len(ordered)} song IDs through Udio APIs",
            flush=True,
        )
        return source_name, ordered
    finally:
        driver.quit()


class CatalogIndex:
    def __init__(
        self, output: Path, source_url: str, kind: str, source_name: str
    ) -> None:
        self.output = output
        self.source_url = source_url
        self.lock = threading.RLock()
        self.lock_file = (output / "index.lock").open("a+")
        fcntl.flock(self.lock_file, fcntl.LOCK_EX)
        path = next(
            (
                candidate for candidate in (
                    output / "index.yml", output / "index.json",
                    output / "udio-index.json",
                ) if candidate.exists()
            ),
            None,
        )
        self.data: dict[str, Any] = (
            yaml.safe_load(path.read_text(encoding="utf-8"))
            if path is not None and path.suffix == ".yml"
            else json.loads(path.read_text(encoding="utf-8"))
            if path is not None
            else {"sources": {}, "songs": {}}
        )
        if not isinstance(self.data, dict) or not all(
            isinstance(self.data.get(section), dict) for section in ("sources", "songs")
        ):
            raise ValueError(f"Invalid song index: {path}")
        previous = self.data["sources"].get(source_url, {})
        if kind == "song":
            self.folder = "singles"
        elif isinstance(previous.get("folder"), str) and previous["folder"] == safe_filename(
            previous["folder"], ""
        ):
            self.folder = previous["folder"]
        else:
            base = safe_filename(source_name, "collection")
            self.folder = base
            reserved = {
                source.get("folder")
                for url, source in self.data["sources"].items()
                if url != source_url and isinstance(source, dict)
            }
            suffix = 2
            while (
                self.folder == "singles"
                or self.folder in reserved
                or (output / self.folder).exists()
            ):
                self.folder = f"{base} ({suffix})"
                suffix += 1
        self.media_dir = output / self.folder
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.aliases: dict[str, str] = {}

    def key(self, song_id: str) -> str:
        return f"{self.folder}/{song_id}"

    def close(self) -> None:
        fcntl.flock(self.lock_file, fcntl.LOCK_UN)
        self.lock_file.close()

    def save(self) -> None:
        yaml_path = self.output / "index.yml"
        md_path = self.output / "index.md"
        temporary_yaml = yaml_path.with_suffix(".yml.tmp")
        temporary_md = md_path.with_suffix(".md.tmp")
        temporary_yaml.write_text(
            yaml.safe_dump(self.data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        temporary_yaml.replace(yaml_path)
        lines = [
            "# Udio experiment index",
            "",
            "## Explored sources",
            "",
            "| Type | Name | Folder | Link | Song IDs |",
            "| --- | --- | --- | --- | ---: |",
        ]
        for url, source in self.data["sources"].items():
            name = str(source.get("name", "")).replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {source['kind']} | {name} | {source.get('folder', '.')} | "
                f"{url} | {len(source['song_ids'])} |"
            )
        lines.extend(
            [
                "",
                "## Songs",
                "",
                "| Status | Folder | Artist - Song | Link | Files |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for song in self.data["songs"].values():
            artist = (
                str(song.get("artist") or "Unknown artist")
                .replace("|", "\\|")
                .replace("\n", " ")
            )
            title = (
                str(song.get("title") or "Unknown song")
                .replace("|", "\\|")
                .replace("\n", " ")
            )
            files = song.get("files", {})
            requested = song.get("requested_formats", ["m4a", "mp3"])
            status = (
                "complete"
                if all(self._has(song, fmt) for fmt in requested)
                else "partial"
                if any(self._has(song, fmt) for fmt in files)
                else "failed"
                if song.get("error")
                else "pending"
            )
            available = ", ".join(
                f"{fmt}: {song.get('folder', '.')}/{name}"
                for fmt, name in files.items()
                if self._has(song, fmt)
            ).replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {status} | {song.get('folder', '.')} | "
                f"{artist} - {title} | {song['url']} | "
                f"{available} |"
            )
            if song.get("error"):
                lines.append(f"\nError for {song['url']}: {song['error']}\n")
        temporary_md.write_text("\n".join(lines) + "\n")
        temporary_md.replace(md_path)

    def _has(self, song: dict[str, Any], ext: str) -> bool:
        name = song.get("files", {}).get(ext)
        file_path = self.output / song.get("folder", "") / name if name else None
        try:
            return bool(
                file_path and file_path.is_file() and file_path.stat().st_size > 0
            )
        except OSError:
            return False

    def add_source(
        self, url: str, kind: str, source_name: str,
        refs: list[SongRef], formats: list[str]
    ) -> list[SongRef]:
        with self.lock:
            previous = self.data["sources"].get(url, {})
            if (
                kind == "song"
                and len(refs) == 1
                and len(previous.get("song_ids", [])) == 1
                and self.key(previous["song_ids"][0]) in self.data["songs"]
            ):
                refs = [{**refs[0], "id": previous["song_ids"][0]}]
            self.data["sources"][url] = {
                "kind": kind,
                "name": source_name,
                "folder": self.folder,
                "formats": formats,
                "song_ids": [ref["id"] for ref in refs],
            }
            pending: list[SongRef] = []
            for ref in refs:
                song = self.data["songs"].setdefault(
                    self.key(ref["id"]),
                    {
                        "id": ref["id"],
                        "url": ref["url"],
                        "folder": self.folder,
                        "files": {},
                    },
                )
                song["folder"] = self.folder
                if ref["artist"] != "Unknown artist":
                    song["artist"] = ref["artist"]
                if ref["title"] != "Unknown song":
                    song["title"] = ref["title"]
                song.setdefault("artist", ref["artist"])
                song.setdefault("title", ref["title"])
                song.setdefault("url", ref["url"])
                song["requested_formats"] = formats
                if all(self._has(song, fmt) for fmt in formats):
                    print(
                        f"[catalog] Skipping existing: {song['artist']} - {song['title']}",
                        flush=True,
                    )
                else:
                    pending.append(ref)
            self.save()
            return pending

    def update_metadata(
        self, old_id: str, actual_id: str, artist: str, title: str
    ) -> str:
        with self.lock:
            song = self.data["songs"].pop(self.key(old_id))
            if actual_id and actual_id != old_id:
                self.aliases[old_id] = actual_id
                previous = self.data["songs"].get(self.key(actual_id))
                if previous:
                    previous.setdefault("files", {}).update(song.get("files", {}))
                    song = previous
                else:
                    song["id"] = actual_id
                    song["url"] = f"https://www.udio.com/songs/{actual_id}"
                source = self.data["sources"][self.source_url]
                source["song_ids"] = [
                    actual_id if item == old_id else item
                    for item in source["song_ids"]
                ]
            song["artist"] = artist
            song["title"] = title
            song.pop("error", None)
            key = actual_id or old_id
            self.data["songs"][self.key(key)] = song
            self.save()
            return key

    def complete(self, song_id: str, formats: list[str]) -> bool:
        with self.lock:
            song = self.data["songs"][self.key(song_id)]
            return all(self._has(song, fmt) for fmt in formats)

    def filename(self, song_id: str, formats: list[str]) -> str:
        with self.lock:
            song = self.data["songs"][self.key(song_id)]
            if song.get("filename"):
                return song["filename"]
            name = safe_filename(f"{song['artist']} - {song['title']}", song_id)
            base = name
            suffix = 2
            reserved = {
                item.get("filename")
                for key, item in self.data["songs"].items()
                if key != self.key(song_id) and item.get("folder") == self.folder
            }
            while (
                name in reserved
                or any(
                    (self.media_dir / f"{name}.{file_extension(fmt)}").exists()
                    for fmt in formats
                )
            ):
                name = f"{base} ({suffix})"
                suffix += 1
            song["filename"] = name
            self.save()
            return name

    def ready(self, song_id: str, ext: str, filename: str) -> None:
        with self.lock:
            self.data["songs"][self.key(song_id)].setdefault("files", {})[ext] = filename
            self.save()

    def failed(self, song_id: str, message: str) -> None:
        with self.lock:
            key = self.aliases.get(song_id, song_id)
            self.data["songs"][self.key(key)]["error"] = message
            self.save()


def prepare_profile(slot: int) -> Path:
    source = Path("/home/researcher/profile")
    destination = Path(tempfile.mkdtemp(prefix=f"udio-profile-{slot}-"))
    if list(source.glob("gmp-widevinecdm/*/libwidevinecdm.so")):
        shutil.rmtree(destination)
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns(
                "lock",
                ".parentlock",
                "parent.lock",
                "cache2",
                "startupCache",
                "sessionstore*",
                "*.sqlite-shm",
                "*.sqlite-wal",
            ),
        )
    return destination


def start_worker(slot: int, profile: Path, hook_dir: Path) -> webdriver.Firefox:
    options = Options()
    options.binary_location = "/opt/processor/RUN.sh"
    options.add_argument("--profile")
    options.add_argument(str(profile))
    options.set_preference("browser.download.folderList", 2)
    options.set_preference("browser.download.dir", str(hook_dir))
    if not list(profile.glob("gmp-widevinecdm/*/libwidevinecdm.so")):
        options.set_preference("media.gmp-manager.updateEnabled", True)
        options.set_preference("media.gmp-manager.lastCheck", 0)
        options.set_preference("media.gmp-manager.lastEmptyCheck", 0)
    service_env = dict(os.environ)
    service_env.update(
        {
            "CONTENT_DIR": str(hook_dir),
            "RUN_AS_WEBDRIVER": "1",
            "HOOK_LIBRARY": "/opt/processor/libhook.so",
            "AUDIO_MAX_SECONDS": "0",
        }
    )
    print(
        f"[worker {slot}] Starting Firefox ESR with its own CDM hook folder", flush=True
    )
    driver = webdriver.Firefox(
        options=options,
        service=Service(
            executable_path="/usr/local/bin/geckodriver",
            log_output=sys.stdout,
            env=service_env,
        ),
    )
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(120)
    return driver


def download_song(
    driver: webdriver.Firefox,
    slot: int,
    ref: SongRef,
    profile: Path,
    hook_dir: Path,
    index: CatalogIndex,
    formats: list[str],
) -> None:
    started = time.monotonic()
    song_id = ref["id"]
    encrypted: Path | None = None
    decrypted_aac: Path | None = None
    partial: Path | None = None
    notification: Path | None = None
    export_partials: list[Path] = []
    try:
        driver.get(ref["url"])
        deadline = time.monotonic() + 180
        while not list(profile.glob("gmp-widevinecdm/*/libwidevinecdm.so")):
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Firefox did not install Widevine within 180 seconds"
                )
            time.sleep(2)

        metadata = read_udio_metadata(driver, api_song=ref["api_song"])
        song_id = index.update_metadata(
            song_id, metadata["track_id"], metadata["artist"], metadata["title"]
        )
        if index.complete(song_id, formats):
            print(
                f"[worker {slot}] Already complete: {metadata['artist']} - "
                f"{metadata['title']}",
                flush=True,
            )
            return
        cover = fetch_udio_cover(metadata)
        accept_udio_consent(driver, timeout=5)
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
            raise RuntimeError(
                f"Firefox Widevine audio capability check failed: {capability}"
            )
        WebDriverWait(driver, 60).until(
            conditions.element_to_be_clickable(
                (By.CSS_SELECTOR, 'button[aria-label="Play"]')
            )
        ).click()
        print(
            f"[worker {slot}] Clicked Play: {metadata['artist']} - {metadata['title']}",
            flush=True,
        )
        playback_deadline = time.monotonic() + 45
        playback_state: dict[str, Any] = {}
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
            raise RuntimeError(f"Udio playback did not advance; state={playback_state}")
        resource_urls = driver.execute_script(
            "return performance.getEntriesByType('resource').map(entry => entry.name)"
        )
        manifest_url = next(
            (
                url
                for url in resource_urls
                if urlparse(url).hostname == "stream.udio.com"
                and urlparse(url).path.endswith("/manifest.m3u8")
            ),
            None,
        )
        if manifest_url is None:
            raise RuntimeError("Udio playback exposed no HLS audio manifest")
        for _ in range(2):
            playlist = fetch_in_player(driver, manifest_url, binary=False)
            if not isinstance(playlist, str):
                raise RuntimeError("Udio HLS manifest was not text")
            if "#EXT-X-MAP:" in playlist:
                break
            lines = [line.strip() for line in playlist.splitlines() if line.strip()]
            variant = next(
                (
                    lines[i + 1]
                    for i, line in enumerate(lines[:-1])
                    if line.startswith("#EXT-X-STREAM-INF:")
                ),
                None,
            )
            if variant is None:
                raise RuntimeError("Udio HLS manifest has no fMP4 audio track")
            manifest_url = urljoin(manifest_url, variant)
        init_match = re.search(r'#EXT-X-MAP:.*URI="([^"]+)"', playlist)
        if init_match is None:
            raise RuntimeError("Udio HLS manifest has no initialization segment")
        lines = [line.strip() for line in playlist.splitlines() if line.strip()]
        segments: list[str] = []
        for i, line in enumerate(lines[:-1]):
            if line.startswith("#EXTINF:"):
                if lines[i + 1].startswith("#"):
                    raise RuntimeError("Udio HLS manifest has a missing audio segment")
                segments.append(urljoin(manifest_url, lines[i + 1]))
        if not segments:
            raise RuntimeError("Udio HLS manifest has no audio segments")
        print(
            f"[worker {slot}] Fetching init and {len(segments)} encrypted fragments",
            flush=True,
        )
        encrypted = hook_dir / f"audio_udio_{song_id}_{time.time_ns()}.mp4"
        decrypted_aac = encrypted.with_suffix(".aac")
        partial = encrypted.with_suffix(".part")
        with partial.open("wb") as sink:
            init = fetch_in_player(
                driver, urljoin(manifest_url, init_match.group(1)), binary=True
            )
            if not isinstance(init, bytes):
                raise RuntimeError("The HLS initialization segment was not binary")
            sink.write(init)
            for start in range(0, len(segments), 16):
                batch = fetch_fragments_in_player(driver, segments[start : start + 16])
                for fragment in batch:
                    sink.write(fragment)
                print(
                    f"[worker {slot}] Fragments {start + 1}-"
                    f"{start + len(batch)}/{len(segments)}",
                    flush=True,
                )
        partial.replace(encrypted)
        notification = hook_dir / f"notification-udio-{time.time_ns()}.txt"
        notification.write_text(f"{encrypted}\n{decrypted_aac}\n")
        print(
            f"[worker {slot}] Firefox launch to encrypted download: "
            f"{time.monotonic() - started:.1f}s",
            flush=True,
        )
        deadline = time.monotonic() + 1200
        while True:
            if (
                decrypted_aac.exists()
                and not encrypted.exists()
                and not notification.exists()
            ):
                break
            if not notification.exists() and not encrypted.exists():
                raise RuntimeError("The CDM hook did not produce decrypted AAC")
            if time.monotonic() >= deadline:
                raise RuntimeError("The CDM hook did not finish within 20 minutes")
            time.sleep(0.5)
        print(
            f"[worker {slot}] Firefox launch to decrypted AAC: "
            f"{time.monotonic() - started:.1f}s",
            flush=True,
        )

        filename = index.filename(song_id, formats)
        stem = encrypted.stem
        for format_name in formats:
            extension = file_extension(format_name)
            destination = index.media_dir / f"{filename}.{extension}"
            if destination.is_file() and destination.stat().st_size > 0:
                index.ready(song_id, format_name, destination.name)
                continue
            temporary = index.media_dir / f"{stem}.part.{extension}"
            export_partials.append(temporary)
            command = [
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info",
                "-xerror", "-i", str(decrypted_aac), "-map", "0:a:0",
            ]
            if format_name == "m4a":
                command.extend(["-c:a", "copy", "-movflags", "+faststart", "-f", "ipod"])
            elif format_name == "mp3":
                command.extend(["-c:a", "libmp3lame", "-b:a", "320k",
                                "-id3v2_version", "3", "-f", "mp3"])
            elif format_name == "wav":
                command.extend(["-c:a", "pcm_s24le", "-f", "wav"])
            elif format_name == "flac":
                command.extend(["-c:a", "flac", "-f", "flac"])
            else:
                command.extend(["-metadata", f"title={metadata['title']}",
                                "-metadata", f"artist={metadata['artist']}",
                                "-f", format_name])
            command.extend(["-y", str(temporary)])
            subprocess.run(command, check=True)
            if format_name == "m4a":
                embed_udio_m4a_metadata(temporary, metadata, cover, ref["url"])
                info = MP4(temporary)
                if info.info.length <= 0 or not info.get("\xa9nam"):
                    raise RuntimeError("The M4A export has no duration or title")
            elif format_name == "mp3":
                embed_udio_metadata(temporary, metadata, cover, ref["url"])
                info = MP3(temporary)
                if (info.info.length <= 0 or info.info.bitrate != 320_000
                        or not info.tags.getall("TIT2")):
                    raise RuntimeError("The MP3 export has invalid duration, bitrate, or title")
            elif format_name == "flac":
                embed_udio_flac_metadata(temporary, metadata, cover, ref["url"])
                if FLAC(temporary).info.length <= 0:
                    raise RuntimeError("The FLAC export has no duration")
            elif format_name == "wav":
                embed_udio_wav_metadata(temporary, metadata, cover, ref["url"])
                if WAVE(temporary).info.length <= 0:
                    raise RuntimeError("The WAV export has no duration")
            elif temporary.stat().st_size == 0:
                raise RuntimeError(f"The {format_name} export is empty")
            temporary.replace(destination)
            index.ready(song_id, format_name, destination.name)
            print(f"[worker {slot}] Ready: {destination} "
                  f"({destination.stat().st_size} bytes)", flush=True)
        print(
            f"[worker {slot}] Firefox launch to exported files: "
            f"{time.monotonic() - started:.1f}s",
            flush=True,
        )
    finally:
        for transient in (
            partial,
            encrypted,
            decrypted_aac,
            notification,
            notification.with_name("processing-" + notification.name)
            if notification is not None
            else None,
            *export_partials,
        ):
            if transient is not None:
                transient.unlink(missing_ok=True)


def worker_loop(
    slot: int,
    jobs: queue.Queue[SongRef | None],
    index: CatalogIndex,
    formats: list[str],
    failures: list[str],
) -> None:
    profile = prepare_profile(slot)
    hook_dir = Path(tempfile.mkdtemp(prefix=f"udio-hook-{slot}-", dir="/dev/shm"))
    driver: webdriver.Firefox | None = None
    try:
        while True:
            ref = jobs.get()
            if ref is None:
                jobs.task_done()
                break
            try:
                if driver is None:
                    driver = start_worker(slot, profile, hook_dir)
                download_song(driver, slot, ref, profile, hook_dir, index, formats)
            except Exception as error:
                message = f"{type(error).__name__}: {error}"
                print(
                    f"[worker {slot}] Failed {ref['url']}: {message}",
                    file=sys.stderr,
                    flush=True,
                )
                try:
                    index.failed(ref["id"], message)
                except Exception as index_error:
                    print(
                        f"[worker {slot}] Could not record the failed song: {index_error}",
                        file=sys.stderr,
                        flush=True,
                    )
                failures.append(ref["url"])
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception as quit_error:
                        print(
                            f"[worker {slot}] Firefox cleanup failed: {quit_error}",
                            file=sys.stderr,
                            flush=True,
                        )
                    finally:
                        driver = None
            finally:
                jobs.task_done()
    finally:
        if driver is not None:
            driver.quit()
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(hook_dir, ignore_errors=True)


def main() -> None:
    target_url = os.environ.get("TARGET_URL", "")
    kind, path_id, target_url = classify_url(target_url)
    parallelism = int(os.environ.get("PARALLELISM", "4"))
    if parallelism < 1:
        raise ValueError("--parallelism must be a positive integer")
    output_format = os.environ.get("OUTPUT_FORMAT", "mp3")
    if output_format == "all":
        raise ValueError("--format=all is no longer supported; choose one output format")
    formats = [output_format]
    for format_name in formats:
        file_extension(format_name)
    output = Path(os.environ["CONTENT_DIR"])
    output.mkdir(parents=True, exist_ok=True)
    source_name, refs = discover_songs(target_url, kind, path_id)
    index = CatalogIndex(output, target_url, kind, source_name)
    try:
        pending = index.add_source(target_url, kind, source_name, refs, formats)
        skipped = len(refs) - len(pending)
        print(
            f"[catalog] {len(pending)} songs need audio export; "
            f"{len(refs) - len(pending)} already complete",
            flush=True,
        )
        if not pending:
            print(
                f"[catalog] Run summary: exported=0 already_present={skipped} "
                f"failed=0 total={len(refs)}",
                flush=True,
            )
            return
        jobs: queue.Queue[SongRef | None] = queue.Queue()
        failures: list[str] = []
        count = min(parallelism, len(pending))
        threads = [
            threading.Thread(
                target=worker_loop,
                args=(slot + 1, jobs, index, formats, failures),
                name=f"udio-worker-{slot + 1}",
            )
            for slot in range(count)
        ]
        for thread in threads:
            thread.start()
        for ref in pending:
            jobs.put(ref)
        for _ in threads:
            jobs.put(None)
        jobs.join()
        for thread in threads:
            thread.join()
        print(
            f"[catalog] Finished: {len(pending) - len(failures)} songs exported, "
            f"{len(failures)} failed; index: {output / 'index.md'}",
            flush=True,
        )
        print(
            f"[catalog] Run summary: exported={len(pending) - len(failures)} "
            f"already_present={skipped} failed={len(failures)} total={len(refs)}",
            flush=True,
        )
        if failures:
            raise RuntimeError(
                f"{len(failures)} song exports failed; see index.md"
            )
    finally:
        index.close()


if __name__ == "__main__":
    main()
