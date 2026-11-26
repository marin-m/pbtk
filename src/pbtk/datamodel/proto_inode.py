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

    file_path = GObject.Property(type=str)
    file_info = GObject.Property(type=Gio.FileInfo)
    file_obj = GObject.Property(type=Gio.File)

    is_directory = GObject.Property(type=bool, default=False)

    children_monitor = GObject.Property(type=Gtk.DirectoryList)

    # Maps a `Gtk.DirectoryList` into `MapListModel[ProtoInode]`
    wrapped_children: GObject.Property(type=Gtk.MapListModel) = None

    # See:
    # https://docs.gtk.org/gtk4/class.DirectoryList.html
    # https://docs.gtk.org/gio/class.FileInfo.html
    # https://docs.gtk.org/gtk4/class.MapListModel.html

    # https://lazka.github.io/pgi-docs/Gtk-4.0/classes/DirectoryList.html
    # https://lazka.github.io/pgi-docs/Gio-2.0/classes/FileInfo.html
    # https://lazka.github.io/pgi-docs/Gtk-4.0/classes/MapListModel.html
    # https://lazka.github.io/pgi-docs/Gtk-4.0/callbacks.html#Gtk.MapListModelMapFunc

    # https://lazka.github.io/pgi-docs/Gtk-4.0/classes/DirectoryList.html#Gtk.DirectoryList.props.monitored

    # The GFileInfos returned from a GtkDirectoryList have the
    # “standard::file” attribute set to the GFile they refer to.
    # This way you can get at the file that is referred to in
    # the same way you would via g_file_enumerator_get_child().

    @classmethod
    def from_path(cls, path: str):
        file_obj = Gio.File.new_for_path(path)
        file_info = file_obj.query_info(
            'standard::*', Gio.FileQueryInfoFlags.NONE, None
        )

        return cls.from_file_info(file_info, file_obj)

    @classmethod
    def from_file_info(
        cls, file_info: Gio.FileInfo, file_obj: Gio.File | None = None
    ):
        if not file_obj:
            file_obj = file_info.get_attribute_object('standard::file')

        self = cls()

        self.file_info = file_info
        self.file_obj = file_obj
        self.file_path = file_obj.get_path()

        self.label = file_info.get_name()

        file_type: Gio.FileType = file_info.get_file_type()

        self.is_directory = file_type == Gio.FileType.DIRECTORY

        if self.is_directory:
            self.children_monitor = Gtk.DirectoryList.new(
                'standard::*', self.file_obj
            )
            self.wrapped_children = Gtk.MapListModel.new(
                self.children_monitor, cls.from_file_info
            )

        return self
