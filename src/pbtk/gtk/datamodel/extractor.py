#!/usr/bin/env python3

from gi.repository import GObject


class Extractor(GObject.Object):
    name = GObject.Property(type=str)
    description = GObject.Property(type=str)
    py_func: callable
