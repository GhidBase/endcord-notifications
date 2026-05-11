# Copyright (C) 2025-2026 Dylan Simon
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.

"""Notifications viewer: browse channels/DMs with mentions or unreads, navigate with j/k, Enter to switch."""

import curses
import json
import logging
import os
import time

EXT_NAME = "Notifications Viewer"
EXT_VERSION = "0.2.0"
EXT_ENDCORD_VERSION = "1.4.2"
EXT_DESCRIPTION = "Press B (vim normal mode) to browse channels with mentions, unreads, or notification history."
EXT_SOURCE = "https://github.com/GhidBase/endcord-notifications"

logger = logging.getLogger(__name__)

_NOTIF_CODE = 1003
_TRIGGER = ord('B')
_FILTERS = ["mentions", "unreads", "dms", "history"]
_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notification_history.json")
_HISTORY_MAX = 300     # max entries to keep
_SCAN_INTERVAL = 8     # seconds between background scans


class Extension:
    def __init__(self, app):
        self.app = app
        self._filter_idx = 0
        self._history = _load_history()   # list of {"channel_id": str, "display": str}
        self._last_scan = 0.0
        logger.info("Notifications viewer active — press B in vim normal mode")

    # ── background scanning ───────────────────────────────────────────────────

    def on_main_loop(self):
        now = time.time()
        if now - self._last_scan < _SCAN_INTERVAL:
            return
        self._last_scan = now
        self._scan_unreads()

    def _scan_unreads(self):
        app = self.app
        if not getattr(app, 'tree_format', None) or not getattr(app, 'tree_metadata', None):
            return

        existing = {e["channel_id"] for e in self._history}
        added = False

        for raw_idx, (code, meta) in enumerate(zip(app.tree_format, app.tree_metadata)):
            if meta is None:
                continue
            kind = code // 100
            if kind >= 10 or kind in (0, 1, 2):
                continue
            status = (code // 10) % 10
            if status not in (2, 3, 5):   # not unread or mentioned
                continue

            ch_id = str(meta["id"])
            if ch_id in existing:
                continue

            display = self._build_display(raw_idx, code, meta, app)
            self._history.append({"channel_id": ch_id, "display": display})
            existing.add(ch_id)
            added = True

        if added:
            if len(self._history) > _HISTORY_MAX:
                self._history = self._history[-_HISTORY_MAX:]
            _save_history(self._history)

    # ── list building ─────────────────────────────────────────────────────────

    def _build_list(self, filter_mode):
        app = self.app

        if filter_mode == "history":
            return self._build_history_list()

        results = []
        for raw_idx, (code, meta) in enumerate(zip(app.tree_format, app.tree_metadata)):
            if meta is None:
                continue
            kind = code // 100
            if kind >= 10 or kind in (0, 1, 2):
                continue
            status = (code // 10) % 10
            is_mentioned = status in (2, 5)
            is_unread = status in (2, 3, 5)
            is_dm = meta["type"] in (1, 3)

            if filter_mode == "mentions" and not is_mentioned:
                continue
            if filter_mode == "unreads" and not is_unread:
                continue
            if filter_mode == "dms" and (not is_dm or not is_unread):
                continue

            results.append({
                "display": self._build_display(raw_idx, code, meta, app),
                "channel_id": str(meta["id"]),
            })
        return results

    def _build_history_list(self):
        app = self.app

        # Build a quick status lookup from the current tree
        current = {}
        if getattr(app, 'tree_format', None) and getattr(app, 'tree_metadata', None):
            for raw_idx, (code, meta) in enumerate(zip(app.tree_format, app.tree_metadata)):
                if meta is None:
                    continue
                kind = code // 100
                if kind >= 10 or kind in (0, 1, 2):
                    continue
                status = (code // 10) % 10
                current[str(meta["id"])] = (raw_idx, code, meta)

        results = []
        seen = set()
        for entry in reversed(self._history):   # most recent first
            ch_id = entry["channel_id"]
            if ch_id in seen:
                continue
            seen.add(ch_id)

            if ch_id in current:
                raw_idx, code, meta = current[ch_id]
                status = (code // 10) % 10
                is_mentioned = status in (2, 5)
                is_unread = status in (2, 3, 5)
                icon = "@" if is_mentioned else ("•" if is_unread else " ")
                display = icon + entry["display"][1:]   # swap icon, keep rest
            else:
                # Channel not in current tree (read, left server, etc.) — show as plain
                display = "  " + entry["display"][1:].lstrip()

            results.append({"display": display, "channel_id": ch_id})

        return results

    def _build_display(self, raw_idx, code, meta, app):
        status = (code // 10) % 10
        is_mentioned = status in (2, 5)
        is_dm = meta["type"] in (1, 3)
        channel_name = meta["name"] or ""
        channel_id = str(meta["id"])

        read_state = app.read_state.get(channel_id) or app.read_state.get(meta["id"], {})
        mentions = read_state.get("mentions", [])
        mention_count = f" @{len(mentions)}" if mentions else ""
        icon = "@" if is_mentioned else "•"

        if is_dm:
            return f"{icon} {channel_name}{mention_count}"
        else:
            guild_id, _parent_id, guild_name = app.find_parents_from_tree(raw_idx)
            prefix = f"[{guild_name}] " if guild_name else ""
            return f"{icon} {prefix}#{channel_name}{mention_count}"

    # ── viewer ────────────────────────────────────────────────────────────────

    def on_binding(self, key, is_command, is_forum):
        tui = self.app.tui
        if getattr(tui, 'insert_mode', True):
            return
        if key != _TRIGGER:
            return
        self._run_viewer()
        return _NOTIF_CODE

    def on_wait_input(self, action_code, input_text, chat_sel, tree_sel):
        if action_code == _NOTIF_CODE:
            self.app.restore_input_text = (input_text, "standard")
            return True

    def _run_viewer(self):
        app = self.app
        tui = app.tui
        filter_mode = _FILTERS[self._filter_idx]
        items = self._build_list(filter_mode)
        selected = 0
        scroll = 0

        def draw():
            title = f" Notifications [{filter_mode}]  j/k·move  f·filter  Enter·go  Esc·close "
            body = [item["display"] for item in items] or ["(none)"]
            tui.extra_index = scroll
            tui.extra_selected = selected
            tui.draw_extra_window(title, body, select=True, reset_scroll=False)

        tui.extra_index = 0
        tui.extra_selected = 0
        draw()

        tui.screen.timeout(-1)
        try:
            while True:
                k = tui.screen.getch()

                if k == 27:
                    break

                elif k in (ord('j'), curses.KEY_DOWN) and items:
                    if selected + 1 < len(items):
                        selected += 1
                        if tui.win_extra_window:
                            h = tui.win_extra_window.getmaxyx()[0] - 1
                            if selected >= scroll + h:
                                scroll += 1

                elif k in (ord('k'), curses.KEY_UP) and items:
                    if selected > 0:
                        selected -= 1
                        if scroll > selected:
                            scroll = selected

                elif k in (ord('f'), 9):
                    self._filter_idx = (self._filter_idx + 1) % len(_FILTERS)
                    filter_mode = _FILTERS[self._filter_idx]
                    items = self._build_list(filter_mode)
                    selected = 0
                    scroll = 0

                elif k in (10, 13, curses.KEY_ENTER) and items:
                    item = items[selected]
                    tui.remove_extra_window()
                    ch_id, ch_name, guild_id, guild_name, parent_id = app.find_parents_from_id(item["channel_id"])
                    if ch_id:
                        app.switch_channel(ch_id, ch_name, guild_id, guild_name, parent_hint=parent_id)
                        app.reset_states(replying=True)
                        app.update_status_line()
                    return

                draw()
        finally:
            tui.screen.timeout(200)
            tui.remove_extra_window()


# ── persistence ───────────────────────────────────────────────────────────────

def _load_history():
    try:
        with open(_HISTORY_FILE) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def _save_history(history):
    try:
        with open(_HISTORY_FILE, "w") as f:
            json.dump(history, f)
    except OSError as e:
        logger.error(f"notifications: could not save history: {e}")
