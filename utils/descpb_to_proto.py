#!/usr/bin/python3
#-*- encoding: Utf-8 -*-
from google.protobuf.descriptor_pb2 import DescriptorProto, FieldDescriptorProto
from collections import OrderedDict
from itertools import groupby

"""
    This script converts back a FileDescriptor structure to a readable .proto file.
    
    There is already a function in the standard C++ library that does this [1], but
    - It is not accessible through the Python binding
    - This implementation has a few output readability improvements, i.e
    -- Declaring enums/messages after first use rather than at top of block
    -- Not always using full names when referencing messages types
    -- Smaller aesthetic differences (number of tabs, line jumps)
    
    For reference of the FileDescriptor structure, see [2].
    Other (less complete) implementations of this are [3] or [4].
    
    [1] https://github.com/google/protobuf/blob/5a76e/src/google/protobuf/descriptor.cc#L2242
    [2] https://github.com/google/protobuf/blob/bb77c/src/google/protobuf/descriptor.proto#L59
    
    [3] https://github.com/fry/d3/blob/master/decompile_protobins.py
    [4] https://github.com/sarum9in/bunsan_binlogs_python/blob/master/src/python/source.py
"""

INDENT = ' ' * 4

def descpb_to_proto(desc):
    out = 'syntax = "%s";\n\n' % (desc.syntax or 'proto2')

    scopes = ['']
    if desc.package:
        out += 'package %s;\n\n' % desc.package
        scopes[0] += '.' + desc.package
    
    for index, dep in enumerate(desc.dependency):
        prefix = ' public' * (index in desc.public_dependency)
        prefix += ' weak' * (index in desc.weak_dependency)
        out += 'import%s "%s";\n' % (prefix, dep)
        scopes.append('.' + ('/' + dep.rsplit('/', 1)[0])[1:].replace('/', '.'))
    
    out += '\n' * (out[-2] != '\n')
    
    out += parse_msg(desc, scopes, desc.syntax).strip('\n')
    name = desc.name.replace('..', '').strip('.\\/')
    
    return name, out + '\n'

def parse_msg(desc, scopes, syntax):
    out = ''
    is_msg = isinstance(desc, DescriptorProto)
    
    if is_msg:
        scopes = list(scopes)
        scopes[0] += '.' + desc.name
    
    blocks = OrderedDict()
    for nested_msg in (desc.nested_type if is_msg else desc.message_type):
        blocks[nested_msg.name] = parse_msg(nested_msg, scopes, syntax)
    
    for enum in desc.enum_type:
        out2 = ''
        for val in enum.value:
            out2 += '%s = %s;\n' % (val.name, fmt_value(val.number, val.options))
        
        if len(set(i.number for i in enum.value)) == len(enum.value):
            enum.options.ClearField('allow_alias')
        
        blocks[enum.name] = wrap_block('enum', out2, enum)
    
    if is_msg and desc.options.map_entry:
        return ' map<%s>' % ', '.join(min_name(i.type_name, scopes) \
            if i.type_name else types[i.type] \
                for i in desc.field)
    
    if is_msg:
        for field in desc.field:
            out += fmt_field(field, scopes, blocks, syntax)
        
        for index, oneof in enumerate(desc.oneof_decl):
            out += wrap_block('oneof', blocks.pop('_oneof_%d' % index), oneof)
        
        out += fmt_ranges('extensions', desc.extension_range)
        out += fmt_ranges('reserved', [*desc.reserved_range, *desc.reserved_name])
    
    else:
        for service in desc.service:
            out2 = ''
            for method in service.method:
                out2 += 'rpc %s(%s%s) returns (%s%s);\n' % (method.name,
                    'stream ' * method.client_streaming,
                    min_name(method.input_type, scopes),
                    'stream ' * method.server_streaming,
                    min_name(method.output_type, scopes))
            
            out += wrap_block('service', out2, service)
    
    extendees = OrderedDict()
    for ext in desc.extension:
        extendees.setdefault(ext.extendee, '')
        extendees[ext.extendee] += fmt_field(ext, scopes, blocks, syntax, True)
    
    for name, value in blocks.items():
        out += value[:-1]
    
    for name, fields in extendees.items():
        out += wrap_block('extend', fields, name=min_name(name, scopes))
    
    out = wrap_block('message' * is_msg, out, desc)
    return out

