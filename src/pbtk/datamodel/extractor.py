#!/usr/bin/env python3

from collections.abc import Callable, Generator
from gi.repository import GObject
from typing import Optional, List

# Objects passed by GUI/CLI runtime to
# extractor routine:


class ExtractorInputArgument(GObject.Object):
    file_path_or_url: str
    output_folder_name: str

    def __init__(self, file_path_or_url: str, output_folder_name: str):
        super().__init__()

        self.file_path_or_url = file_path_or_url
        self.output_folder_name = output_folder_name


class ExtractorInputs(GObject.Object):
    inputs: List[ExtractorInputArgument]

    def __init__(self):
        super().__init__()

        self.inputs = []


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


class ExtractorErrorMessage(ExtractorThreadMessage):
    info: str

    def __init__(self, info: str):
        super().__init__()

        self.info = info


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
    files: List[ExtractorOutputFile]

    def __init__(self, name: str):
        super().__init__()

        self.name = name
        self.files = []


class ExtractorOutputs(GObject.Object):
    folders: List[ExtractorOutputFolder]

    def __init__(self):
        super().__init__()

        self.folders = []


# Info contained in decorators when creating an extractor:


class Extractor(GObject.Object):
    name = GObject.Property(type=str)
    description = GObject.Property(type=str)
    py_func: Callable[[str], Generator[ExtractorThreadMessage]]
    pick_url = GObject.Property(type=bool, default=False)
    depends: dict = None
