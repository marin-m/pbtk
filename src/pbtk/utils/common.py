#!/usr/bin/env python3
from collections import OrderedDict, defaultdict
from collections.abc import Sequence, Iterable
from os.path import exists, dirname, realpath
from google.protobuf.message import Message
from importlib import import_module, reload
from tempfile import TemporaryDirectory
from inspect import getmembers, isclass
from logging import debug, error, info
from sys import platform, path as PATH
from os import environ, makedirs, sep
from importlib.util import find_spec
from argparse import ArgumentParser
from urllib.parse import urlparse
from platform import architecture
from subprocess import run, PIPE
from json import dump, load
from re import findall, sub
from pathlib import Path
from shutil import which
from typing import Dict

from pbtk.datamodel.transport import Transport, TransportDefinition
from pbtk.datamodel.extractor import (
    Extractor,
    ExtractorThreadMessage,
    ExtractorOutputFile,
    ExtractorErrorMessage,
    ExtractorInfoMessage,
    ExtractorProgress,
)

# Constructing paths - local data

if environ.get('FLATPAK_ID') and environ.get('XDG_DATA_HOME'):
    BASE_PATH = Path(environ['XDG_DATA_HOME'])
elif platform != 'win32':
    BASE_PATH = Path(environ['HOME']) / '.pbtk'
else:
    BASE_PATH = Path(environ['APPDATA']) / 'pbtk'
makedirs(str(BASE_PATH / 'protos'), exist_ok=True)
makedirs(str(BASE_PATH / 'endpoints'), exist_ok=True)

# Constructing paths - executables

external = Path(dirname(realpath(__file__))) / 'external'
arch = '64' * (architecture()[0] == '64bit')

protoc = str(
    external
    / 'protoc'
    / ('protoc' + {'win32': '.exe', 'darwin': '_osx'}.get(platform, arch))
)
dex2jar = str(
    external
    / 'dex2jar'
    / ('d2j-dex2jar.' + {'win32': 'bat'}.get(platform, 'sh'))
)
jad = str(
    external
    / 'jad'
    / ('jad' + {'win32': '.exe', 'darwin': '_osx'}.get(platform, ''))
)

# Disable the C++ extension for Python-Protobuf (for consistent behaviour) [1]
# [1] https://github.com/google/protobuf/blob/cf1418/python/google/protobuf/internal/api_implementation.py#L72

environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'

# Decorators for registering pluggable modules, documented at [2]
# [2] https://github.com/marin-m/pbtk#source-code-structure

extractors: Dict[str, Extractor] = OrderedDict()

"""
def register_extractor(name = None, # Used to refer to internally
                       readable_name = None, # Used to display in the UI
                       description = None, # Used to describe extractor in UI
                       pick_url = False, # Pick URL rather than file
                       depends = None): # kwargs for assert_installed()
"""


def register_extractor(
    name: str,  # Used to refer to internally
    readable_name: str,  # Used to display in the UI
    description: str,  # Used to describe extractor in UI
    pick_url=False,  # Pick URL rather than file
    depends=None,
):  # kwargs for assert_installed()

    def register_extractor_decorate(func):
        extractor_obj = Extractor()
        extractor_obj.name = readable_name
        extractor_obj.description = description
        extractor_obj.py_func = func
        extractor_obj.pick_url = pick_url
        extractor_obj.depends = depends

        extractors[name] = extractor_obj

        return func

    return register_extractor_decorate


transports: dict[str, TransportDefinition] = OrderedDict()


def register_transport(cls: Transport):
    transports[cls.name] = TransportDefinition(cls)
    return cls


# General utility functions


def assert_installed(modules=[], binaries=[]):
    missing = defaultdict(list)
    for items, what, func in (
        (modules, 'modules', find_spec),
        (binaries, 'binaries', which),
    ):
        for item in items:
            if not func(item):
                missing[what].append(item)
    if missing:
        msg = []
        for subject, names in missing.items():
            if len(names) == 1:
                subject = {'modules': 'module', 'binaries': 'binary'}[subject]
            msg.append('%s "%s"' % (subject, '", "'.join(names)))
        msg = 'You are missing the %s for this.' % ' and '.join(msg)
        raise ImportError(msg)


def insert_endpoint(base_path, obj):
    url = obj['request']['url']
    path = base_path / (urlparse(url).hostname + '.json')

    json = []
    if exists(str(path)):
        with open(str(path)) as fd:
            json = load(fd, object_pairs_hook=OrderedDict)

    # Try to merge objects
    inserted = False
    for obj2 in json:
        if obj2['request']['url'] == obj['request']['url'] and obj2[
            'request'
        ].get('pb_param') == obj['request'].get('pb_param'):
            # Try to merge data samples
            if 'samples' in obj2['request'] and 'samples' in obj['request']:
                if obj2['request']['transport'] == 'pburl_private':
                    new_samples = []
                    lite_samples = []

                    for i in obj2['request']['samples'] + obj['request'].pop(
                        'samples'
                    ):
                        # Simplify Protobuf-URL payloads
                        lite = {
                            k: sub(
                                r'(!\d+[^esz]|!\d+s(?=\d+|0x[a-f0-9]+:0x[a-f0-9]+(!|$)))[^!]+',
                                r'\1',
                                v,
                            )
                            if v.startswith('!')
                            else v
                            for k, v in i.items()
                        }
                        if lite not in lite_samples:
                            new_samples.append(i)
                        lite_samples.append(lite)

                    obj2['request']['samples'] = new_samples

                else:
                    for sample in obj['request'].pop('samples'):
                        if sample not in obj2['request']['samples']:
                            obj2['request']['samples'].append(sample)

            obj2['request'].update(obj['request'])
            if 'response' in obj:
                obj2['response'] = obj['response']
            inserted = True
            break

    if not inserted:
        json.append(obj)

    makedirs(str(path.parent), exist_ok=True)
    with open(str(path), 'w') as fd:
        dump(json, fd, ensure_ascii=False, indent=4)


