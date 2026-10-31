#!/usr/bin/env python3

from gi.repository import GObject, Gio
from typing import Optional


# ⚠️ XX WIP...


class EndpointListRow(GObject.Object):
    __gtype_name__ = 'EndpointListRow'

    label = GObject.Property(type=str)

    children: Gio.ListStore | None = GObject.Property(
        type=Gio.ListStore  # of EndpointListRow
    )

    endpoint: dict | None = GObject.Property(type=object)

    def __init__(self, label, endpoint=None, has_children: bool = True):
        super().__init__()

        self.label = label
        self.children = (
            Gio.ListStore.new(EndpointListRow) if has_children else None
        )
        self.endpoint = endpoint
