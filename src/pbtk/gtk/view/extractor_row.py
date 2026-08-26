#!/usr/bin/env
from pbtk.gtk.datamodel.extractor import Extractor

import gi

gi.require_version('Adw', '1')

from gi.repository import Adw


class ExtractorRow(Adw.ActionRow):
    def __init__(self, data: Extractor):

        super().__init__()

        self.set_title(data.name)
        self.set_subtitle(data.description)