# Turn a .proto input into Python classes.


class ProtoMessageDeclaration:
    name: str
    definition: Message

    def __init__(self, name, definition):
        self.name = name
        self.definition = definition


class ProtoFileDescription:
    definition: 'FileDescriptorSet'
    file_path: str

    def __init__(self, definition, file_path):
        self.definition = definition
        self.file_path = file_path


def load_proto_msgs(
    proto_path, ret_source_info=False
) -> Iterable[ProtoMessageDeclaration | ProtoFileDescription]:
    # List imports that we need to specify to protoc for the necessary *_pb2.py to be generated

    proto_dir = Path(proto_path).parent
    arg_proto_path = proto_dir
    arg_proto_files = []
    to_import = [str(proto_path)]

    while to_import:
        next_import = to_import.pop()
        while (
            not exists(str(arg_proto_path / next_import))
            and arg_proto_path.name
        ):
            arg_proto_path = arg_proto_path.parent
        next_import = str(arg_proto_path / next_import)

        if next_import not in arg_proto_files:
            arg_proto_files.insert(0, next_import)
            with open(next_import) as fd:
                to_import.extend(
                    reversed(
                        findall(
                            r'import(?:\s*weak|public)?\s*"(.+?)"\s*;',
                            fd.read(),
                        )
                    )
                )

    # Execute protoc and import the actual module from a tmp

    with TemporaryDirectory() as arg_python_out:
        args = [
            protoc,
            '--proto_path=%s' % arg_proto_path,
            '--python_out=' + arg_python_out,
            *arg_proto_files,
        ]
        if ret_source_info:
            args += [
                '-o%s' % (Path(arg_python_out) / 'desc_info'),
                '--include_source_info',
                '--include_imports',
            ]

        cmd = run(args, stderr=PIPE)
        if cmd.returncode:
            raise ValueError(cmd.stderr.decode('utf8'))

        if ret_source_info:
            from google.protobuf.descriptor_pb2 import FileDescriptorSet

            with open(str(Path(arg_python_out) / 'desc_info'), 'rb') as fd:
                yield ProtoFileDescription(
                    FileDescriptorSet.FromString(fd.read()), arg_proto_path
                )
                return

        # Do actual import

        module_name = (
            str(proto_dir)
            .replace(str(arg_proto_path), '')
            .strip('/\\')
            .replace(sep, '.')
        )
        if module_name:
            module_name += '.'
        module_name += Path(proto_path).stem.replace('-', '_') + '_pb2'

        PATH.append(arg_python_out)
        module = import_module(module_name)
        reload(module)
        PATH.remove(arg_python_out)

    # Recursively iterate over class members to list Protobuf messages

    yield from iterate_proto_msg(module, '')


def iterate_proto_msg(module, base):
    for name, cls in getmembers(module):
        if isclass(cls) and issubclass(cls, Message):
            yield ProtoMessageDeclaration(base + name, cls)
            yield from iterate_proto_msg(cls, base + name + '.')


# Routine for saving data returned by an extractor


def extractor_save(
    base_path: str, folder: str, outputs: Sequence[ExtractorThreadMessage]
):
    nb_written = 0
    name_to_path = {}
    wrote_endpoints = False

    # ⚠️ TODO make the output prettier
    for thread_msg in outputs:
        if isinstance(thread_msg, ExtractorOutputFile):
            if '.proto' in thread_msg.name:
                if folder:
                    path = base_path / 'protos' / folder / thread_msg.name
                else:
                    path = base_path / thread_msg.name

                makedirs(str(path.parent), exist_ok=True)
                with open(str(path), 'w') as fd:
                    fd.write(thread_msg.contents)

                if thread_msg.name not in name_to_path:
                    nb_written += 1
                name_to_path[thread_msg.name] = str(path)

            elif thread_msg.name.endswith('.sample'):
                endpoint = thread_msg.contents

                name = thread_msg.name.replace('.sample', '.proto')
                endpoint['proto_path'] = name_to_path[name]
                endpoint['proto_msg'] = name.replace('.proto', '')

                wrote_endpoints = True
                if folder:
                    insert_endpoint(
                        base_path / 'endpoints', {'request': endpoint}
                    )
                else:
                    insert_endpoint(base_path, {'request': endpoint})

            else:
                raise ValueError

        elif isinstance(thread_msg, ExtractorInfoMessage):
            info('[i] %s' % thread_msg.info)

        elif isinstance(thread_msg, ExtractorErrorMessage):
            error('[!] %s' % thread_msg.info)

        elif isinstance(thread_msg, ExtractorProgress):
            if thread_msg.progress is None:
                debug('[i] %s' % thread_msg.info)
            else:
                debug(
                    '[i] %s (%s %%)' % (thread_msg.info, thread_msg.progress)
                )

    return nb_written, wrote_endpoints


# CLI entry point when calling an extractor as an individual script


def extractor_main(extractor_name: str):
    extractor: Extractor = extractors[extractor_name]

    assert_installed(**(extractor.depends or {}))

    parser = ArgumentParser(description=extractor.description)
    if extractor.pick_url:
        parser.add_argument('input_', metavar='input_url')
    else:
        parser.add_argument('input_', metavar='input_file')
    parser.add_argument('output_dir', type=Path, default='.', nargs='?')
    args = parser.parse_args()

    nb_written, wrote_endpoints = extractor_save(
        args.output_dir, '', extractor.py_func(args.input_)
    )
    if nb_written:
        print(
            '\n[+] Wrote %s .proto files to "%s".\n'
            % (nb_written, args.output_dir)
        )
