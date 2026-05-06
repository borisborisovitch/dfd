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

async function loadTracks() {
    const container = document.querySelector("#trackList");
    container.innerHTML = "";

    const { tracks } = await browser.storage.local.get("tracks");
    if (!tracks) {
        container.textContent = "No tracks available.";
        return;
    }

    tracks.audio.forEach(track => {
        const div = document.createElement("div");
        div.className = "track";
        div.innerHTML = `
            <strong>Audio Track</strong>
            <div class="track-details">
                Bandwidth: ${track.bandwidth}<br>
                Language: ${track.lang}<br>
            </div>
            <button class="download">Download</button>
        `;

        div.querySelector("button.download").addEventListener("click", () => {
            browser.downloads.download({
                url: track.url,
                filename: `WidevineMedia/audio_${track.lang}_${track.bandwidth}.mp4`,
                conflictAction: "uniquify",
                saveAs: false
            }).then((data) => browser.runtime.getBackgroundPage().then((window) => window.downloadIds.push(data)));
        });

        container.appendChild(div);
    });

    tracks.video.forEach(track => {
        const div = document.createElement("div");
        div.className = "track";
        div.innerHTML = `
            <strong>Video Track</strong>
            <div class="track-details">
                Bandwidth: ${track.bandwidth}<br>
                Resolution: ${track.res}<br>
            </div>
            <button class="download">Download</button>
        `;

        div.querySelector("button.download").addEventListener("click", () => {
            browser.downloads.download({
                url: track.url,
                filename: `WidevineMedia/video_${track.res}_${track.bandwidth}.mp4`,
                conflictAction: "uniquify",
                saveAs: false
            }).then((data) => browser.runtime.getBackgroundPage().then((window) => window.downloadIds.push(data)));
        });

        container.appendChild(div);
    });
}

document.querySelector("#refresh").addEventListener("click", loadTracks);

document.querySelector("#clear").addEventListener("click", async () => {
    await browser.storage.local.remove("tracks");
    loadTracks();
});

loadTracks();
