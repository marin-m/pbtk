#!/usr/bin/env python3

from gi.repository import GObject, GLib
from threading import Thread

from pbtk.gtk.datamodel.extractor import (
    Extractor,
    ExtractorInputs,
    ExtractorOutputs,
    ExtractorOutputFolder,
    ExtractorOutputFile,
    ExtractorInfoMessage,
    ExtractorProgress,
)


class ExtractorWorker(GObject.Object):
    # Cf. https://pygobject.gnome.org/guide/api/signals.html#gi.repository.GObject.Signal
    extractor: Extractor
    inputs: ExtractorInputs

    def __init__(self, extractor: Extractor, inputs: ExtractorInputs):
        super().__init__()

        self.extractor = extractor
        self.inputs = inputs

    def start(self):
        thread = ExtractorThread(self, self.extractor, self.inputs)
        thread.daemon = True
        thread.start()

    @GObject.Signal(arg_types=(object,))
    def finished(self, output: ExtractorOutputs):
        pass

    @GObject.Signal(arg_types=(object,))
    def information(self, message: ExtractorInfoMessage):
        pass

    @GObject.Signal(arg_types=(object,))
    def progress(self, progress: ExtractorProgress):
        pass


class ExtractorThread(Thread):
    worker: ExtractorWorker
    extractor: Extractor
    inputs: ExtractorInputs

    def __init__(
        self,
        worker: ExtractorWorker,
        extractor: Extractor,
        inputs: ExtractorInputs,
    ):
        super().__init__()

        self.worker = worker
        self.extractor = extractor
        self.inputs = inputs

    def run(self):
        outputs = ExtractorOutputs()
        for input_pos in range(self.inputs.inputs.get_n_items()):
            input_item = self.inputs.inputs.get_item(input_pos)

            output_folder = ExtractorOutputFolder(
                input_item.output_folder_name
            )

            # Extractor is ran here
            for thread_msg in self.extractor.py_func(
                input_item.file_path_or_url
            ):
                if isinstance(thread_msg, ExtractorOutputFile):
                    output_folder.files.append(thread_msg)

                elif isinstance(thread_msg, ExtractorInfoMessage):
                    GLib.idle_add(self.worker.information.emit, thread_msg)

                elif isinstance(thread_msg, ExtractorProgress):
                    GLib.idle_add(self.worker.progress.emit, thread_msg)

                else:
                    raise ValueError

            outputs.folders.append(output_folder)

        GLib.idle_add(self.worker.finished.emit, outputs)
