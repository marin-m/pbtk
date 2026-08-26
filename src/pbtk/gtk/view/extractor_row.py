#!/usr/bin/env
from pbtk.gtk.datamodel.extractor import Extractor

from logging import debug

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw


class ExtractorRow(Adw.ActionRow):
    def __init__(self, data: Extractor):

        super().__init__()

        self.set_title(data.name)
        self.set_subtitle(data.description)

        select_button = Gtk.Button()
        select_button.set_label('Select...')

        select_button.connect('clicked', self.on_clicked)

        self.add_suffix(select_button)
        self.set_activatable_widget(select_button)

    def on_clicked(self, target: Gtk.Button, *args):
        debug('TODO')
