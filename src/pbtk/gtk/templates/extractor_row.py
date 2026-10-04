#!/usr/bin/env
from pbtk.gtk.datamodel.extractor import (
    Extractor,
    ExtractorProgress,
    ExtractorInfoMessage,
    ExtractorOutputs,
    ExtractorInputs,
    ExtractorInputArgument,
)
from pbtk.gtk.workers.extractor_thread import ExtractorWorker
from pbtk.utils.common import assert_installed

from logging import debug

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gio, Adw
from pathlib import Path


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
                # https://lazka.github.io/pgi-docs/Gtk-4.0/classes/FileDialog.html#Gtk.FileDialog.open_multiple

                def file_picked(
                    dialog: Gtk.FileDialog, result: Gio.AsyncResult
                ):
                    files: Gio.ListModel = dialog.open_multiple_finish(result)
                    # ⚠️ TODO handle Dialog dismissal

                    inputs = ExtractorInputs()

                    for pos in range(files.get_n_items()):
                        file_item: Gio.File = files.get_item(pos)
                        file_path: str = file_item.get_path()
                        out_folder_name: str = Path(file_path).stem

                        inputs.inputs.append(
                            ExtractorInputArgument(file_path, out_folder_name)
                        )

                    # (⚠️ TODO show progress dialog - IN A SUBVIEW
                    # PAGE OR A POPUP?, prepare info dialog,
                    # RESULT SUBVIEW PAGE?)

                    # __progress subview show__ WIP
                    self.window.main_nav_view.push_by_tag('extracting_page')

                    self.window.extracting_status_page.set_title(
                        'Extracting...'
                    )
                    self.window.extracting_status_page.set_description('')

                    self.window.extracting_progress_bar.set_fraction(0.0)

                    worker = ExtractorWorker(self.extractor, inputs)
                    worker.progress.connect(self.on_progress)
                    worker.information.connect(self.on_information)
                    worker.finished.connect(self.on_finished)
                    worker.start()

                file_picker = Gtk.FileDialog()
                file_picker.open_multiple(self.window, callback=file_picked)

            else:
                XX

        # => 🪧 WIP: File picker branch
        #  => Use Gtk.FileDialog

        # => 🪧 TODO: URL prompt branch
        #  (cf. prompt_extractor @ gui.py § L61)

    def on_progress(
        self, worker: ExtractorWorker, progress: ExtractorProgress
    ):
        print('==> [ ⚠️ XX WIP 1 ]', progress.info, progress.progress)

    def on_information(
        self, worker: ExtractorWorker, information: ExtractorInfoMessage
    ):
        print('==> [ ⚠️ XX WIP 2 ]', information.info)

    def on_finished(self, worker: ExtractorWorker, outputs: ExtractorOutputs):
        print('==> [ ⚠️ XX WIP 3 ]', outputs.folders.get_n_items())
