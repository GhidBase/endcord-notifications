# Copyright (C) 2025-2026 Dylan Simon
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.

"""Notifications viewer: browse channels/DMs with mentions or unreads, navigate with j/k, Enter to switch."""

import curses
import logging

EXT_NAME = "Notifications Viewer"
EXT_VERSION = "0.1.0"
EXT_ENDCORD_VERSION = "1.4.2"
EXT_DESCRIPTION = "Press B (vim normal mode) to browse channels with mentions or unread messages."
EXT_SOURCE = "https://github.com/GhidBase/endcord-notifications"

logger = logging.getLogger(__name__)

_NOTIF_CODE = 1003
_TRIGGER = ord('B')
_FILTERS = ["mentions", "unreads", "dms"]


class Extension:
    def __init__(self, app):
        self.app = app
        self._filter_idx = 0
        logger.info("Notifications viewer active — press B in vim normal mode")

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

    def _build_list(self, filter_mode):
        app = self.app
        results = []
        for raw_idx, (code, meta) in enumerate(zip(app.tree_format, app.tree_metadata)):
            if meta is None:
                continue
            kind = code // 100
            if kind >= 10 or kind in (0, 1, 2):
                continue  # end markers, folders, dm/guild headers, categories
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

            channel_id = meta["id"]
            channel_name = meta["name"] or ""

            mention_count = ""
            read_state = app.read_state.get(channel_id, {})
            mentions = read_state.get("mentions", [])
            if mentions:
                mention_count = f" @{len(mentions)}"

            icon = "@" if is_mentioned else "•"

            if is_dm:
                display = f"{icon} {channel_name}{mention_count}"
            else:
                guild_id, _parent_id, guild_name = app.find_parents_from_tree(raw_idx)
                prefix = f"[{guild_name}] " if guild_name else ""
                display = f"{icon} {prefix}#{channel_name}{mention_count}"

            results.append({
                "display": display,
                "channel_id": channel_id,
            })
        return results

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

                if k == 27:  # Escape
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

                elif k in (ord('f'), 9):  # f or Tab to cycle filter
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