def fmt_value(val, options=None, desc=None, optarr=[]):
    if type(val) != str:
        if type(val) == bool:
            val = str(val).lower()
        elif desc and desc.enum_type:
            val = desc.enum_type.values_by_number[val].name
        val = str(val)
    else:
        val = '"%s"' % val.encode('unicode_escape').decode('utf8')
    
    if options:
        opts = [*optarr]
        for (option, value) in options.ListFields():
            opts.append('%s = %s' % (option.name, fmt_value(value, desc=option)))
        if opts:
            val += ' [%s]' % ', '.join(opts)
    return val

types = {v: k.split('_')[1].lower() for k, v in FieldDescriptorProto.Type.items()}
labels = {v: k.split('_')[1].lower() for k, v in FieldDescriptorProto.Label.items()}

def fmt_field(field, scopes, blocks, syntax, extend=False):
    type_ = types[field.type]
    
    default = ''
    if field.default_value:
        if field.type == field.TYPE_STRING:
            default = ['default = %s' % fmt_value(field.default_value)]
        elif field.type == field.TYPE_BYTES:
            default = ['default = "%s"' % field.default_value]
        else:
            # Guess whether it ought to be more readable as base 10 or 16,
            # based on the presence of repeated digits:
            
            if ('int' in type_ or 'fixed' in type_) and \
               int(field.default_value) >= 0x10000 and \
               not any(len(list(i)) > 3 for _, i in groupby(str(field.default_value))):
                
                field.default_value = hex(int(field.default_value))
            
            default = ['default = %s' % field.default_value]
    
    out = ''
    if field.type_name:
        type_ = min_name(field.type_name, scopes)
        short_type = type_.split('.')[-1]
        
        if short_type in blocks and ((not extend and not field.HasField('oneof_index')) or \
                                      blocks[short_type].startswith(' map<')):
            out += blocks.pop(short_type)[1:]
    
    if out.startswith('map<'):
        line = out + ' %s = %s;\n' % (field.name, fmt_value(field.number, field.options, optarr=default))
        out = ''
    elif field.type != field.TYPE_GROUP:
        line = '%s %s %s = %s;\n' % (labels[field.label], type_, field.name, fmt_value(field.number, field.options, optarr=default))
    else:
        line = '%s group %s = %d ' % (labels[field.label], type_, field.number)
        out = out.split(' ', 2)[-1]
    
    if field.HasField('oneof_index') or (syntax == 'proto3' and line.startswith('optional')):
        line = line.split(' ', 1)[-1]
    if out:
        line = '\n' + line
    
    if field.HasField('oneof_index'):
        blocks.setdefault('_oneof_%d' % field.oneof_index, '')
        blocks['_oneof_%d' % field.oneof_index] += line + out
        return ''
    else:
        return line + out

"""
    Find the smallest name to refer to another message from our scopes.
    
    For this, we take the final part of its name, and expand it until
    the path both scopes don't have in common (if any) is specified; and
    expand it again if there are multiple outer packages/messages in the
    scopes sharing the same name, and that the first part of the obtained
    partial name is one of them, leading to ambiguity.
"""

def min_name(name, scopes):
    name, cur_scope = name.split('.'), scopes[0].split('.')
    short_name = [name.pop()]
    
    while name and (cur_scope[:len(name)] != name or \
                    any(list_rfind(scope.split('.'), short_name[0]) > len(name) \
                        for scope in scopes)):
        short_name.insert(0, name.pop())
    
    return '.'.join(short_name)

def wrap_block(type_, value, desc=None, name=None):
    out = ''
    if type_:
        out = '\n%s %s {\n' % (type_, name or desc.name)
    
    if desc:
        for (option, optval) in desc.options.ListFields():
            value = 'option %s = %s;\n' % (option.name, fmt_value(optval, desc=option)) + value
    
    value = value.replace('\n\n\n', '\n\n')
    if type_:
        out += '\n'.join(INDENT + line for line in value.strip('\n').split('\n'))
        out += '\n}\n\n'
    else:
        out += value
    return out

def fmt_ranges(name, ranges):
    text = []
    for range_ in ranges:
        if type(range_) != str and range_.end - 1 > range_.start:
            if range_.end < 0x20000000:
                text.append('%d to %d' % (range_.start, range_.end - 1))
            else:
                text.append('%d to max' % range_.start)
        elif type(range_) != str:
            text.append(fmt_value(range_.start))
        else:
            text.append(fmt_value(range_))
    if text:
        return '\n%s %s;\n' % (name, ', '.join(text))
    return ''


# Fulfilling a blatant lack of the Python language.
list_rfind = lambda x, i: len(x) - 1 - x[::-1].index(i) if i in x else -1
