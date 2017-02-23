#!/usr/bin/python3
#-*- encoding: Utf-8 -*-
from google.protobuf.descriptor_pb2 import FileDescriptorProto, DescriptorProto
from collections import defaultdict, OrderedDict
from re import sub

from utils.descpb_to_proto import descpb_to_proto

"""
    When parsing output from e.g. the Java extractor, messages aren't
    nested and you need to nest them back between them.
    
    We nest only messages that are in the same package, and have only
    one reference into it. Except if this leads to disallowed patterns,
    such as mutually importing files, in this case more will be done.
    
    Also, ensure every message starts by an uppercase letter. Once this
    is done, render the .proto files to ASCII using the existing module.
"""

def nest_and_print_to_files(msg_path_to_obj, msg_to_referrers):
    msg_to_topmost = OrderedDict()
    msg_to_newloc = {}
    newloc_to_msg = {}
    msg_to_imports = defaultdict(list)

    # Iterate over referred to messages/groups/enums.
    
    for msg, referrers in dict(msg_to_referrers).items():
        # Suppress references to unknown messages caused by
        # decompilation failures.
        if msg not in msg_path_to_obj:
            del msg_to_referrers[msg]
            for field, referrer, _ in referrers:
                field = next((i for i in msg_path_to_obj[referrer].field if i.name == field), None)
                
                field.ClearField('type_name')
                field.type = field.TYPE_BYTES
        else:
            for _, referrer, _ in referrers:
                msg_to_imports[referrer].append(msg)
    
    # Merge groups first:
    msg_to_referrers = OrderedDict(sorted(msg_to_referrers.items(), key=lambda x: -x[1][0][2]))
    
    mergeable = OrderedDict()
    enumfield_to_enums = defaultdict(set)
    enum_to_dupfields = defaultdict(set)
    
    for msg, referrers in msg_to_referrers.items():
        msg_pkg = get_pkg(msg)

        first_field = referrers[0]
        field, referrer, is_group = first_field

        # Check whether message/enum has exactly one referrer, and
        # whether it's in the same package.
        if not is_group:
            in_pkg = [(field, referrer) for field, referrer, _ in referrers \
                      if (get_pkg(referrer) == msg_pkg or not msg_pkg) \
                      and msg_to_topmost.get(referrer, referrer) != msg \
                      and not msg_path_to_obj[referrer].options.map_entry \
                      # If it's a subclass, parent must be the same
                      and ('$' not in msg or msg.split('.')[-1].split('$')[0] == \
                                        referrer.split('.')[-1].split('$')[0])]
            
            if len({i[1] for i in referrers}) != 1 or not in_pkg:
                # It doesn't. Keep for the next step
                if in_pkg:
                    mergeable[msg] = in_pkg
                continue
            
            field, referrer = in_pkg[0]
        
        else:
            assert len(referrers) == 1
        
        merge_and_rename(msg, referrer, msg_pkg, is_group,
            msg_to_referrers, msg_to_topmost, msg_to_newloc, msg_to_imports, msg_path_to_obj, newloc_to_msg)

    for msg, referrers in msg_to_referrers.items():
        msg_pkg = get_pkg(msg_to_newloc.get(msg, msg))
        msg_obj = msg_path_to_obj[msg]

        # Check for duplicate enum fields in the same package.
        if not isinstance(msg_obj, DescriptorProto):
            for enum_field in msg_obj.value:
                name = msg_pkg + '.' + enum_field.name
                enumfield_to_enums[name].add(msg)
                
                if len(enumfield_to_enums[name]) > 1:
                    for other_enum in enumfield_to_enums[name]:
                        enum_to_dupfields[other_enum].add(name)

    # Try to fix recursive (mutual) imports, and conflicting enum field names.
    still_to_merge = bool(mergeable)
    
    while still_to_merge:
        still_to_merge = False
        
        for msg, in_pkg in OrderedDict(mergeable).items():
            duplicate_enumfields = enum_to_dupfields.get(msg, set())

            for field, referrer in sorted(in_pkg, key=lambda x: msg_to_newloc.get(x[1], x[1]).count('.')):
                top_referrer = msg_to_topmost.get(referrer, referrer)
                
                if (msg in msg_to_imports[top_referrer] and \
                    top_referrer in msg_to_imports[msg] and \
                    msg_to_topmost.get(referrer, referrer) != msg) or \
                    duplicate_enumfields:
                    
                    merge_and_rename(msg, referrer, get_pkg(msg), False,
                        msg_to_referrers, msg_to_topmost, msg_to_newloc, msg_to_imports, msg_path_to_obj, newloc_to_msg)
                    
                    still_to_merge = True
                    del mergeable[msg]
                    break
            
            for dupfield in duplicate_enumfields:
                siblings = enumfield_to_enums[dupfield]
                siblings.remove(msg)
                if len(siblings) == 1:
                    enum_to_dupfields[siblings.pop()].remove(dupfield)
    
    for msg, msg_obj in msg_path_to_obj.items():
        # If we're a top-level message, enforce name transforms anyway
        if msg not in msg_to_topmost:
            new_name = msg_obj.name.split('$')[-1]
            new_name = new_name[0].upper() + new_name[1:]
            
            msg_pkg = get_pkg(msg)
            if msg_pkg:
                msg_pkg += '.'
            
            if new_name != msg_obj.name:
                while newloc_to_msg.get(msg_pkg + new_name, msg_pkg + new_name) in msg_path_to_obj:
                    new_name += '_'
                msg_obj.name = new_name
            
            fix_naming(msg_obj, msg_pkg + new_name, msg, msg,
                       msg_to_referrers, msg_to_topmost, msg_to_newloc, msg_to_imports, msg_path_to_obj, newloc_to_msg)
    
    # Turn messages into individual files and stringify.
    
    path_to_file = OrderedDict()
    path_to_defines = defaultdict(list)
    
    for msg, msg_obj in msg_path_to_obj.items():
        if msg not in msg_to_topmost:
            path = msg.split('$')[0].replace('.', '/') + '.proto'
            
            if path not in path_to_file:
                path_to_file[path] = FileDescriptorProto()
                path_to_file[path].syntax = 'proto2'
                path_to_file[path].package = get_pkg(msg)
                path_to_file[path].name = path
            file_obj = path_to_file[path]
            
            for imported in msg_to_imports[msg]:
                import_path = imported.split('$')[0].replace('.', '/') + '.proto'
                if import_path != path and imported not in msg_to_topmost:
                    if import_path not in file_obj.dependency:
                        file_obj.dependency.append(import_path)

            if isinstance(msg_obj, DescriptorProto):
                nested = file_obj.message_type.add()
            else:
                nested = file_obj.enum_type.add()
            nested.MergeFrom(msg_obj)

            path_to_defines[path].append(msg)
            path_to_defines[path] += [k for k, v in msg_to_topmost.items() if v == msg and '$map' not in k]

    for path, file_obj in path_to_file.items():
        name, proto = descpb_to_proto(file_obj)
        header_lines = ['/**', 'Messages defined in this file:\n']
        header_lines += path_to_defines[path]
        yield name, '\n * '.join(header_lines) + '\n */\n\n' + proto

