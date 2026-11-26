#!/usr/bin/env python3
from typing import Self

import gi

gi.require_version('Gtk', '4.0')

from gi.repository import GObject, Gio, Gtk

# 🪧 ROOT OF THE TREELISTMODEL WILL POINT
# TO PROTOINODE(ROOT_PROTO_DIR).CHILDREN


class ProtoInode(GObject.Object):
    __gtype_name__ = 'ProtoInode'

    label = GObject.Property(type=str)

    is_directory = GObject.Property(type=bool)

    file_path = GObject.Property(type=str)
    file_info = GObject.Property(type=Gio.FileInfo)

    children_monitor: Gtk.DirectoryList
    wrapped_children: Gtk.MapListModel[Self, Gtk.DirectoryList]

    # ⚠️ WIP: See
    # https://docs.gtk.org/gtk4/class.DirectoryList.html
    # https://docs.gtk.org/gio/class.FileInfo.html
    # https://docs.gtk.org/gtk4/class.MapListModel.html

    # https://lazka.github.io/pgi-docs/Gtk-4.0/classes/DirectoryList.html
    # https://lazka.github.io/pgi-docs/Gio-2.0/classes/FileInfo.html
    # https://lazka.github.io/pgi-docs/Gtk-4.0/classes/MapListModel.html
    # https://lazka.github.io/pgi-docs/Gtk-4.0/callbacks.html#Gtk.MapListModelMapFunc

    @classmethod
    def from_path(cls):
        XX

    @classmethod
    def from_file_info(cls):
        XX

    def get_children(self):
        XX
