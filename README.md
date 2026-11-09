# NHL player research with a local model

This tool searches the web for an NHL player's contracts, trades and career statistics. It reads several
sources, checks them against each other, and exports JSON you can import into your own service.
Everything runs on your Mac: the model runs in Ollama (or LM Studio) and search runs on your own SearXNG.

It's built for a **Mac mini M4 with 16 GB of RAM** and an 8B model.

```
player name
   │
   ▼
1. SEARCH     SearXNG (self-hosted, free) runs 6 queries per player
   │          → picks up to 8 pages, at most 2 per site, and always includes stats-table pages
   ▼
2. FETCH      follows robots.txt, waits 5 s between hits to the same site, uses an honest user agent,
   │          caches pages for 7 days, and skips blocked sites (see "Sources" below)
   ▼
3. READ       stats tables are read by CODE (exact numbers, no model)
   │          article text goes to the LOCAL MODEL, which fills a fixed JSON schema
   ▼
4. VERIFY     every contract or trade must quote a sentence that really is on the page
   │          dollar amounts, terms, dates and % retained must appear on the page,
   │          otherwise they're removed. Invented items are dropped and counted.
   ▼
5. MERGE      the same contract or trade from different sites is combined by weighted vote
   │          status: confirmed (2+ sites agree) · single_source · conflict
   ▼
6. CHECK      G+A=PTS, season rows vs. career totals, cap hit × term = total,
   │          overlapping contracts, team changes with no trade, and the JSON schema
   ▼
7. EXPORT     out/players/<slug>.json · <name>.json · <name>.ndjson · <name>-report.md
```

## 1. One-time setup (about 30 minutes)

Open **Terminal** and run these commands in order.

```bash
# Homebrew (skip if you already have it): https://brew.sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python 3.12, plus OrbStack (a light Docker runtime for SearXNG; Docker Desktop also works)
brew install python@3.12
brew install --cask orbstack
```

Install **Ollama** from <https://ollama.com/download>. Open **OrbStack** and **Ollama** once from Applications
so they start. Then:

```bash
# The model (~5 GB download)
ollama pull qwen3:8b

# Optional but recommended on 16 GB: smaller memory use for long pages
launchctl setenv OLLAMA_FLASH_ATTENTION 1
launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0
# then quit Ollama from the menu bar and open it again

# The project: keep it in your home folder, NOT Downloads/Desktop/Documents.
# macOS protects those folders, and Docker can hang at "Starting" waiting for permission.
mv ~/Downloads/nhl-local-pipeline ~/nhl-local-pipeline
cd ~/nhl-local-pipeline
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Search engine
openssl rand -hex 32                     # copy the output into searxng/settings.yml → secret_key
docker compose up -d
```

Edit **`config.toml`** → `user_agent` and put your real email address in the contact part.

Check that everything responds:

```bash
python run.py --check
```

You should see `Ollama OK` and `SearXNG OK`.

## 2. First test run: one player

```bash
source .venv/bin/activate
python run.py --players "Nazem Kadri" --debug
python compare_reference.py out/players/nazem-kadri.json reference/nazem_kadri_contract_trade_stats.json
```

`compare_reference.py` scores the result against the hand-checked files in `reference/`
(Makar, Kane, Hellebuyck, Kadri). Run all four players, then score them together:

```bash
python run.py --players-file players.txt --name test
python compare_reference.py --all
```

To see which pages *would* be read without running the model:

```bash
python run.py --players "Nazem Kadri" --dry-run
```

## 3. A whole team

```bash
caffeinate -i python run.py --team "Colorado Avalanche"
```

`caffeinate -i` keeps the Mac awake. The roster comes from the team's Wikipedia page. If that fails, list the
players in a file (one per line, with an optional `| team` hint for common names) and use `--players-file`.

**Timing (rough):** about 10–20 minutes per player on an M4 with 16 GB, so a 25-player roster is an overnight
run. It's safe to stop (Ctrl-C) and restart: finished players are kept, and fetched pages come from the cache.
Use `--force` to redo a player.

## 3b. The whole league (about 800 players)

**Step 1: build the player list** from all 32 current rosters on Wikipedia, then open the file and check it:

```bash
python run.py --build-league-list league.txt
```

