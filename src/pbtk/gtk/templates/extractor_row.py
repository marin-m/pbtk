#!/usr/bin/env
from pbtk.gtk.datamodel.extractor import Extractor
from pbtk.utils.common import assert_installed

from logging import debug

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw


class ExtractorRow(Adw.ActionRow):
    extractor: Extractor
    window: Adw.ApplicationWindow

    def __init__(self, data: Extractor, window: Adw.ApplicationWindow):

        super().__init__()

        self.window = window
        self.extractor = data

        self.set_title(data.name)
        self.set_subtitle(data.description)

        select_button = Gtk.Image.new_from_icon_name('go-next-symbolic')

        self.set_activatable(True)
        self.connect('activated', self.on_clicked)
        self.add_suffix(select_button)

    def on_clicked(self, target: Gtk.Button, *args):
        debug('TODO')

        try:
            assert_installed(**(self.extractor.depends or {}))
        except ImportError as err:
            dialog = Adw.AlertDialog.new(err.msg)
            dialog.add_response('ok', 'Ok')
            dialog.choose(self.window, None, None)

        else:
            if not self.extractor.pick_url:
                # WIP: see
                # https://lazka.github.io/pgi-docs/Gtk-4.0/classes/FileDialog.html#Gtk.FileDialog.open_multiple

                def file_picked(XX, XY):
                    XZ

                file_picker = Gtk.FileDialog()
                file_picker.open_multiple(self.window, callback=file_picked)

            else:
                XX

        # => 🪧 TODO: File picker branch
        #  => Use Gtk.FileDialog

        # => 🪧 TODO: URL prompt branch
        #  (cf. prompt_extractor @ gui.py § L61)
