# Copyright (C) 2025-2026 Dylan Simon
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.

"""Notifications viewer: browse mentions, navigate with j/k, Enter to switch."""

import curses
import logging

EXT_NAME = "Notifications Viewer"
EXT_VERSION = "0.6.0"
EXT_ENDCORD_VERSION = "1.4.2"
EXT_DESCRIPTION = "Press B (vim normal mode) to browse mentions. u=all  g=server  Enter=go."
EXT_SOURCE = "https://github.com/GhidBase/endcord-notifications"

logger = logging.getLogger(__name__)

_NOTIF_CODE = 1003
_TRIGGER = ord('B')
_MENTIONS_FETCH = 50


class Extension:
    def __init__(self, app):
        self.app = app
        logger.info("Notifications viewer active — press B in vim normal mode")

    # ── list building ─────────────────────────────────────────────────────────

    def _build_list(self, show_all, guild_filter=None):
        results = self._build_all_list() if show_all else self._build_unread_list()
        if guild_filter is not None:
            results = [r for r in results if r.get("guild_id") == guild_filter]
        return results

    def _build_unread_list(self):
        """Currently mentioned channels from the sidebar tree."""
        app = self.app
        results = []
        for raw_idx, (code, meta) in enumerate(zip(app.tree_format, app.tree_metadata)):
            if meta is None:
                continue
            kind = code // 100
            if kind >= 10 or kind in (0, 1, 2):
                continue
            if (code // 10) % 10 not in (2, 5):
                continue

            guild_id, _parent_id, guild_name = app.find_parents_from_tree(raw_idx)
            is_dm = meta["type"] in (1, 3)
            channel_name = meta["name"] or ""
            channel_id = str(meta["id"])

            read_state = app.read_state.get(channel_id) or app.read_state.get(meta["id"], {})
            mention_ids = read_state.get("mentions", [])
            count_tag = f" @{len(mention_ids)}" if mention_ids else ""

            if is_dm:
                display = f"@ {channel_name}{count_tag}"
            else:
                prefix = f"[{guild_name}] " if guild_name else ""
                display = f"@ {prefix}#{channel_name}{count_tag}"

            results.append({
                "display": display,
                "channel_id": channel_id,
                "guild_id": str(guild_id) if guild_id else None,
                "message_id": str(mention_ids[-1]) if mention_ids else None,
            })
        return results

    def _build_all_list(self):
        """All recent mentions from the Discord API."""
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
                "message_id": str(m["id"]),
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
        show_all = False
        guild_filter = None
        guild_filter_name = None
        items = self._build_list(show_all)
        selected = 0
        scroll = 0

        def draw():
            mode_tag = "all" if show_all else "mentions"
            server_tag = f"|{guild_filter_name}" if guild_filter_name else ""
            title = f" Notifications [{mode_tag}{server_tag}]  j/k·move  u·{'unread' if show_all else 'all'}  g·server  Enter·go  Esc·close "
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

                elif k == ord('u'):
                    show_all = not show_all
                    items = self._build_list(show_all, guild_filter)
                    selected = 0
                    scroll = 0

                elif k == ord('g'):
                    guilds = _guilds_from_items(self._build_list(show_all))
                    if guilds:
                        guild_filter, guild_filter_name = self._pick_guild(
                            tui, guilds, guild_filter, guild_filter_name
                        )
                        items = self._build_list(show_all, guild_filter)
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
                        if item.get("message_id"):
                            app.go_to_message(item["message_id"])
                        app.reset_states(replying=True)
                        app.update_status_line()
                    return

                draw()
        finally:
            tui.screen.timeout(200)
            tui.remove_extra_window()

    def _pick_guild(self, tui, guilds, current_gid, current_name):
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
    seen = {}
    for item in items:
        gid = item.get("guild_id")
        if gid and gid not in seen:
            d = item["display"]
            start, end = d.find("["), d.find("]")
            seen[gid] = d[start + 1:end] if 0 <= start < end else gid
    return sorted(seen.items(), key=lambda x: x[1].lower())
