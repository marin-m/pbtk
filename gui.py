#!/usr/bin/env python3
# -*- encoding: Utf-8 -*-

from os.path import dirname, realpath, join
import sys

ROOT_DIR = dirname(realpath(__file__))
SRC_DIR = join(ROOT_DIR, 'src')
sys.path.insert(0, SRC_DIR)

from pbtk.ui.gui import PBTKGUI

PBTKGUI()
