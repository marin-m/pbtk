#!/usr/bin/env python3

from logging import (
    getLogger,
    StreamHandler,
    DEBUG,
    INFO,
    WARNING,
    ERROR,
    CRITICAL,
    Formatter,
    Logger,
)

from re import split, IGNORECASE
import sys


LOG_FORMAT = '[{asctime}] [ui {process}] - {levelname} - {message} ({pathname_last}:{lineno})'

# if '--service' in join(sys.argv).lower():
#     LOG_FORMAT = LOG_FORMAT.replace('ui ', 'service ')

BASE_FORMATTER = Formatter(fmt=LOG_FORMAT, style='{')


class NoColorFormatter(Formatter):
    def format(self, record):
        record.pathname_last = split(
            r'diagng/', record.pathname, flags=IGNORECASE
        ).pop()
        return BASE_FORMATTER.format(record)


class ColorFormatter(Formatter):
    CSI = '\x1b['
    grey = CSI + '38m'
    yellow = CSI + '33m'
    red = CSI + '31m'
    magenta = CSI + '35m'
    bold_red = CSI + '31;1m'
    reset = CSI + '0m'
    # format = "%(asctime)s - [pid %(process)s] - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"
    format = LOG_FORMAT

    FORMATS = {
        DEBUG: grey + format + reset,
        INFO: grey + format + reset,
        WARNING: yellow + format + reset,
        ERROR: magenta + format + reset,
        CRITICAL: red + format + reset,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        record.pathname_last = split(
            r'pbtk/', record.pathname, flags=IGNORECASE
        ).pop()
        formatter = Formatter(log_fmt, style='{')
        return formatter.format(record)


class LoggingCentral:
    logger: Logger

    def __init__(self, debug_mode: bool):
        self.logger = getLogger()
        self.logger.setLevel(DEBUG)

        stderr_handler = StreamHandler()
        stderr_handler.setLevel(DEBUG if debug_mode else INFO)
        if sys.stderr.isatty():
            stderr_handler.setFormatter(ColorFormatter())
        else:
            stderr_handler.setFormatter(NoColorFormatter())
        self.logger.addHandler(stderr_handler)
