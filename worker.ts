/// <reference types="@cloudflare/workers-types" />

interface Track {
  trackName?: string;
  artistName?: string;
  collectionName?: string;
  releaseDate?: string;
  previewUrl?: string;
  artworkUrl100?: string;
  trackViewUrl?: string;
}

interface SearchResponse {
  results: Track[];
}

export default {
  async fetch(request: Request, env: Env, ctx: EventContext): Promise<Response> {
    const url = new URL(request.url);

    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    const song = url.searchParams.get("song")?.trim();
    const artist = url.searchParams.get("artist")?.trim();
    const format = url.searchParams.get("format") || "json";

    if (!song) {
      return jsonError("Missing required parameter: song", 400);
    }
    if (!artist) {
      return jsonError("Missing required parameter: artist", 400);
    }

    try {
      const tracks = await searchTracks(song, artist);
      if (format === "html") {
        return renderHtml(song, artist, tracks);
      }
      return jsonOk({ song, artist, results: tracks });
    } catch (err) {
      return jsonError(err instanceof Error ? err.message : "Search failed", 500);
    }
  },
};

async function searchTracks(song: string, artist: string): Promise<Track[]> {
  const query = `${song} ${artist}`;
  const searchUrl = new URL("https://itunes.apple.com/search");
  searchUrl.searchParams.set("term", query);
  searchUrl.searchParams.set("entity", "song");
  searchUrl.searchParams.set("limit", "10");

  const resp = await fetch(searchUrl.toString(), {
    headers: { "User-Agent": "MusicBot/1.0" },
  });

  if (!resp.ok) {
    throw new Error(`iTunes API returned status ${resp.status}`);
  }

  const data = (await resp.json()) as SearchResponse;
  if (!data || !Array.isArray(data.results)) {
    throw new Error("Invalid response from music search service");
  }
  return data.results;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function jsonOk(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

function jsonError(message: string, status: number): Response {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

function renderHtml(song: string, artist: string, tracks: Track[]): Response {
  const cards = tracks
    .map((t) => {
      const artwork = t.artworkUrl100
        ? `<img src="${escapeHtml(t.artworkUrl100)}" alt="">`
        : "";
      const preview = t.previewUrl
        ? `<audio controls preload="none"><source src="${escapeHtml(t.previewUrl)}">Your browser does not support audio playback.</audio>`
        : "";
      return `<article>${artwork}<div><h2>${escapeHtml(t.trackName || "Unknown track")}</h2><p>${escapeHtml(t.artistName || "Unknown artist")}</p>${t.collectionName ? `<p class="muted">${escapeHtml(t.collectionName)}</p>` : ""}${preview}</div></article>`;
    })
    .join("");

  const html = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Music Finder</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; background: #10131b; color: #f3f5fa; }
    body { margin: 0; padding: 2rem 1rem; }
    main { max-width: 860px; margin: auto; }
    h1 { margin-bottom: .4rem; }
    .muted { color: #aab2c5; }
    .results { display: grid; gap: 1rem; }
    article { display: flex; gap: 1rem; align-items: flex-start; background: #191e2a; border-radius: .8rem; padding: 1rem; }
    article img { width: 96px; height: 96px; border-radius: .5rem; object-fit: cover; }
    article h2 { margin: 0 0 .4rem; font-size: 1.1rem; }
    article p { margin: .25rem 0; }
    audio { display: block; width: min(100%, 360px); margin-top: .75rem; }
    .empty { padding: 1rem; border-radius: .6rem; background: #292439; }
  </style>
</head>
<body>
  <main>
    <h1>Music Finder</h1>
    <p class="muted">Results for "<b>${escapeHtml(song)}</b>" by "<b>${escapeHtml(artist)}</b>"</p>
    ${tracks.length === 0 ? `<p class="empty">No music found. Check the names and try again.</p>` : `<section class="results">${cards}</section>`}
  </main>
</body>
</html>`;

  return new Response(html, {
    status: 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
    },
  });
}