#!/usr/bin/env
from pbtk.gtk.datamodel.extractor import (
    Extractor,
    ExtractorProgress,
    ExtractorErrorMessage,
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
from os.path import join
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

                    self.window.extracting_status_page.set_paintable(
                        self.window.extraction_spinner
                    )
                    self.window.extracting_status_page.set_title(
                        'Extracting...'
                    )
                    self.window.extracting_status_page.set_description('')

                    self.window.extracting_progress_bar.set_fraction(0.0)

                    self.window.extraction_text_view.set_visible(False)
                    self.window.extraction_text_buffer.set_text('')

                    self.window.extraction_next_steps.set_visible(False)

                    worker = ExtractorWorker(self.extractor, inputs)
                    worker.progress.connect(self.on_progress)
                    worker.information.connect(self.on_information)
                    worker.error.connect(self.on_error)
                    worker.finished.connect(self.on_finished)
                    worker.start()

                    # ⚠️ ⚠️ TODO: 🪧 Cancel the extraction process when QUITTING THE VIEW
                    #  OR THE WINDOW?

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

        self.window.extracting_status_page.set_description(progress.info)
        self.window.extracting_progress_bar.set_fraction(
            progress.progress or 0.0
        )

    def on_information(
        self, worker: ExtractorWorker, information: ExtractorInfoMessage
    ):
        print('==> [ ⚠️ XX WIP 2 ]', information.info)

        # ⚠️ TODO display a pop-up?

        dialog = Adw.AlertDialog.new('Information', information.info)
        dialog.add_response('ok', 'Ok')
        dialog.choose(self.window, None, None)

        self.window.extraction_text_view.set_visible(True)
        self.window.extraction_text_buffer.insert(
            self.window.extraction_text_buffer.get_end_iter(),
            information.info + '\n\n' + '=' * 24 + '\n\n',
        )

    def on_error(
        self, worker: ExtractorWorker, information: ExtractorErrorMessage
    ):
        print('==> [ ⚠️ XX WIP 3 ]', information.info)

        # ⚠️ TODO display the text-view?

        self.window.extraction_text_view.set_visible(True)
        self.window.extraction_text_buffer.insert(
            self.window.extraction_text_buffer.get_end_iter(),
            information.info + '\n\n' + '=' * 24 + '\n\n',
        )

    def on_finished(self, worker: ExtractorWorker, outputs: ExtractorOutputs):
        print('==> [ ⚠️ XX WIP 4 ]', outputs.folders.get_n_items())

        # ⚠️ TODO either switch view or display a pop-up?

        num_files_out = 0
        for num_folder in range(outputs.folders.get_n_items()):
            folder_item = outputs.folders.get_item(num_folder)

            num_files_out += folder_item.files.get_n_items()

            for num_file in range(folder_item.files.get_n_items()):
                file_item = folder_item.files.get_item(num_file)

                self.window.extraction_text_view.set_visible(True)
                self.window.extraction_text_buffer.insert(
                    self.window.extraction_text_buffer.get_end_iter(),
                    'Successfully extracted: %s\n'
                    % join(folder_item.name, file_item.name),
                )

        # dialog = Adw.AlertDialog.new(
        #     'Information', 'Task done, %d files were saved' % num_files_out
        # )
        # dialog.add_response('ok', 'Ok')
        # dialog.choose(self.window, None, None)

        self.window.present()
        self.window.extracting_status_page.set_paintable(None)
        self.window.extracting_status_page.set_title('Extraction done')
        self.window.extracting_status_page.set_description(
            '%d .proto files have been extracted' % num_files_out
        )
        self.window.extracting_progress_bar.set_fraction(1.0)

        self.window.extraction_next_steps.set_visible(True)
