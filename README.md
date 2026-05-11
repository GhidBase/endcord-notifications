# endcord-notifications

A notification browser extension for [endcord](https://github.com/SparkLost/endcord), a Discord TUI client.

Requires [endcord-vim](https://github.com/GhidBase/endcord-vim) (uses vim normal mode).

## Installation

Copy `endcord_notifications.py` into your endcord extensions directory:

```
~/.local/share/endcord/Extensions/endcord_notifications/endcord_notifications.py
```

## Usage

Press `B` in vim normal mode to open the notification viewer.

| Key | Action |
|-----|--------|
| `B` | Open notification viewer |
| `j` / `↓` | Move selection down |
| `k` / `↑` | Move selection up |
| `f` / `Tab` | Cycle filter mode |
| `Enter` | Switch to the selected channel |
| `Escape` | Close the viewer |

## Filter modes

| Mode | Shows |
|------|-------|
| `mentions` | Channels where you were @mentioned |
| `unreads` | All channels with unread messages |
| `dms` | DMs and group DMs with unreads |

The `@` icon indicates a mention; `•` indicates an unread without a mention. Mention counts are shown as `@N` next to the channel name.

## License

GPLv3 — see source file header.
