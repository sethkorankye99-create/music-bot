<?php
/**
 * Music Search Bot
 * Searches for music by song name and artist using iTunes Search API
 */

class MusicSearchBot
{
    private const ITUNES_API_URL = 'https://itunes.apple.com/search';
    private const ENTITY = 'song';
    private const LIMIT = 10;

    /**
     * Search for music tracks
     */
    public function search(string $term, ?string $artist = null): array
    {
        $query = $term;
        if ($artist) {
            $query = "{$term} {$artist}";
        }

        $url = self::ITUNES_API_URL . '?' . http_build_query([
            'term' => $query,
            'entity' => self::ENTITY,
            'limit' => self::LIMIT,
        ]);

        $response = $this->fetch($url);
        $data = json_decode($response, true);

        if (!is_array($data) || !isset($data['results']) || !is_array($data['results'])) {
            throw new RuntimeException('The music search service returned an invalid response.');
        }

        return $data['results'];
    }

    /**
     * Fetch data from URL
     */
    private function fetch(string $url): string
    {
        $context = stream_context_create([
            'http' => [
                'header' => "User-Agent: MusicBot/1.0\r\n",
                'timeout' => 15,
            ],
        ]);

        $response = @file_get_contents($url, false, $context);
        if ($response === false) {
            throw new RuntimeException('Failed to fetch data from iTunes API');
        }

        return $response;
    }

    /**
     * Display search results
     */
    public function displayResults(array $tracks): void
    {
        if (empty($tracks)) {
            echo "No music found.\n";
            return;
        }

        echo str_repeat("=", 60) . "\n";
        echo "Found " . count($tracks) . " result(s):\n";
        echo str_repeat("=", 60) . "\n\n";

        foreach ($tracks as $i => $track) {
            echo ($i + 1) . ". " . ($track['trackName'] ?? 'Unknown track') . "\n";
            echo "   Artist: " . ($track['artistName'] ?? 'Unknown artist') . "\n";
            if (!empty($track['collectionName'])) {
                echo "   Album: " . $track['collectionName'] . "\n";
            }
            if (!empty($track['releaseDate'])) {
                echo "   Release: " . $track['releaseDate'] . "\n";
            }
            if (!empty($track['previewUrl'])) {
                echo "   Preview: " . $track['previewUrl'] . "\n";
            }
            if (!empty($track['artworkUrl100'])) {
                echo "   Artwork: " . $track['artworkUrl100'] . "\n";
            }
            echo str_repeat("-", 40) . "\n";
        }
    }

    /**
     * Run the bot
     */
    public function run(): void
    {
        echo str_repeat("=", 60) . "\n";
        echo "         MUSIC SEARCH BOT\n";
        echo str_repeat("=", 60) . "\n\n";
        echo "Type 'quit' to exit.\n\n";

        while (true) {
            echo "Enter song name: ";
            $song = trim(fgets(STDIN));

            if (strtolower($song) === 'quit') {
                echo "Goodbye!\n";
                break;
            }

            if (empty($song)) {
                echo "Please enter a song name.\n";
                continue;
            }

            echo "Enter artist name (optional, press Enter to skip): ";
            $artist = trim(fgets(STDIN));

            try {
                echo "Searching...\n";
                $tracks = $this->search($song, $artist ?: null);
                $this->displayResults($tracks);
            } catch (Exception $e) {
                echo "Error: " . $e->getMessage() . "\n";
            }

            echo "\n";
        }
    }
}

function escapeHtml(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

if (PHP_SAPI === 'cli') {
    $bot = new MusicSearchBot();
    $bot->run();
    exit;
}

$song = isset($_GET['song']) && is_string($_GET['song']) ? trim($_GET['song']) : '';
$artist = isset($_GET['artist']) && is_string($_GET['artist']) ? trim($_GET['artist']) : '';
$tracks = [];
$error = null;
$searched = array_key_exists('song', $_GET) || array_key_exists('artist', $_GET);

if ($searched) {
    if ($song === '' || $artist === '') {
        $error = 'Enter both a song name and a singer or artist name.';
    } else {
        try {
            $tracks = (new MusicSearchBot())->search($song, $artist);
        } catch (RuntimeException $exception) {
            $error = $exception->getMessage();
        }
    }
}
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Music Finder</title>
    <style>
        :root { color-scheme: dark; font-family: system-ui, sans-serif; background: #10131b; color: #f3f5fa; }
        body { margin: 0; padding: 3rem 1rem; }
        main { max-width: 860px; margin: auto; }
        h1 { margin-bottom: .4rem; }
        .muted { color: #aab2c5; }
        form { display: grid; grid-template-columns: 1fr 1fr auto; gap: .75rem; margin: 2rem 0; }
        label { display: grid; gap: .4rem; font-size: .9rem; }
        input, button { box-sizing: border-box; border: 1px solid #3a4255; border-radius: .6rem; padding: .8rem; font: inherit; }
        input { background: #191e2a; color: inherit; }
        button { align-self: end; border: 0; background: #8b7bff; color: #111; font-weight: 700; cursor: pointer; }
        .results { display: grid; gap: 1rem; }
        article { display: flex; gap: 1rem; align-items: flex-start; background: #191e2a; border-radius: .8rem; padding: 1rem; }
        article img { width: 96px; height: 96px; border-radius: .5rem; object-fit: cover; }
        article h2 { margin: 0 0 .4rem; font-size: 1.1rem; }
        article p { margin: .25rem 0; }
        audio { display: block; width: min(100%, 360px); margin-top: .75rem; }
        .notice { padding: 1rem; border-radius: .6rem; background: #292439; }
        @media (max-width: 620px) { form { grid-template-columns: 1fr; } button { min-height: 44px; } }
    </style>
</head>
<body>
<main>
    <h1>Music Finder</h1>
    <p class="muted">Search for a song by its title and singer or artist.</p>

    <form method="get">
        <label>
            Song name
            <input name="song" value="<?= escapeHtml($song) ?>" required>
        </label>
        <label>
            Singer or artist
            <input name="artist" value="<?= escapeHtml($artist) ?>" required>
        </label>
        <button type="submit">Search music</button>
    </form>

    <?php if ($error !== null): ?>
        <p class="notice" role="alert"><?= escapeHtml($error) ?></p>
    <?php elseif ($searched && count($tracks) === 0): ?>
        <p class="notice">No music found. Check the names and try again.</p>
    <?php elseif ($tracks): ?>
        <h2>Search results</h2>
        <section class="results" aria-label="Music search results">
            <?php foreach ($tracks as $track): ?>
                <article>
                    <?php if (!empty($track['artworkUrl100'])): ?>
                        <img src="<?= escapeHtml($track['artworkUrl100']) ?>" alt="">
                    <?php endif; ?>
                    <div>
                        <h2><?= escapeHtml($track['trackName'] ?? 'Unknown track') ?></h2>
                        <p><?= escapeHtml($track['artistName'] ?? 'Unknown artist') ?></p>
                        <?php if (!empty($track['collectionName'])): ?>
                            <p class="muted"><?= escapeHtml($track['collectionName']) ?></p>
                        <?php endif; ?>
                        <?php if (!empty($track['previewUrl'])): ?>
                            <audio controls preload="none">
                                <source src="<?= escapeHtml($track['previewUrl']) ?>">
                                Your browser does not support audio playback.
                            </audio>
                        <?php endif; ?>
                    </div>
                </article>
            <?php endforeach; ?>
        </section>
    <?php endif; ?>
</main>
</body>
</html>