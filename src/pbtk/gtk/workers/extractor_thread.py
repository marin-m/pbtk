#!/usr/bin/env python3

from gi.repository import GObject
from threading import Thread

from pbtk.gtk.datamodel.extractor import (
    Extractor,
    ExtractorInputs,
    ExtractorOutputs,
    ExtractorInfoMessage,
    ExtractorProgress,
)


class ExtractorThread(Thread):
    extractor: Extractor
    inputs: ExtractorInputs

    def __init__(self, extractor: Extractor, inputs: ExtractorInputs):
        super().__init__()

        self.extractor = extractor
        self.inputs = inputs

    def run():
        pass  # ⚠️ TODO - see "class Worker(QThread)" in gui.py and
        # "ExtractorThreadMessage" in our new data model


class ExtractorWorker(GObject.Object):
    # ⚠️ 🚧 TODO REDEFINE SIGNALS HERE
    # Cf. https://pygobject.gnome.org/guide/api/signals.html#gi.repository.GObject.Signal

    thread: ExtractorThread

    def __init__(self, extractor: Extractor):
        super().__init__()

        self.thread = ExtractorThread(extractor)
        self.thread.start()

    @GObject.Signal(arg_types=(object,))
    def finished(self, output: ExtractorOutputs):
        pass

    @GObject.Signal(arg_types=(object,))
    def information(self, message: ExtractorInfoMessage):
        pass

    @GObject.Signal(arg_types=(object,))
    def progress(self, progress: ExtractorProgress):
        pass


"""

# 🚧 ⚠️ 🪧 ORIGINAL CODE:


class Worker(QThread):
    finished = Signal(object)
    information = Signal(object)
    progress = Signal(object, object)

    def __init__(self, inputs, extractor):
        super().__init__()
        self.inputs = inputs
        self.extractor = extractor

    def run(self):
        output = defaultdict(list)
        for input_, folder in self.inputs:
            # Extractor is runned here
            for name, contents in self.extractor['func'](input_):
                if name == '_progress':
                    self.progress.emit(*contents)
                elif name == '_info':
                    self.information.emit(contents)
                else:
                    output[folder].append((name, contents))

        self.finished.emit(output)

"""
