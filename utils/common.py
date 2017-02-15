#!/usr/bin/python3
#-*- encoding: Utf-8 -*-
from google.protobuf.message import Message
from tempfile import TemporaryDirectory
from inspect import getmembers, isclass
from os import environ, name, makedirs
from importlib.util import find_spec
from importlib import import_module
from argparse import ArgumentParser
from urllib.parse import urlparse
from subprocess import run, PIPE
from sys import path as PATH
from json import dump, load
from re import findall, sub
from os.path import exists
from pathlib import Path
from shutil import which

if name != 'nt':
    BASE_PATH = Path(environ['HOME']) / '.pbtk'
else:
    BASE_PATH = Path(environ['APPDATA']) / 'pbtk'
makedirs(BASE_PATH / 'protos', exist_ok=True)
makedirs(BASE_PATH / 'endpoints', exist_ok=True)

extractors = {}
"""
def register_extractor(name = None, # Used to refer to internally
                       desc = None, # Used to describe extractor in GUI
                       pick_url = False, # Pick URL rather than file
                       depends = None): # kwargs for assert_installed()
"""
def register_extractor(**kwargs):
    def register_extractor_decorate(func):
        extractors[kwargs['name']] = {'func': func, **kwargs}
        return func
    return register_extractor_decorate

transports = {}
"""
def register_transport(name, # Used to refer to in JSON data files
                       desc, # Used to describe protocol in GUI
                       ui_tab = None, # Used to name the protocol data tab in fuzzer GUI (if any)
                       ui_data_form = None, # Used to describe the nature of protocol data
                       enforce_int_parameter = False): # Whether keys in protocol data are integer
"""
def register_transport(**kwargs):
    def register_transport_decorate(func):
        transports[kwargs['name']] = {'func': func, **kwargs}
        return func
    return register_transport_decorate

def assert_installed(win=None, modules=[], binaries=[]):
    missing = {'modules': [], 'binaries': []}
    for items, what, func in ((modules, 'modules', find_spec),
                              (binaries, 'binaries', which)):
        for item in items:
            if not func(item):
                missing[what].append(item)
    wrong = bool(missing['binaries'] or missing['modules'])
    if wrong:
        msg = []
        for what in ('binaries', 'modules'):
            if missing[what]:
                msg.append('%s "%s"' % (what, '", "'.join(missing[what])))
        msg = 'You are missing the %s for this.' % ' and '.join(msg)
        if win:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(win, ' ', msg)
        else:
            raise ImportError(msg)
    return not wrong

def insert_endpoint(base_path, obj):
    url = obj['request']['url']
    path = base_path / (urlparse(url).netloc + '.json')
    
    json = []
    if exists(path):
        with open(path) as fd:
            json = load(fd)
    
    # Try to merge objects
    inserted = False
    for obj2 in json:
        if obj2['request']['url'] == obj['request']['url'] and \
           obj2['request'].get('pb_param') == obj['request'].get('pb_param'):
            
            # Try to merge data samples
            if 'samples' in obj2['request'] and 'samples' in obj['request']:
                
                if obj2['request']['transport'] == 'pburl_private':
                    new_samples = []
                    lite_samples = []
                    for i in obj2['request']['samples'] + obj['request'].pop('samples'):
                        # Simplify Protobuf-URL payloads
                        lite = {k: sub('(!\d+[^esz]|!\d+s(?=\d+|0x[a-f0-9]+:0x[a-f0-9]+(!|$)))[^!]+', r'\1', v)
                                if v.startswith('!') else v
                                for k, v in i.items()}
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
    
    makedirs(path.parent, exist_ok=True)
    with open(path, 'w') as fd:
        dump(json, fd, ensure_ascii=False, indent=4)

# Turn a .proto input into Python classes

def load_proto_msgs(proto_path):
    # List imports that we need to specify to protoc for the necessary *_pb2.py to be generated
    
    proto_dir = Path(proto_path).parent
    arg_proto_path = proto_dir
    arg_proto_files = []
    to_import = [str(proto_path)]
    
    while to_import:
        next_import = to_import.pop()
        while not exists(arg_proto_path / next_import) and \
              str(arg_proto_path.parent).startswith(str(BASE_PATH)):
            arg_proto_path = arg_proto_path.parent
        next_import = str(arg_proto_path / next_import)
        
        if next_import not in arg_proto_files:
            arg_proto_files.insert(0, next_import)
            with open(next_import) as fd:
                for prior_import in reversed(findall('import(?:\s*weak|public)?\s*"(.+?)"\s*;', fd.read())):
                    to_import.append(prior_import)
    
    # Execute protoc and import the actual module from a tmp
    
    with TemporaryDirectory() as arg_python_out:
        cmd = run(['protoc', '--proto_path=%s' % arg_proto_path, '--python_out=' + arg_python_out, *arg_proto_files], stderr=PIPE, encoding='utf8')
        if cmd.returncode:
            raise ValueError(cmd.stderr)
        
        module_name = str(proto_dir).replace(str(arg_proto_path), '').strip('/\\').replace('/', '.')
        if module_name:
            module_name += '.'
        module_name += Path(proto_path).stem.replace('-', '_') + '_pb2'

        PATH.append(arg_python_out)
        module = import_module(module_name)
        PATH.remove(arg_python_out)
    
    # Recursively iterate over class members to list Protobuf messages

    yield from iterate_proto_msg(module, '')

def iterate_proto_msg(module, base):
    for name, cls in getmembers(module):
        if isclass(cls) and issubclass(cls, Message):
            yield base + name, cls
            yield from iterate_proto_msg(cls, base + name + '.')

# Routine for saving data returned by an extractor

def extractor_save(base_path, folder, outputs):
    nb_written = 0
    name_to_path = {}
    wrote_endpoints = False
    
    for name, contents in outputs:
        if '.proto' in name:
            if folder:
                path = base_path / 'protos' / folder / name
            else:
                path = base_path / name
            
            makedirs(path.parent, exist_ok=True)
            with open(path, 'w') as fd:
                fd.write(contents)
            
            if name not in name_to_path:
                nb_written += 1
            name_to_path[name] = str(path)
        
        elif name.endswith('.sample'):
            endpoint = contents
            
            name = name.replace('.sample', '.proto')
            endpoint['proto_path'] = name_to_path[name]
            endpoint['proto_msg'] = name.replace('.proto', '')
            
            wrote_endpoints = True
            if folder:
                insert_endpoint(base_path / 'endpoints', {'request': endpoint})
            else:
                insert_endpoint(base_path, {'request': endpoint})
    
    return nb_written, wrote_endpoints

# CLI entry point when calling an extractor as an individual script

def extractor_main(extractor):
    extractor = extractors[extractor]
    
    if assert_installed(**extractor.get('depends', {})):
        parser = ArgumentParser(description=extractor['desc'])
        if extractor.get('pick_url'):
            parser.add_argument('input_', metavar='input_url')
        else:
            parser.add_argument('input_', metavar='input_file')
        parser.add_argument('output_dir', type=Path, default='.', nargs='?')
        args = parser.parse_args()
        
        nb_written, wrote_endpoints = extractor_save(args.output_dir, '', extractor['func'](args.input_))
        if nb_written:
            print('\n[+] Wrote %s .proto files to "%s".\n' % (nb_written, args.output_dir))