def merge_and_rename(msg, referrer, msg_pkg, is_group,
    msg_to_referrers, msg_to_topmost, msg_to_newloc, msg_to_imports, msg_path_to_obj, newloc_to_msg):
    if msg_pkg:
        msg_pkg += '.'

    msg_obj = msg_path_to_obj[msg]
    referrer_obj = msg_path_to_obj[referrer]
    top_path = msg_to_topmost.get(referrer, referrer)
    
    # Strip out $'s from name
    new_name = msg_obj.name.split('$')[-1]
    
    # Ensure first letter is uppercase, and avoid conflicts
    new_name = new_name[0].upper() + new_name[1:]
    
    other_names = [i.name for i in [*filter(lambda x: x.type != x.TYPE_GROUP,
                                            referrer_obj.field),
                                    *referrer_obj.nested_type,
                                    *referrer_obj.enum_type]]
    
    while new_name in other_names or \
          (is_group and new_name.lower() in other_names) or \
          (msg_pkg + new_name in msg_to_imports[top_path] and \
           msg_pkg + new_name not in msg_to_topmost):
        new_name += '_'
    msg_obj.name = new_name

    # Perform the merging of nested message
    
    if isinstance(msg_obj, DescriptorProto):
        nested = referrer_obj.nested_type.add()
    else:
        nested = referrer_obj.enum_type.add()
    nested.MergeFrom(msg_obj)
    
    # Perform the renaming of references to nested message, and
    # of references to children of nested message. Also, fix imports
    
    new_path = msg_to_newloc.get(referrer, referrer) + '.' + nested.name
    
    msg_to_imports[top_path].extend(msg_to_imports[msg])

    fix_naming(nested, new_path, msg, top_path,
               msg_to_referrers, msg_to_topmost, msg_to_newloc, msg_to_imports, msg_path_to_obj, newloc_to_msg)

"""
    Recursively iterate over the children and references of a just
    merged nested message/group/enum, in order to make state variables
    coherent.
"""
def fix_naming(nested, new_path, prev_path, top_path,
               msg_to_referrers, msg_to_topmost, msg_to_newloc, msg_to_imports, msg_path_to_obj, newloc_to_msg):
    
    # Keep track of the original full name of the generated block, as
    # it's the one we'll use when processing further references from
    # msg_to_referrers and other objects.
    orig_path = newloc_to_msg.get(prev_path, prev_path)
    newloc_to_msg[new_path] = orig_path

    if orig_path != top_path:
        msg_to_topmost[orig_path] = top_path
    msg_to_newloc[orig_path] = new_path
    msg_path_to_obj[orig_path] = nested
    
    # Fix references.
    for field, referrer, _ in msg_to_referrers.get(orig_path, []):
        field = next((i for i in msg_path_to_obj[referrer].field if i.name == field), None)
        
        field.type_name = '.' + new_path

        # Fix imports in reference's files.
        referrer_top_path = msg_to_topmost.get(referrer, referrer)
        
        msg_to_imports[referrer_top_path].append(top_path)
    
    # Do the same with children.
    if isinstance(nested, DescriptorProto):
        for child in [*nested.nested_type, *nested.enum_type]:
            fix_naming(child, new_path + '.' + child.name, prev_path + '.' + child.name, top_path,
                       msg_to_referrers, msg_to_topmost, msg_to_newloc, msg_to_imports, msg_path_to_obj, newloc_to_msg)

get_pkg = lambda x: ('.' + x).rsplit('.', 1)[0][1:]