Each line looks like `Cale Makar | Colorado Avalanche`. If a roster couldn't be read, the file has a `#` line
for that team. Add those players by hand, or delete anyone you don't want.

**Step 2: set gentler pacing for a long run** in `config.toml`. About 4,800 searches and 6,000 page visits is
enough to get rate-limited if you go fast:

```toml
[search]
delay_between_searches_s = 5
[fetch]
min_delay_per_domain_s = 8
max_pages_per_player = 6        # optional: about 25% faster, slightly less cross-checking
```

**Step 3: run it**, with the Mac kept awake:

```bash
caffeinate -i python run.py --players-file league.txt --name league
```

After each player, the log prints how many are left and an estimated time to go. Expect **several days on
one Mac**, so check the estimate after the first 10 players. You can stop it (Ctrl-C) and run the same
command again at any time: finished players are skipped.

**Two Macs (about half the time):** set up the project on both, each with its own Ollama and SearXNG and the
**same** `league.txt`. Raise `min_delay_per_domain_s` to 10 on both, since sites see both machines. Then:

```bash
# Mac mini
caffeinate -i python run.py --players-file league.txt --name league --shard 1/2
# MacBook Pro
caffeinate -i python run.py --players-file league.txt --name league --shard 2/2
```

**Combine the results:** copy `out/players/*.json` from the second Mac into `out/players/` on the first, then
run the full command once more without `--shard`. Every player is already done, so it only writes the
combined `league.json`, `league.ndjson` and `league-report.md`, in seconds.

**Failures:** players that hit an error, or for whom no pages could be read, are listed in
`out/league-failed.txt` and aren't marked done. Run the same command again later to retry them.

## 4. Output

| File | What it is |
|---|---|
| `out/players/<slug>.json` | one player record |
| `out/<name>.json` | all players in one JSON array |
| `out/<name>.ndjson` | one record per line, which most import tools accept |
| `out/<name>-report.md` | summary table plus every warning to review |
| `out/debug/` | raw model answers (with `--debug`), useful when something looks wrong |
| `schema/player_record.schema.json` | JSON Schema of the record, for setting up your import |

Each record has `player`, `draft`, `contracts`, `trade_history`, `career_statistics`, `summary`,
`verification` and `sources`. Every contract and trade carries:

- `status`: `confirmed`, `single_source` or `conflict`
- `sources`: the URLs it came from
- `evidence`: the quoted sentence(s)
- `derived_fields`: values worked out with arithmetic rather than read from a page, e.g. cap hit = total ÷ term

**Before importing, filter on `status`.** For example, import `confirmed` items directly and send
`single_source` and `conflict` items to a review queue.

## 5. How accuracy is protected

- **Stats never go through the model.** Code reads the tables, and two sites are compared row by row. The
  current season is allowed to differ (sites update at different times), and the most recent count is kept.
- **The model only reads.** Code decides what to search, which pages to read and how to merge. Small models
  are poor at open-ended research but good at filling a form from one page.
- **Nothing unverified gets through.** Each item needs a quote found on the page. Money (±1%), contract
  length, years and % retained must also appear on that page.
- **Cross-checking.** One site alone gives `single_source`. When sites disagree you get `conflict`, with every
  reported value kept.

## 6. Sources and rules

- **Skipped on purpose** (`config.toml → blocked`):
  - Sports Reference sites (Hockey-Reference), whose terms forbid scraping and using their content to prompt AI models
  - Amazon and social media, which block scrapers or are unreliable
  - Paywalled news, which returns no article text
- **Trust weights:** NHL.com, PuckPedia and CapWages are weighted highest when sources disagree. You can edit the
  weights in `config.toml`.
