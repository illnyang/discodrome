<div align="center">
  
# <img src="resources/discodrome.png" width="32" height="32" alt="Discodrome Icon"> Discodrome

### Subsonic Compatible Discord Music Bot

[![GitHub issues](https://img.shields.io/github/issues/7eventy7/discodrome.svg)](https://github.com/7eventy7/discodrome/issues)
[![Docker Pulls](https://img.shields.io/docker/pulls/7eventy7/discodrome.svg)](https://hub.docker.com/r/7eventy7/discodrome)
[![License](https://img.shields.io/github/license/7eventy7/discodrome.svg)](https://github.com/7eventy7/discodrome/blob/main/LICENSE)

A Discord music bot that seamlessly streams music from your personal music server directly to your voice channels. Works great with Navidrome and other Subsonic-compatible music servers.

</div>

---

## Commands

Music commands are hybrid commands, so they can be used as slash commands or with the configured message prefix. For example, `/play` and `?play` both play a track, album, or playlist (`?` is the default prefix).

| Slash command | Prefix command | Description |
|---------------|----------------|-------------|
| `/play` | `?play` | Place a specified track, album, or playlist at the end of the queue and start playing |
| `/next` | `?next` | Place a specified track next in the queue and start playing |
| `/disco` | `?disco` | Play an artist's entire discography |
| `/queue` | `?queue` | View, remove, or move tracks in the current queue |
| `/clear` | `?clear` | Clear the current queue |
| `/shuffle` | `?shuffle` | Shuffle the current queue |
| `/skip` | `?skip` | Skip the current track |
| `/stop` | `?stop` | Stop playing the current track |
| `/pause`, `/pa` | `?pause`, `?pa` | Pause the current track |
| `/resume`, `/r` | `?resume`, `?r` | Resume the paused track |
| `/goto`, `/g` | `?goto`, `?g` | Jump to an absolute position in the current track |
| `/leave` | `?leave` | Stop playback, clear the queue, and leave the voice channel |
| `/autoplay` | `?autoplay` | Toggle autoplay |
| `/audiobalance` | `?audiobalance` | Configure automatic audio balancing |
| `/playlists` | `?playlists` | List available playlists |
| `/playlist` | `?playlist` | List songs in a playlist |
| `/sync` | `?sync` | Sync application commands (owner only) |

The existing short music commands are available in both forms as well: `/p` and `?p` play a track, `/n` and `?n` queue one next, `/s` and `?s` skip, and `/q` and `?q` show the queue. Replace `?` with your configured `BOT_PREFIX` when it differs from the default. Prefix queries containing spaces can be entered as the remaining text after the command; quote playlist names when also specifying a page.

`/play` and `/next` suggest matching tracks as you type; an empty track query suggests random tracks.

`pause/pa`, `resume/r`, and `goto/g` control the current track without changing the queue. `p` remains the shortcut for **play**. Seeking while paused keeps the track paused.

Choose the `goto/g` timestamp format using the current track's full duration:

| Track duration | Required format | Example |
|----------------|-----------------|---------|
| More than one hour | `hh:mm:ss` | `/goto 01:02:03` |
| More than one minute, up to and including one hour | `mm:ss` | `?g 02:30` |
| Up to and including one minute | `ss` | `/g 15` |

Colon-separated minutes and seconds require two digits from `00` to `59`; hours require at least two digits. Seconds-only input accepts one or two digits. Positions must be nonnegative and strictly before the end of the track. Tracks with an unknown duration cannot be seeked.

Queue positions are 1-based and exclude the currently playing track. Use `/queue` (or `?queue`) to browse ten tracks per page, `/queue action:Remove index:2` (`?queue remove 2`) to remove a track, or `/queue action:Move index:3 target:1` (`?queue move 3 1`) to move one. Page buttons are available only to the command's author and show a snapshot of the queue.

The queue's **Now Playing** section shows `(current time/total time)`, for example `(01:23/04:56)`. The timestamp is captured when you request the queue and remains unchanged when browsing that snapshot's pages.

Regular voice channels show `Track by Artist (current time/total time)`. Progress refreshes every 15 seconds when the timestamp changes, and the status clears when playback stops or finishes. Grant the bot `Set Voice Channel Status` to enable this display.

---

## Requirements

- Docker running on an x64 or ARM device

**For non-Docker deployment or development:**
- Python 3.10 or later
- FFmpeg available in PATH

---

## Quick Start

### Step 1 — Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** and give it a name
3. Navigate to the **Bot** tab and click **Add Bot**
4. Under the TOKEN section, click **Reset Token** and copy your new token
5. Enable the following Privileged Gateway Intents:
   - `MESSAGE CONTENT INTENT`
   - `SERVER MEMBERS INTENT`
   - `PRESENCE INTENT`
6. Navigate to **OAuth2 → URL Generator**
7. Select the following scopes: `bot`, `applications.commands`
8. Select bot permissions: `Send Messages`, `Connect`, `Speak`, `Use Voice Activity`, `Read Message History`
9. Copy the generated URL and paste it into your browser to invite the bot to your server

To show the current track and artist in a regular voice channel's status, also grant `Set Voice Channel Status`. The status is cleared when playback finishes or stops; stage channels are left unchanged. Status-update failures are logged without interrupting playback.

### Step 2 — Gather Required Information

- **Discord Bot Token** — from Step 1
- **Discord Server ID** — right-click your server icon and select **Copy ID** (requires Developer Mode enabled in Discord settings)
- **Your Discord User ID** — right-click your username and select **Copy ID**
- **Subsonic Server Details** — URL, username, password and auth mode for your music server
  - Use token auth mode unless you have a good reason not to

### Step 3 — Deploy with Docker

Create a `.env` file next to `docker-compose.yml` with the environment variables described in the Configuration section, then build and start the bot:

```
docker compose build --no-cache
docker compose up -d
```

The Compose file builds from your local checkout, including any merged changes. After updating the checkout, re-run `docker compose build --no-cache` and `docker compose up -d` to rebuild and restart the bot.

---

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SUBSONIC_SERVER` | URL of your Subsonic server (include http/https) | Yes |
| `SUBSONIC_USER` | Username for your Subsonic server | Yes |
| `SUBSONIC_PASSWORD` | Password or auth token for your Subsonic server | Yes |
| `SUBSONIC_AUTH_MODE` | Authentication mode: `plaintext` or `token`. Token auth is highly recommended for security. | Yes |
| `DISCORD_BOT_TOKEN` | Your Discord bot token | Yes |
| `DISCORD_OWNER_ID` | Your Discord user ID | Yes |
| `DISCORD_TEST_GUILD` | Discord server ID for testing during development. Set this to sync commands to that server immediately as well as globally; without it, global slash-command updates may take time to appear. | No |
| `APP_ID` | Optional Discord application ID for the listening activity. | No |
| `BOT_STATUS` | Custom status message for the bot | No |
| `BOT_PREFIX` | Command prefix for the bot. If unset, prefix commands can still be used with an @mention. An empty string will cause all messages to be interpreted as commands. | No |
| `BOT_SEARCH_SUGGESTION_COUNT` | Number of items to display in the autocomplete menu. Defaults to 5. | No |

### Saved Guild State

Queues, autoplay mode, and audio balance mode are saved to `guild_properties.json`. On first startup, an existing `guild_properties.pickle` is migrated automatically and retained as a backup. Invalid saved state stops startup to avoid overwriting it; repair the file or restore a backup before restarting.

Audio balance defaults to `dynamic`; use `/audiobalance` or `?audiobalance` with `off`, `replaygain`, or `dynamic`. Changes apply to the next track.

Run the isolated persistence, audio-filter, queue, and voice-status regression checks with `python -m unittest discover -s tests -v`. They do not connect to Discord or Subsonic.

### Supported Subsonic Servers

- Navidrome
- Airsonic
- Subsonic
- Gonic
- Ampache (with Subsonic API enabled)
- Jellyfin (with Subsonic plugin)

---

## Contributing

Contributions are welcome. This includes:

- Reporting bugs
- Suggesting features
- Improving documentation
- Submitting fixes
- Adding new features

Please check the [GitHub Issues](https://github.com/7eventy7/discodrome/issues) page before submitting new ones.

---

## License

GPL-3.0 — free to use for most purposes.

---

## Acknowledgments

This project is a fork of [Submeister](https://github.com/Gimzie/submeister) by Gimzie. Built upon their foundation with additional features and improvements while preserving the core functionality of the original.

---

<div align="center">
Forked with care by <a href="https://github.com/7eventy7">7eventy7</a>
</div>
