#!/usr/bin/env python3

from os import environ

# Disable the C++ extension for Python-Protobuf (for consistent behaviour) [1]
# [1] https://github.com/google/protobuf/blob/cf1418/python/google/protobuf/internal/api_implementation.py#L72

environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'

from traceback import format_exception
from argparse import ArgumentParser
from logging import debug, error
import sys

# Register resources
import pbtk.ui.gresource

from pbtk.ui.logging_central import LoggingCentral
from pbtk.ui.main_window import MainWindow

import gi

gi.require_version('Adw', '1')
gi.require_version('Gtk', '4.0')

from gi.repository import Adw, Gtk, Gdk, GLib


def main():
    args = ArgumentParser(
        description='A tool for reverse engineering Protobuf-based apps'
    )
    args = args.parse_args()

    GLib.set_prgname('re.fossplant.pbtk')

    app = MainApplication(application_id='re.fossplant.pbtk')
    app.run()


class MainApplication(Adw.Application):
    window: MainWindow = None
    logging_central: LoggingCentral

    def __init__(self, **kwargs):
        self.logging_central = LoggingCentral(debug_mode=True)

        self.setup_error_handling()

        # debug('Initializing app...')

        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icon_theme.add_resource_path('/re/fossplant/pbtk/')

        super().__init__(**kwargs)

        self.connect('startup', self.on_startup)
        self.connect('activate', self.on_activate)

    def setup_error_handling(self):
        # Generic error handler for non-bubbled exceptions raised in GLib callbacks
        # "This works because exception hooks are called in PyErr_Print."
        # Cf. https://gitlab.gnome.org/GNOME/pygobject/-/blob/3.48.2/tests/test_generictreemodel.py#L335

        def error_handler(exctype, value, traceback):
            tb_string = ''.join(
                format_exception(exctype, value, traceback)
            ).rstrip()

            error('Caught Python exception: \n' + tb_string)

            if self.window:
                dialog = Adw.AlertDialog.new(
                    '⚠️ Caught Python exception', tb_string
                )
                dialog.add_response('ok', 'Ok')
                dialog.choose(self.window, None, None)

        sys.excepthook = error_handler

    def on_startup(self, app, *args):
        self.window = MainWindow(self)

        # ^ ⚠️ ⚠️ TODO propagate logging.error errors to
        # main_window using a CUSTOM LOGGING HANDLER
        # when the GUI IS ENABLED?

        # Application will close once it has no longer has active
        # windows attached to it

        self.window.present()

    def on_activate(self, app):
        self.window.present()


if __name__ == '__main__':
    main()
