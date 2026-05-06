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

async function storeTracks(tracks) {
  const stored = await browser.storage.local.get("tracks");
  const oldTracks = stored.tracks || { audio: [], video: [] };

  const byFile = new Map();

  [...oldTracks.audio, ...oldTracks.video].forEach(t => {
    byFile.set(t.url, t);
  });

  [...tracks.audio, ...tracks.video].forEach(t => {
    const file = t.url;
    if (!byFile.has(file)) {
      byFile.set(file, t);
    }
  })

  filtered = { audio: [], video: [] }
  for (const track of byFile.values()) {
    if (track.type === "audio") filtered.audio.push(track);
    else filtered.video.push(track);
  }

  console.log(JSON.stringify(filtered, undefined, 2));

  await browser.storage.local.set({ tracks: filtered });
}

function parseManifest(manifest, baseUrl) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(manifest, "application/xml");
  const adaptationSets = doc.getElementsByTagName("AdaptationSet");

  const tracks = { audio: [], video: [] };
  audioSets = Array.from(adaptationSets).filter(set => set.getAttribute("contentType") == "audio");
  audioSets.forEach(set => {
    lang = set.getAttribute("lang");
    reps = Array.from(set.getElementsByTagName("Representation"));
    reps.forEach(rep => {
      bandwidth = rep.getAttribute("bandwidth");
      url = rep.getElementsByTagName("BaseURL")[0].textContent;
      if (url.endsWith(".mp4"))
        tracks.audio.push({ type: "audio", lang: lang, bandwidth: bandwidth, url: baseUrl + url });
    });
  });

  videoSets = Array.from(adaptationSets).filter(set => set.getAttribute("contentType") == "video");
  videoSets.forEach(set => {
    reps = Array.from(set.getElementsByTagName("Representation"));
    reps.forEach(rep => {
      bandwidth = rep.getAttribute("bandwidth");
      x = rep.getAttribute("width");
      y = rep.getAttribute("height");
      url = rep.getElementsByTagName("BaseURL")[0].textContent;
      if (url.endsWith(".mp4"))
        tracks.video.push({ type: "video", res: `${x}x${y}`, bandwidth: bandwidth, url: baseUrl + url });
    });
  });

  storeTracks(tracks);
}

function catchManifest(details) {
  const baseUrl = details.url.slice(0, details.url.split('#')[0].split('?')[0].lastIndexOf("/") + 1);

  const filter = browser.webRequest.filterResponseData(details.requestId);
  const decoder = new TextDecoder("utf-8");
  const encoder = new TextEncoder();

  playlist = "";

  filter.ondata = event => {
    const data = decoder.decode(event.data, { stream: true });
    filter.write(encoder.encode(data));

    playlist += data;
  }

  filter.onstop = event => {
    filter.close();
    parseManifest(playlist, baseUrl);
  };
}

browser.webRequest.onBeforeRequest.addListener(
  catchManifest,
  { urls: ["*://*/*.mpd"], types: ["xmlhttprequest"] },
  ["blocking"]
);

var downloadIds = [];

browser.downloads.onChanged.addListener(async downloadDelta => {
  if (downloadDelta.state && downloadDelta.state.current === "complete") {
    const idx = downloadIds.indexOf(downloadDelta.id);
    if (idx == -1) {
      return;
    }
    downloadIds.splice(idx, 1);

    const results = await browser.downloads.search({ id: downloadDelta.id });
    if (results.length > 0) {
      const filePath = results[0].filename;

      const blob = new Blob([filePath], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);

      browser.downloads.download({
        url: url,
        filename: "WidevineMedia/notification.txt",
        saveAs: false
      });
    }
  }
});

browser.storage.local.set({ audio: [], video: [] });