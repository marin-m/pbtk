#!/usr/bin/env python3

from gi.repository import GObject, Gio
from typing import Optional

# Objects passed by GUI/CLI runtime to
# extractor routine:


class ExtractorInputArgument(GObject.Object):
    file_path_or_url: str
    output_folder_name: str


class ExtractorInputs(GObject.Object):
    inputs = GObject.Property(type=Gio.ListStore)  # of ExtractorInputArgument


# Objects returned by extractor routines to GUI/CLI
# through generators:


class ExtractorThreadMessage(GObject.Object):
    pass


class ExtractorOutputFile(ExtractorThreadMessage):
    name: str
    contents: str

    def __init__(self, name: str, contents: str):
        self.name = name
        self.contents = contents


class ExtractorInfoMessage(ExtractorThreadMessage):
    info: str

    def __init__(self, info: str):
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


class ExtractorOutputs(GObject.Object):
    folders = GObject.Property(type=Gio.ListStore)  # of ExtractorOutputFolder


# Info contained in decorators when creating an extractor:


class Extractor(GObject.Object):
    name = GObject.Property(type=str)
    description = GObject.Property(type=str)
    py_func: callable
    pick_url = GObject.Property(type=bool, default=False)
    depends: dict = None
