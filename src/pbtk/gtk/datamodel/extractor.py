#!/usr/bin/env python3

from collections.abc import Callable, Generator
from gi.repository import GObject, Gio
from typing import Optional

# Objects passed by GUI/CLI runtime to
# extractor routine:


class ExtractorInputArgument(GObject.Object):
    file_path_or_url: str
    output_folder_name: str

    def __init__(self, file_path_or_url: str, output_folder_name: str):
        self.file_path_or_url = file_path_or_url
        self.output_folder_name = output_folder_name


class ExtractorInputs(GObject.Object):
    inputs = GObject.Property(type=Gio.ListStore)  # of ExtractorInputArgument

    def __init__(self):
        self.inputs = Gio.ListStore.new(ExtractorInputArgument)


# Objects returned by extractor routines to GUI/CLI
# through generators:


class ExtractorThreadMessage(GObject.Object):
    pass


class ExtractorOutputFile(ExtractorThreadMessage):
    name: str
    contents: str

    def __init__(self, name: str, contents: str):
        super().__init__()

        self.name = name
        self.contents = contents


class ExtractorInfoMessage(ExtractorThreadMessage):
    info: str

    def __init__(self, info: str):
        super().__init__()

        self.info = info


class ExtractorProgress(ExtractorThreadMessage):
    info: str
    progress: Optional[float]

    def __init__(self, info: str, progress: Optional[float] = None):
        super().__init__()

        self.info = info
        self.progress = progress


# Objects passed by GUI/CLI extractor thread to
# GUI/CLI main thread through signals:


class ExtractorOutputFolder(GObject.Object):
    name: str
    files = GObject.Property(type=Gio.ListStore)  # of ExtractorOutputFile

    def __init__(self, name: str):
        super().__init__()

        self.name = name
        self.files = Gio.ListStore.new(ExtractorOutputFile)


class ExtractorOutputs(GObject.Object):
    folders = GObject.Property(type=Gio.ListStore)  # of ExtractorOutputFolder

    def __init__(self):
        super().__init__()

        self.folders = Gio.ListStore.new(ExtractorOutputFolder)


# Info contained in decorators when creating an extractor:


class Extractor(GObject.Object):
    name = GObject.Property(type=str)
    description = GObject.Property(type=str)
    py_func: Callable[[str], Generator[ExtractorThreadMessage]]
    pick_url = GObject.Property(type=bool, default=False)
    depends: dict = None
