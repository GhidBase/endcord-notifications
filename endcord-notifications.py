# Copyright (C) 2025-2026 Dylan Simon
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.

"""Notifications viewer: browse mentions and unreads, navigate with j/k, Enter to switch."""

import curses
import logging

EXT_NAME = "Notifications Viewer"
EXT_VERSION = "0.5.0"
EXT_ENDCORD_VERSION = "1.4.2"
EXT_DESCRIPTION = "Press B (vim normal mode) to browse notifications. f=filter  u=unread  g=server  Enter=go."
EXT_SOURCE = "https://github.com/GhidBase/endcord-notifications"

logger = logging.getLogger(__name__)

_NOTIF_CODE = 1003
_TRIGGER = ord('B')
_FILTERS = ["mentions", "unreads"]
_MENTIONS_FETCH = 50


class Extension:
    def __init__(self, app):
        self.app = app
        self._filter_idx = 0
        logger.info("Notifications viewer active — press B in vim normal mode")

    # ── list building ─────────────────────────────────────────────────────────

    def _build_list(self, filter_mode, guild_filter=None, mentions_unread_only=False):
        if filter_mode == "mentions" and mentions_unread_only:
            results = self._build_live_mentions_list()
        elif filter_mode == "mentions":
            results = self._build_mentions_list()
        else:
            results = self._build_unreads_list()

        if guild_filter is not None:
            results = [r for r in results if r.get("guild_id") == guild_filter]

        return results

    def _build_mentions_list(self):
        app = self.app
        try:
            mentions = app.discord.get_mentions(num=_MENTIONS_FETCH)
        except Exception as e:
            logger.error(f"notifications: get_mentions failed: {e}")
            return [{"display": "  (failed to load)", "channel_id": None, "guild_id": None}]
        if not mentions:
            return []

        results = []
        for m in mentions:
            ch_id = str(m["channel_id"])
            _cid, ch_name, guild_id, guild_name, _parent = app.find_parents_from_id(ch_id)
            author = m.get("global_name") or m.get("username") or "?"
            snippet = (m.get("content") or "")[:60].replace("\n", " ")
            if guild_name:
                display = f"@ [{guild_name}] #{ch_name}  {author}: {snippet}"
            else:
                display = f"@ {ch_name or ch_id}  {author}: {snippet}"
            results.append({
                "display": display,
                "channel_id": ch_id,
                "guild_id": str(guild_id) if guild_id else None,
            })
        return results

    def _build_live_mentions_list(self):
        """Currently mentioned channels from the sidebar tree."""
        app = self.app
        results = []
        for raw_idx, (code, meta) in enumerate(zip(app.tree_format, app.tree_metadata)):
            if meta is None:
                continue
            kind = code // 100
            if kind >= 10 or kind in (0, 1, 2):
                continue
            status = (code // 10) % 10
            if status not in (2, 5):   # mentioned only
                continue

            guild_id, _parent_id, guild_name = app.find_parents_from_tree(raw_idx)
            is_dm = meta["type"] in (1, 3)
            channel_name = meta["name"] or ""
            channel_id = str(meta["id"])

            read_state = app.read_state.get(channel_id) or app.read_state.get(meta["id"], {})
            mentions = read_state.get("mentions", [])
            mention_count = f" @{len(mentions)}" if mentions else ""

            if is_dm:
                display = f"@ {channel_name}{mention_count}"
            else:
                prefix = f"[{guild_name}] " if guild_name else ""
                display = f"@ {prefix}#{channel_name}{mention_count}"

            results.append({
                "display": display,
                "channel_id": channel_id,
                "guild_id": str(guild_id) if guild_id else None,
            })
        return results

    def _build_unreads_list(self):
        app = self.app
        results = []
        for raw_idx, (code, meta) in enumerate(zip(app.tree_format, app.tree_metadata)):
            if meta is None:
                continue
            kind = code // 100
            if kind >= 10 or kind in (0, 1, 2):
                continue
            status = (code // 10) % 10
            if status not in (2, 3, 5):
                continue

            guild_id, _parent_id, guild_name = app.find_parents_from_tree(raw_idx)
            is_mentioned = status in (2, 5)
            is_dm = meta["type"] in (1, 3)
            channel_name = meta["name"] or ""
            channel_id = str(meta["id"])

            read_state = app.read_state.get(channel_id) or app.read_state.get(meta["id"], {})
            mentions = read_state.get("mentions", [])
            mention_count = f" @{len(mentions)}" if mentions else ""
            icon = "@" if is_mentioned else "•"

            if is_dm:
                display = f"{icon} {channel_name}{mention_count}"
            else:
                prefix = f"[{guild_name}] " if guild_name else ""
                display = f"{icon} {prefix}#{channel_name}{mention_count}"

            results.append({
                "display": display,
                "channel_id": channel_id,
                "guild_id": str(guild_id) if guild_id else None,
            })
        return results

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
        guild_filter = None
        guild_filter_name = None
        mentions_unread_only = False
        items = self._build_list(filter_mode)
        selected = 0
        scroll = 0

        def draw():
            unread_tag = "·unread" if (filter_mode == "mentions" and mentions_unread_only) else ""
            server_tag = f"|{guild_filter_name}" if guild_filter_name else ""
            title = (
                f" Notifications [{filter_mode}{unread_tag}{server_tag}]"
                f"  j/k·move  f·filter"
                + ("  u·unread" if filter_mode == "mentions" else "")
                + "  g·server  Enter·go  Esc·close "
            )
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
                    guild_filter = None
                    guild_filter_name = None
                    mentions_unread_only = False
                    items = self._build_list(filter_mode)
                    selected = 0
                    scroll = 0

                elif k == ord('u') and filter_mode == "mentions":
                    mentions_unread_only = not mentions_unread_only
                    items = self._build_list(filter_mode, guild_filter, mentions_unread_only)
                    selected = 0
                    scroll = 0

                elif k == ord('g'):
                    all_items = self._build_list(filter_mode, mentions_unread_only=mentions_unread_only)
                    guilds = _guilds_from_items(all_items)
                    if guilds:
                        guild_filter, guild_filter_name = self._pick_guild(
                            tui, guilds, guild_filter, guild_filter_name
                        )
                        items = self._build_list(filter_mode, guild_filter, mentions_unread_only)
                        selected = 0
                        scroll = 0

                elif k in (10, 13, curses.KEY_ENTER) and items:
                    item = items[selected]
                    if not item["channel_id"]:
                        continue
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

    def _pick_guild(self, tui, guilds, current_gid, current_name):
        """Guild picker overlay. Returns (guild_id, name) or (None, None) for all servers."""
        entries = [(None, None)] + guilds
        try:
            sel = next(i for i, (gid, _) in enumerate(entries) if gid == current_gid)
        except StopIteration:
            sel = 0
        scroll = 0

        def draw():
            title = " filter by server  j/k·move  Enter·pick  Esc·cancel "
            body = ["  all servers"] + [f"  {name}" for _, name in guilds]
            tui.extra_index = scroll
            tui.extra_selected = sel
            tui.draw_extra_window(title, body, select=True, reset_scroll=False)

        draw()
        while True:
            k = tui.screen.getch()

            if k == 27:
                return current_gid, current_name

            elif k in (ord('k'), curses.KEY_UP):
                if sel > 0:
                    sel -= 1
                    if scroll > sel:
                        scroll = sel
                draw()

            elif k in (ord('j'), curses.KEY_DOWN):
                if sel < len(entries) - 1:
                    sel += 1
                    if tui.win_extra_window:
                        h = tui.win_extra_window.getmaxyx()[0] - 1
                        if sel >= scroll + h:
                            scroll += 1
                draw()

            elif k in (10, 13, curses.KEY_ENTER):
                gid, name = entries[sel]
                return gid, name


# ── helpers ───────────────────────────────────────────────────────────────────

def _guilds_from_items(items):
    """Return sorted list of (guild_id, guild_name) pairs from a list of notification items."""
    seen = {}
    for item in items:
        gid = item.get("guild_id")
        if gid and gid not in seen:
            d = item["display"]
            start = d.find("[")
            end = d.find("]")
            name = d[start + 1:end] if 0 <= start < end else gid
            seen[gid] = name
    return sorted(seen.items(), key=lambda x: x[1].lower())