- **Robots.txt is always followed.** A site that answers "too many requests" is left alone for the rest of the run.
- **Personal use.** This is meant for personal research. If you publish or sell the data, read each site's
  terms first (this isn't legal advice).

## 7. Tuning

| Setting | Default | When to change |
|---|---|---|
| `llm.model` | `qwen3:8b` | Try `llama3.1:8b`. `qwen3:14b` fits only with `num_ctx = 8192` and other apps closed |
| `llm.num_ctx` | 16384 | Lower it to 8192 if the Mac shows memory pressure. 32768 is tight on 16 GB |
| `extract.max_chars_per_call` | 30000 | Keep at about 2× `num_ctx`. Lower it together with `num_ctx` |
| `fetch.max_pages_per_player` | 8 | More pages means more cross-checking but a slower run |
| `search.queries` | 6 queries | Add site-specific ones, e.g. `"{name} site:nhl.com"` |

**Faster option, LM Studio (MLX):** install LM Studio, download an MLX build of Qwen3 8B, and start its local
server. Then set:

```toml
[llm]
provider = "openai"
base_url = "http://localhost:1234/v1"
model = "<the model id LM Studio shows>"
```

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| `docker compose up -d` stuck at "Starting" | macOS is blocking access to the folder. Move the project to your home folder (`~/nhl-local-pipeline`), or allow OrbStack under System Settings → Privacy & Security → Files and Folders. Then `docker compose down` and `docker compose up -d` |
| `SearXNG returned no results` | `docker compose ps`, then `docker compose logs searxng`. Some engines rate-limit; enable more in `searxng/settings.yml` and run `docker compose restart` |
| `model 'qwen3:8b' not found` | `ollama pull qwen3:8b` |
| Very slow, or the Mac swaps | Close Chrome and other apps, set `num_ctx = 8192`, and check the Ollama memory env vars above |
| Many items "dropped" | Look in `out/debug/<player>/`. The model may be paraphrasing instead of quoting; try `llama3.1:8b` |
| No stats | Run `--dry-run` to see whether Wikipedia, Elite Prospects or HockeyDB pages were found. Pages built with JavaScript can't be read |
| Wrong player (common name) | Add a team hint in the players file: `Sebastian Aho | Carolina Hurricanes` |

## 9. Tests

```bash
pip install pytest
python -m pytest -q
```

The tests run offline with fake web pages, a fake search engine and a fake model. They cover the
politeness rules, table reading, the anti-hallucination checks, merging and export. **The first run on your
Mac is the first time it meets real websites and a real model**, so start with one player and `--debug`.

## 10. Hourly game tracker (no AI model needed)

`daily.py` records, for every finished game:
- the **game-winning goal**
- **power-play**, **shorthanded** and **empty-net goals**
- **shutouts**

It also keeps **season leaderboards** for each of those and a **standings** snapshot. The data comes from the
NHL's public game feed and is computed by code, so it's exact, fast, and light enough for the 16 GB Mac mini
to run all day.

**Try it once:**
```bash
python daily.py --date 2026-11-08
```

**Fill in the season so far** (about one request per day, plus a few extra for shutouts):
```bash
python daily.py --from 2026-10-01
```

**Run it every hour in the background:**
```bash
chmod +x schedule_hourly.sh
./schedule_hourly.sh
```
Each run checks yesterday and today (late games finish after midnight). Finished games are saved once and
never fetched again. Remove the job with `./schedule_hourly.sh --remove`.

**Output** in `out/games/`:

| File | Contents |
|---|---|
| `2026-11-08.json` | every finished game that day, with GWG, PP/SH/EN goals, shutouts and score |
| `leaders-20262027-regular.json` | season leaders: GWG, PPG, SHG, ENG, shutouts (playoffs get their own file) |
| `standings.json` | current standings: points, record, last 10, streak, goal difference |
| `last_run.json` | when it last ran, and any warnings |

Everything is also stored in `data/nhl_games.db` (SQLite).

**Rules used:**
- **Game-winning goal:** the winning team's goal that gives it one more than the loser's final total. Shootout
  wins have no individual game-winning goal.
- **Shutout:** a goalie gets one only if he played the whole game alone. If two goalies shared it, it's a team
  shutout. In a 0-0 game decided by a shootout, both goalies are credited.
- **Incomplete feed:** if a game's goal list doesn't add up to the final score, the game is flagged, stored
  without a game-winning goal, and re-checked next hour.

**Tips:**
- Keep the Mac mini from sleeping: System Settings → Energy → "Prevent automatic sleeping".
- If `logs/daily.log` shows "Operation not permitted" while the project is on the external SSD, give Python
  access under System Settings → Privacy & Security → Files and Folders (Removable Volumes). Or move the
  project to your home folder.
- The NHL feed is free and needs no key, but it's unofficial. That's fine for personal use; a commercial
  product should license official data.
