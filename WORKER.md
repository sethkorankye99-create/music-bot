# Music Bot - Cloudflare Worker

A serverless music search bot that queries the iTunes catalog by song title and singer/artist. Returns JSON results or an HTML page with playable previews.

## Features

- Searches the iTunes Search API (free, no API key required)
- Returns up to 10 tracks with metadata and album artwork
- Includes 30-second preview audio clips where available
- Supports JSON and HTML response formats
- CORS enabled for direct browser calls

## Usage

### JSON API

```
GET /?song=Never%20Gonna%20Give%20You%20Up&artist=Rick%20Astley&format=json
```

### HTML page

```
GET /?song=Never%20Gonna%20Give%20You%20Up&artist=Rick%20Astley&format=html
```

## Deploy to Cloudflare

1. Install Wrangler CLI:

```bash
npm install -g wrangler
```

2. Log in to Cloudflare:

```bash
wrangler login
```

3. Deploy:

```bash
wrangler deploy
```

The bot will be available at a `*.workers.dev` URL.

## Environment

No environment variables or secrets required. The bot only calls the public iTunes API.