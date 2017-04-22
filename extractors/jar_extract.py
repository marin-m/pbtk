#!/usr/bin/python3
#-*- encoding: Utf-8 -*-
from google.protobuf.descriptor_pb2 import DescriptorProto, EnumDescriptorProto, FieldDescriptorProto
from re import findall, MULTILINE, search, split, sub, escape, finditer
from collections import OrderedDict, defaultdict
from itertools import count, product
from string import ascii_lowercase
from ctypes import c_int, c_long
from struct import pack, unpack
from ast import literal_eval

from os.path import dirname, realpath
__import__('sys').path.append(dirname(realpath(__file__)) + '/..')
from utils.common import register_extractor, extractor_main
from utils.nest_messages import nest_and_print_to_files
from extractors.from_binary import walk_binary
from utils.java_wrapper import JarWrapper

"""
    This script aims to provide a complete Protobuf structure extraction
    routine for the different Java target implementations that exist.

    Most of these (Lite, Nano, Micro) share a common structure in generated
    code. In a common logic for processing them, important library classes
    (such as CommonInputStream/CommonOutputStream) are first recognized
    through simple string signatures.

    Then, generated classes are decompiled and parsed based on a regexp
    system (somewhat less burdensome than following bytecode structure),
    calls to library classes and their context are analyzed, and this
    information is used to reconstruct the Protobuf structure.

    The decompiler used is Jad. Although slighty outdated, it produces more
    complete output on erroring classes (rather than failing or omitting
    code, like other tools), and is blazing fast. Dex-to-Jar conversion is
    operated using dex2jar.
"""

@register_extractor(name = 'jar_extract',
                    desc = 'Extract Protobuf structures from any Java code (*.jar, *.dex, *.apk)',
                    depends={'binaries': ['java']})
def handle_jar(path):
    # Scan classes for Java Protobuf string signatures
    
    if path.endswith('.jar'):
        yield '_progress', ('Decompressing JAR...', None)
    else:
        yield '_progress', ('Converting DEX to JAR...', None)
    
    with JarWrapper(path) as jar:
        enums = {}
        
        pkg_to_codedinputstream = OrderedDict()
        pkg_to_codedoutputstream = {}
        map_entry_cls = []
        out_additional_cls = []
        
        pkg_to_j2me_protobuftype = OrderedDict()
        
        """
        First iteration on classes: look for library classes signatures.
        """
        
        for i, cls in enumerate(jar.classes):
            if i % 10 == 0:
                yield '_progress', ('Scanning Java package contents...', (i / len(jar.classes)) * 0.5)
            
            pkg = cls[:cls.rfind('.')] if '.' in cls else ''
            binr = jar.read(cls)
            
            # Search for CodedInputStream/CodedOutputStream
            
            raw_cls = cls.replace('.', '/').encode('utf8')
            
            """
            Handle multiple cases:
            1. CodedInputStream, before it was split out in multiple
               subclasses (cc8ca5b - oct 2016)
            2. CodedInputStream, after it was
            3. CodedInputByteBufferNano
            4. CodedInputStreamMicro
            
            The second case doesn't provide intelligible strings to
            search for, so we'll use method signatures (the different
            kinds that can be produced by Proguard) instead.
            """
            
            SIG_NANO = b'([BII)V' # CodedInputByteBufferNano(final byte[] buffer, final int off, final int len)
            SIG_NANO_2 = b'([BI)V' # CodedInputByteBufferNano(final byte[] buffer, final int bufferSize)
            SIG_DEF = b'([BIIZ)L%s;' % raw_cls # static CodedInputStream newInstance(final byte[] buf, final int off, final int len, final boolean bufferIsImmutable)
            SIG_DEF_2 = b'([BII)L%s;' % raw_cls # static CodedInputStream newInstance(final byte[] buf, final int off, final int len)
            SIG_CALL = b'([BIIZ)V' # private ArrayDecoder(final byte[] buffer, final int offset, final int len, boolean immutable)
            SIG_CALL_2 = b'([BII)V' # private ArrayDecoder(final byte[] buffer, final int offset, final int len)
            SIG_CALL_3 = b'([BIIZL' # CodedInputStream$ArrayDecoder(byte abyte0[], int i, int j, boolean flag, com.google.protobuf.CodedInputStream$1 codedinputstream$1)
            
            has_constructor = SIG_DEF in binr or SIG_DEF_2 in binr
            calls_arraydecoder = SIG_CALL in binr or SIG_CALL_2 in binr or SIG_CALL_3 in binr
            is_legit_class = b'Beginning index' not in binr and b'Number too large' not in binr and b'a byte array' not in binr
            
            has_constructor_nano = SIG_NANO in binr or SIG_NANO_2 in binr
            has_relevant_string = b'message contained an invalid tag' in binr
            has_relevant_string_nano = b'is beyond current' in binr
            has_relevant_string_micro = b"when buffer wasn't empty" in binr
            
            """
            Try to match CodedOutputStream before CodedInputStream, as
            it may have common points in signatures but always has a
            recognizable string.
            """
            
            has_out_constructor = b'([BII' in binr
            has_out_relevant_string = b'write as much data as' in binr
            has_out_relevant_string_old = b'UTF-8 not supported.' in binr
            has_out_relevant_string_nano = b'Unpaired surrogate at index ' in binr and b'wrap' in binr
            has_out_relevant_string_2 = b'Converting ill-formed UTF-16.' in binr and b'Pos:' not in binr
            is_legit_out_class = b'byte array' not in binr
            
            if has_out_constructor and (\
               ((has_out_relevant_string or has_out_relevant_string_old) and is_legit_out_class) or \
                 has_out_relevant_string_nano or has_out_relevant_string_2): # CodedOutputStream
                
                while pkg in pkg_to_codedoutputstream:
                    pkg += '_'
                pkg_to_codedoutputstream[pkg] = cls
            
            elif (has_constructor and is_legit_class and (calls_arraydecoder or has_relevant_string)) or \
               (has_constructor_nano and (has_relevant_string_nano or has_relevant_string_micro)): # CodedInputStream
                
                while pkg in pkg_to_codedinputstream:
                    pkg += '_'
                pkg_to_codedinputstream[pkg] = cls
            
            # Other classes that may be called for (de)serializing objects
            
            elif b'Generated message class' in binr: # GeneratedMessage*
                out_additional_cls.append(cls)

            elif b'is not a primitive type' in binr: # InternalNano
                map_entry_cls.append(cls)
            
            elif b'Groups are not allowed in maps' in binr or \
                 b'a map entry message.' in binr: # MapEntry*
                map_entry_cls.append(cls)
            
            # Search for J2ME implementation's ProtoBuf.java
            
            elif b'Unexp.EOF' in binr:
                code = jar.decomp(cls, True).raw
                protobuftype_cls = search('public \w+\(([\w.$]+) \w+\)', code).group(1)
                
                default_consts = {}
                for prop, const in findall('(\w+) = new Boolean\((\w+)\)', code):
                    default_consts[cls + '.' + prop] = const
                
                while pkg in pkg_to_j2me_protobuftype:
                    pkg += '_'
                pkg_to_j2me_protobuftype[pkg] = (protobuftype_cls, default_consts)
        
        for pkg in list(pkg_to_codedinputstream):
            if pkg not in pkg_to_codedoutputstream:
                del pkg_to_codedinputstream[pkg]
        
        """
        Second iteration on classes: look for generated classes, that
        contains method call signatures [1] for libraries we found, or
        other extractible information.
        
        [1] https://docs.oracle.com/javase/specs/jvms/se7/html/jvms-4.html#jvms-4.3
        """
        
        gen_classes = OrderedDict()
        gen_classes_j2me = OrderedDict()
        had_metadata = set()
        
        for i, cls in enumerate(jar.classes):
            if i % 10 == 0:
                yield '_progress', ('Scanning Java package contents...', (i / len(jar.classes)) * 0.5 + 0.5)
            
            binr = jar.read(cls)
            
            # Search for metadata descriptors
            if b'.proto\x12' in binr or b'.protodevel\x12' in binr:
                code = jar.decomp(cls, True).raw
                code = sub('",\s+"', '', code, flags=MULTILINE)
                meta = search(r'"(\\n.+?\.proto.+)"', code)
                if meta:
                    meta = meta.group(1).encode('latin1')
                    meta = meta.decode('unicode_escape').encode('latin1')
                    
                    yield from walk_binary(meta)
                    had_metadata.add(cls)
            
            # Search for signatures common to generated Java classes
            for impl in pkg_to_codedinputstream:
                if b'%s' % pkg_to_codedinputstream[impl].replace('.', '/').encode('ascii') in binr and \
                   b'(L%s;' % pkg_to_codedoutputstream[impl].replace('.', '/').encode('ascii') in binr and \
                   cls not in (pkg_to_codedinputstream[impl], pkg_to_codedoutputstream[impl]):
                    gen_classes[cls] = (pkg_to_codedinputstream[impl], pkg_to_codedoutputstream[impl])
        
            # Search for generated J2ME classes
            for impl, (protobuftype_cls, consts) in pkg_to_j2me_protobuftype.items():
                if b'(IILjava/lang/Object;)L%s;' % protobuftype_cls.replace('.', '/').encode('ascii') in binr and \
                   cls != protobuftype_cls:
                    gen_classes_j2me[cls] = (protobuftype_cls, consts)

            # Search for enums
            if b'Ljava/lang/Enum<' in binr[:256]:
                enums[cls] = cls
                
                if '$' in cls:
                    enums[cls.replace('$', '.')] = cls
                    enums[cls.rsplit('.', 1)[0] + '.' + cls.rsplit('$', 1)[1]] = cls
        
        gen_classes_nodollar = OrderedDict(gen_classes)
        for cls, pkg in OrderedDict(gen_classes_nodollar).items():
            if '$' in cls:
                gen_classes_nodollar[cls.replace('$', '.')] = pkg
                gen_classes_nodollar[cls.rsplit('.', 1)[0] + '.' + cls.rsplit('$', 1)[1]] = pkg
        
        """
        Once we know what classes we should look at, do the actual code
        scraping and extraction work.
        """
        
        # These variables will be filled in by extract_* functions:
        
        msg_path_to_obj = OrderedDict() # For the class name of a message/enum, its DescriptorProto object
        msg_to_referrers = defaultdict(list) # For a nested message/enum, all message fields that refer to it
        
        # Call the extraction routine for most implementations
        for i, (cls, (codedinputstream, codedoutputstream)) in enumerate(gen_classes.items()):
            yield '_progress', ('Extracting %s...' % cls, i / len(gen_classes))
            
            if cls.split('$')[0] not in had_metadata:
                extract_lite(jar, cls, enums, gen_classes_nodollar, codedinputstream, codedoutputstream, map_entry_cls, out_additional_cls,
                             msg_path_to_obj, msg_to_referrers)
        
        # Call the extraction routine for J2ME
        for i, (cls, (protobuftype_cls, consts)) in enumerate(gen_classes_j2me.items()):
            yield '_progress', ('Extracting %s...' % cls, i / len(gen_classes_j2me))
            
            extract_j2me(jar, cls, enums, gen_classes_j2me, protobuftype_cls, consts,
                         msg_path_to_obj, msg_to_referrers)
        
        yield '_progress', ('Dumping information to .protos...', None)

        # Merge nested Protobuf messages and write them to files
        yield from nest_and_print_to_files(msg_path_to_obj, msg_to_referrers)
        
        # If we got an APK and it contained .so's with embedded metadata or .protos, yield them
        yield from jar.bonus_protos.items()

"""
    Extraction routine for most implementations (Base, Lite, Nano, Micro)
    
    Base should already be handled through metadata extraction.
"""
def extract_lite(jar, cls, enums, gen_classes, codedinputstream, codedoutputstream, map_entry_cls, out_additional_cls,
                 msg_path_to_obj, msg_to_referrers):
    code = jar.decomp(cls)
    
    print('\nIn %s:' % cls)
    if not code.raw:
        print('(Jad failed)')
        return

    """
    Step 1: Look for calls to CodedInputStream (or CodedInputByteBufferNano) methods
    
    They should be located in a switch structure from mergeFrom(CodedInputStream), or from MERGE_FROM_STREAM: of dynamicMethod()
    """
    
    in_switch = False
    label_to_val = None
    fields = {}
    
    for start, (call, end) in code.method_calls.items():
        call_ret, call_obj, call_name, call_args = call
        
        if call_obj in [codedinputstream, *map_entry_cls] \
           and not (call_ret, call_args) == ('void', 'int'):
        
            if not in_switch:
                # Look at the switch structure around the read*() calls:
                
                next_lines = '\n'.join(code.raw[start:].split('\n')[:3])
                
                if 'INSTR lookupswitch' in next_lines or ' switch(' in next_lines:
                    in_switch = True
                    label_to_val = code.parse_switch(start, next_lines)
            
            else:
                # Then at the switch's cases:
                
                if label_to_val and start < label_to_val[0][0]: # We're before the current switch case...
                    continue
                while label_to_val and start > label_to_val[0][1][1]: # We're after the next one in method...
                    lazy_start, (lazy_tag, lazy_end) = label_to_val.pop(0)
                    
                    if lazy_tag and lazy_tag >> 3 not in fields:
                        lazy_obj = search('([\w$.]+) [\w$]+ = new ', code.raw[lazy_start:lazy_end])
                        fenumormsg = None
                        if lazy_obj and lazy_obj.group(1) in gen_classes:
                            fenumormsg = lazy_obj.group(1)
                        
                        ftype = {0: 'int32', 1: 'fixed64', 2: 'bytes', 3: 'group', 5: 'fixed32'}[lazy_tag & 7]
                        fields[lazy_tag >> 3] = (ftype, fenumormsg)
                
                if not label_to_val: # We have seen every case...
                    break
                
                label_start, (tag, label_end) = label_to_val[0]
                
                # Parse the message number and wire type from switch case value
                fnumber, wire_type = (tag >> 3), (tag & 0b111)
                if fnumber in fields and fields[fnumber][0] != 'bytes':
                    continue
                
                case = code.raw[label_start:label_end]
                
                # Interprete wire type: https://developers.google.com/protocol-buffers/docs/encoding#structure,
                # Then look at called method's return type
                
                fenumormsg = None
                call_ret = call_ret.split('.')[-1]
                
                if wire_type == 0: # Varint
                    ftype = {'long': 'int64', 'boolean': 'bool'}.get(call_ret, 'uint32')
                    # We'll distinguish a uint32 from a int32 on step 2.
                    # We can't know signedness for (u)int64, (s)fixed32 or (s)fixed64, so pick the most common case.
                    
                    if ('!= 0' in case and not '.arraycopy' in case) or 'oolean' in case:
                        ftype = 'bool'
                    elif 'Long' in ftype and ftype == 'uint32':
                        ftype = 'int64'
                    
                    # Look for enums
                    if ftype == 'uint32':
                        for start2, (call2, end2) in code.method_calls.items():
                            _, call2_obj, _, _ = call2
                            
                            if label_start < start2 < label_end and call2_obj in enums:
                                ftype = 'enum'
                                fenumormsg = call2_obj
                                break
                
                elif wire_type == 1:
                    ftype = {'double': 'double'}.get(call_ret, 'fixed64')
                    if 'longBitsToDouble' in case:
                        ftype = 'double'
                    
                elif wire_type == 5:
                    ftype = {'float': 'float'}.get(call_ret, 'fixed32')
                    if 'intBitsToFloat' in case:
                        ftype = 'float'
                
                elif wire_type == 2: # Length-delimited
                    ftype = {'String': 'string'}.get(call_ret, 'bytes')

                    first_arg = code.raw[end:].split('\n', 1)[0].split(',')[0]
                    if first_arg.endswith('()'):
                        first_arg = first_arg.rsplit('.', 1)[0]
                        
                        if first_arg in gen_classes:
                            fenumormsg = first_arg
                            ftype = 'message'
                
                elif wire_type == 3:
                    ftype = 'group'

                    for start2, (call2, end2) in code.method_calls.items():
                        _, call2_obj, _, _ = call2
                        
                        if label_start < start2 < label_end and call2_obj in gen_classes:
                            fenumormsg = call2_obj
                            break                
                else:
                    return
                
                if not fenumormsg and ftype in ('group', 'bytes'):
                    msg_obj = search('([\w$.]+) [\w$]+ = new ', case)
                    
                    if msg_obj and msg_obj.group(1) in gen_classes:
                        fenumormsg = msg_obj.group(1)
                        if ftype == 'bytes':
                            ftype = 'message'
                
                # General case: store information for step 2
                if call_obj not in map_entry_cls or len(call_args.split(', ')) != 8:
                    fields[fnumber] = (ftype, fenumormsg)

                else: # Look for InternalNano.mergeMapEntry()
                    args = code.raw[start:].split('(')[1].split(')')[0].split(', ')
                    var, ftype1, fmsg1, ftype2, fmsg2 = args[1], int(args[3]), None, int(args[4]), args[5]

                    fmsg2 = fmsg2[4:].split('(')[0] if fmsg2.startswith('new ') else None
                    
                    fields[fnumber] = create_map(cls, jar, enums, code.pkg, var, fnumber, ftype1, fmsg1, ftype2, fmsg2, \
                                                 msg_to_referrers, msg_path_to_obj)

    
    if not in_switch and 'tableswitch 0 0' not in code.raw:
        return
    
    # Store any remaining fields that weren't parsed
    while label_to_val:
        lazy_start, (lazy_tag, lazy_end) = label_to_val.pop(0)
        if lazy_tag and lazy_tag >> 3 not in fields:
            lazy_obj = search('([\w$.]+) [\w$]+ = new ', code.raw[lazy_start:lazy_end])
            fenumormsg = None
            if lazy_obj and lazy_obj.group(1) in gen_classes:
                fenumormsg = lazy_obj.group(1)
            
            ftype = {0: 'int32', 1: 'fixed64', 2: 'bytes', 3: 'group', 5: 'fixed32'}[lazy_tag & 7]
            fields[lazy_tag >> 3] = (ftype, fenumormsg)
    
    """
    Step 2: Look for calls to CodedOutputStream (or CodedOutputByteBufferNano, or GeneratedMessage) methods
    
    They should be located mostly in conditions of .writeTo(CodedOutputStream)
    """
    
    seen_conds = set()
    cond_lines = OrderedDict()
    prev_cond_end = 0
    take_packed = False
    
    for start, (call, end) in code.method_calls.items():
        call_ret, call_obj, call_name, call_args = call
        
        has_constant = search('\(\d+', code.raw[start:].split('\n')[0]) or search('\([a-zA-Z_]\w*, \d+', code.raw[start:].split('\n')[0])
        
        if call_obj in [codedoutputstream, *out_additional_cls, *map_entry_cls] and \
           (has_constant or take_packed):

            from_condition = False
            
            # Does it originate from a condition block?
            for cond_start, cond_end in code.cond_bounds:
                if cond_start < start < cond_end:
                    from_condition = True
                    prev_cond_end = cond_end
                    break
            
            # If it doesn't (it is a required field in Nano implementation),
            # what are the nearest blocks we can relate to?
            if not from_condition:
                func_start, func_end = next((i for i in code.method_bounds.values() if i[0] < start < i[1]), None)
                
                after_line = code.raw.index('\n', start)
                cond_start, cond_end = max(func_start, prev_cond_end), after_line
                prev_cond_end = after_line
            
            cond = code.raw[cond_start:cond_end]
            callee = None
            
            has_constant = search('\(\d+', cond) or search('\([a-zA-Z_]\w*, \d+', cond)
            
            separate_tag = False
            if has_constant:
                # Parse the field number from method arguments
                shift = False
                fnumber = search('\((\d+), ', cond)
                if not fnumber:
                    fnumber = search('(?<!put)\([a-zA-Z_]\w*, (\d+)', cond)
                if not fnumber:
                    fnumber = search('\((\d+)\)', cond)
                    separate_tag = True
                    assert fnumber
                    callee = jar.decomp_func(call) + cond
                    if '<< 3' not in callee:
                        shift = True
                fnumber = int(fnumber.group(1))
                if shift:
                    fnumber >>= 3
            
            take_packed = separate_tag or not has_constant
            
            is_map_continuation = '.hasNext' in cond and '.iterator' not in cond
            
            # Based on field number, load back information from step 1
            
            if fnumber not in fields:
                print('Note: extension data ignored, extensions are not supported yet')
                continue
            field = fields[fnumber]
            
            if len(field) == 2:
                ftype, fenumormsg = field
                var = None
            else:
                flabel, ftype, fenumormsg, fdefault, var = field
            
            # Store condition line (if any) for optional processing of step 3
            if from_condition:
                cond_line = cond.split('\n')[0].strip()
                if ';' in cond_line:
                    cond_line = sub('^[\w\s$]+', '', cond_line.split(';')[1])
                cond_lines[cond_line] = fnumber
                assert 'int ' not in cond_line
            
            # Perform a few checks about what we couldn't see from step 1
            
            flabel = 'optional'
            if 'for(' in cond or 'while(' in cond:
                flabel = 'repeated'
            elif 'if(' not in cond:
                flabel = 'required'
            
            if ftype in ('uint32', 'int64'):
                if not callee:
                    callee = jar.decomp_func(call) + cond
                
                # Don't inherit signedness from the call that writes
                # tag number, if separate
                if call_args == 'int' and \
                   code.raw[start:].split('(')[1].split(')')[0].isdigit():
                    callee = cond
                
                if ' >= 0' in callee:
                    ftype = ftype[-5:]
                if ' << 1' in callee:
                    ftype = 's' + ftype[-5:]
            
            # Look for enums
            if ftype == 'int32':
                for start2, (call2, end2) in code.method_calls.items():
                    _, call2_obj, _, _ = call2
                    
                    if cond_start < start2 < cond_end and call2_obj in enums:
                        ftype = 'enum'
                        fenumormsg = call2_obj
                        break
            
            # Search for the relevant variable name for this field
            
            # Try successive regexes. Strings mean search variable name
            # in the code, lists of strings mean search for a local
            # method call, then for variable name in this method's code.
            
            if not var or (has_constant and not shift and not is_map_continuation):
                var = None
                regexps = [' < ([\w$]+)\.(?:size|length)',
                          '([\w$]+)\.(?:size\(\)|length) > ',
                          ' >= ([\w$]+)\.(?:size\(\)|length)',
                         ['([\w$]+)\(\)\.(?:size\(\)|length)', 'return ([a-zA-Z_][\w$]*);', 'return new [\w.$]+\(([a-zA-Z_][\w$]*),'],
                          'if\(([\w$]+) [!=]= null\)',
                          'if\(\!([\w$]+)\..+?\(\)\)',
                          '(?:unmodifiableMap|Arrays\.equals)\(([a-zA-Z_][\w$]*)',
                          'Bits\((?:\(+[\w.]+\))?([a-zA-Z_][\w$]*)\)',
                          '([a-zA-Z_][\w$]*)\.(?:getMap|entrySet|iterator)\(',
                         ['([a-zA-Z_][\w$]*)\(\)\.(?:getMap|entrySet|iterator)\(', 'return ([a-zA-Z_][\w$]*);'],
                          ' = \(java\.lang\.String\)([a-zA-Z_][\w$]*)',
                          ', \(java.+?\)([a-zA-Z_][\w$]*)[).]',
                         ['\(\d+, ([a-zA-Z_][\w$]*)\(\)+\)', ' = \(.+?\)([a-zA-Z_][\w$]*);', 'return ([a-zA-Z_][\w$]*);', ' = ([a-zA-Z_][\w$]*);'],
                          '\s+([a-zA-Z_][\w$]*)\.[\w$]+\(\);',
                          '\d+, [\w$]+\.\w+\(([a-zA-Z_][\w$]*)\)',
                          ', ([a-zA-Z_][\w$]*)[).]',
                          '(?<!flag)(?<!flag\d) = ([a-zA-Z_][\w$]*);',
                          ' = ([a-zA-Z_][\w$]*)\[',
                          ' = \(.+?\)([a-zA-Z_][\w$]*)',
                          ' = \(\(.+?\)([a-zA-Z_][\w$]*)\)\.',
                          ' = ([a-zA-Z_][\w$]*);',
                          ', \(.+?\)([a-zA-Z_][\w$]*)[).]',
                          '\(\!?([a-zA-Z_][\w$]*)\)']
                
                for regex in regexps:
                    if type(regex) == str: # Regular case
                        var = search(regex, cond)
                    
                    elif type(regex) == list: # Search inside a method
                        func = search(regex[0], cond)
                        if func:
                            call_sig, _ = code.method_loc_calls[cond_start + func.start(1)]
                            func = code.get_method_unfold(call_sig, unfold=False)
                            for regex2 in regex[1:]:
                                if not var:
                                    var = search(regex2, func)
                    if var and var.group(1) in ('super', 'false', 'true'):
                        var = None
                    if var:
                        break

                if not var:
                    continue
                var = var.group(1)
                
                # Search for the line defining the default value for this variable
                
                fdefault = findall('\s+(?:super\.)?%s(?:\[\])* = (.+?);' % escape(var), code.raw, flags=MULTILINE)
                if not fdefault:
                    fdefault = ['null']
                fdefault = next((i for i in fdefault if i not in ('0', 'null', 'false')), fdefault[0])
                
                # Check its type for an embedded message or group, too
                
                fdefault_type = search('([\w.$]+?) %s(?:\[\])*(?: =|;)' % escape(var), code.raw, flags=MULTILINE)
                if fdefault_type and fdefault_type.group(1) in gen_classes:
                    fenumormsg = fdefault_type.group(1)
                    if ftype == 'bytes':
                        ftype = 'message'
                
                # Parse default value if it denotes a message type
                if '.DEFAULT_INSTANCE' in fdefault:
                    fenumormsg = fdefault.split('.DEFAULT_INSTANCE')[0].split('(')[-1].split(', ')[-1]
            
            if fdefault == 'null':
                fdefault = None
            
            if call_obj not in map_entry_cls or fenumormsg: # Non map-type: store back information
                fields[fnumber] = (flabel, ftype, fenumormsg, fdefault, var)
            
            # Look for MapEntryLite.serializeTo() or MapEntry.newBuilderForType()
            else:
                map_cls = search('([\w.$]+)\.[\w$]+$', code.raw[:start].split('\n')[-1])
                map_cls = map_cls.group(1) if map_cls else call_obj
                if call_obj.startswith(map_cls):
                    map_cls = search(' = ([\w$.]+)\.\w+;', cond) # Handle inlined call
                    if not map_cls:
                        fields[fnumber] = (flabel, ftype, fenumormsg, fdefault, )
                        continue
                    map_cls = map_cls.group(1)
                map_code = jar.decomp(map_cls, True).raw
                
                # Look for MapEntryLite.newDefaultInstance()
                args = map_code.split('static \n')[1].split('(', 1)[1].split('\n')[0].split(', ')
                if len(args) == 5:
                    args.pop(0)
                ftype1, fmsg1, ftype2, fmsg2 = args[0], args[1], args[2], args[3]
                
                fmsg1 = fmsg1.split('(')[1].rsplit('.', 2)[0] if '.valueOf(' in fmsg1 else fmsg1.rsplit('.', 1)[0]
                fmsg2 = fmsg2.split('(')[1].rsplit('.', 2)[0] if '.valueOf(' in fmsg2 else fmsg2.rsplit('.', 1)[0]
                
                fields[fnumber] = create_map(cls, jar, enums, code.pkg, var, fnumber, ftype1, fmsg1, ftype2, fmsg2, \
                                             msg_to_referrers, msg_path_to_obj)

    """
    Optional step 3 (for Lite-generated code only): look for 'case IS_INITIALIZED:'
    """
    
    case = split(' == 1\)[\n{ ]+return DEFAULT_INSTANCE;(?:[\n ]+\}\n)?', code.raw, flags=MULTILINE)
    if len(case) > 1:
        case = case[1]
        case = case.split('\n_')[0]
        
        for cond in cond_lines:
            if cond in case:
                fnumber = cond_lines[cond]
                
                flabel, ftype, fenumormsg, fdefault, var = fields[fnumber]
                
                if ftype in ('message', 'group', 'bytes'):
                    body = case.split(cond, 1)[1]
                    for cond2 in set(cond_lines) - {cond}:
                        body = body.split(cond2)[0]
                    
                    if '.DEFAULT_INSTANCE)' in body:
                        fenumormsg = body.split('.DEFAULT_INSTANCE)')[0].split('(')[-1].split(', ')[-1]
                        if ftype == 'bytes':
                            ftype = 'message'
                
                fields[fnumber] = (flabel, ftype, fenumormsg, fdefault, var)
    
    print(fields)

    """
    Final step: Build the DescriptorProto object
    """
    
    message = DescriptorProto()
    message.name = cls.rsplit('.', 1)[-1]

    seen_vars = {}
    my_namer = namer()
    oneofs = {}
        
    # Are these variables proguarded and should we rename these?
    use_namer = all(len(i[4]) < 3 or i[4].endswith('_fld') for i in fields.values())
    
    all_vars = [field[4] for field in fields.values()]
    
    for number, (flabel, ftype, fenumormsg, fdefault, var) in sorted(fields.items()):
        field = message.field.add()
        
        if ftype == 'group' and not fenumormsg:
            ftype = 'bytes'
        
        if ftype == 'enum' and fenumormsg not in msg_path_to_obj:
            create_enum(jar, enums, fenumormsg, msg_path_to_obj)
        
        if ftype == 'enum' and fdefault and fdefault.lstrip('-').isnumeric():
            fdefault = next((repr(x.name) \
                             for x in msg_path_to_obj[fenumormsg].value[1:] \
                             if x.number == int(fdefault)), None)
        
        if use_namer:
            disp_var = next(my_namer)
        else:
            disp_var = var.rstrip('_')
            if disp_var[0].islower():
                disp_var = sub('[A-Z]', lambda x: '_' + x.group(0).lower(), disp_var)
        
        if all_vars.count(var) > 1:
            assert flabel == 'optional'
            if var not in oneofs:
                oneofs[var] = (len(message.oneof_decl), message.oneof_decl.add())
                oneofs[var][1].name = disp_var
            if not use_namer or oneofs[var][1].name == disp_var:
                disp_var = next(my_namer)
            field.oneof_index = oneofs[var][0]
            fdefault = None
        
        if fdefault and (var not in seen_vars or seen_vars[var] == (flabel, ftype)) and \
           ftype not in ('message', 'group', 'bytes') and flabel != 'repeated':
            
            parse_default(field, ftype, fdefault)
        
        field.name = disp_var
        field.number = number
        field.label = label_consts[flabel]
        field.type = type_consts[ftype]
        
        if fenumormsg:
            field.type_name = '.' + fenumormsg
            msg_to_referrers[fenumormsg].append((field.name, cls, ftype == 'group'))
        
        seen_vars[var] = (flabel, ftype)
    
    msg_path_to_obj[cls] = message

def namer():
    for length in count(1):
        for name in product(ascii_lowercase, repeat=length):
            yield ''.join(name)

"""
    Parse a default value out of a Java literal. Handle signedness, etc.
"""

def parse_default(field, ftype, fdefault):
    if not (ftype == 'bool' and fdefault == 'true'):
        try:
            fdefault = literal_eval(fdefault.rstrip('LDF'))
        except (ValueError, SyntaxError):
            fdefault = None
    
    if type(fdefault) is int:
        if ftype[0] != 'u' and ftype[:5] != 'fixed':
            if fdefault >> 63:
                fdefault = c_long(fdefault).value
            elif fdefault >> 31 and ftype[-2:] != '64':
                fdefault = c_int(fdefault).value
        else:
            fdefault &= (1 << int(ftype[-2:])) - 1
        
        if ftype == 'float' and abs(fdefault) >> 23:
            fdefault = unpack('=f', pack('=i', fdefault))[0]
        elif ftype == 'double' and abs(fdefault) >> 52:
            fdefault = unpack('=d', pack('=q', fdefault))[0]
    
    if fdefault:
        field.default_value = str(fdefault)

"""
    Create an enum or map, still as descriptor objects.
"""

def create_enum(jar, enums, fenum, msg_path_to_obj):
    if fenum not in msg_path_to_obj:
        enum_code = jar.decomp(enums[fenum], True).raw
        
        enum = EnumDescriptorProto()
        enum.name = fenum.split('.')[-1]
        for fname, fnumber in findall('(?:[\w.$]+|<init>)\("(.+?)", \d+, (-?\d+)[LDF]?\);', enum_code):
            if (fname, fnumber) != ('UNRECOGNIZED', '-1'):
                value = enum.value.add()
                value.name = fname
                value.number = int(fnumber)
        
        msg_path_to_obj[fenum] = enum

def create_map(cls, jar, enums, pkg, var, number, ftype1, fmsg1, ftype2, fmsg2, \
               msg_to_referrers, msg_path_to_obj):
    map_obj = DescriptorProto()
    map_obj.options.map_entry = True
    map_obj.name = '%s$map%d' % (cls.split('.')[-1], number)
    
    map_full_name = map_obj.name
    if pkg:
        map_full_name = pkg + '.' + map_full_name
    
    if map_full_name not in msg_path_to_obj:
        for fnumber, fname, ftype, fmsg in ((1, 'key', ftype1, fmsg1), \
                                            (2, 'value', ftype2, fmsg2)):
            field = map_obj.field.add()

            if type(ftype) is str:
                if ftype.isnumeric():
                    ftype = int(ftype)
                else:
                    enum_name, enum_var = ftype.rsplit('.', 1)
                    enum_code = jar.decomp(enum_name, True).raw
                    ftype = type_consts[enum_code.split(enum_var + ' = new ')[1].split('"')[1].lower()]

            if fmsg and ftype in (field.TYPE_GROUP, field.TYPE_ENUM, field.TYPE_MESSAGE):
                if '.' not in fmsg and pkg:
                    fmsg = pkg + '.' + fmsg
                msg_to_referrers[fmsg].append((fname, map_full_name, ftype == FieldDescriptorProto.TYPE_GROUP))
                field.type_name = '.' + fmsg
            
            if ftype == field.TYPE_ENUM:
                if fmsg:
                    create_enum(jar, enums, fmsg, msg_path_to_obj)
                else:
                    ftype = field.TYPE_INT32
            
            field.type = ftype
            field.name = fname
            field.number = fnumber
        
        msg_path_to_obj[map_full_name] = map_obj
    
    return ('repeated', 'message', map_full_name, None, var)

"""
    Extraction routine for the J2ME implementation. See [1] for
    reference of type and label constants.
    
    [1] https://github.com/android/platform_external_protobuf/blob/eclair-release/src/com/google/common/io/protocol/ProtoBufType.java
"""

def extract_j2me(jar, cls, enums, gen_classes_j2me, protobuftype_cls, consts,
                 msg_path_to_obj, msg_to_referrers):
    code = jar.decomp(cls, True)
    cls = cls.replace('$', '.')
    
    if not code.raw:
        print('(Jad failed)')
        return

    """
    First step: look for calls to ProtoBufType.addElement(int, int, Object)
    """
    
    code = sub('(?:new )?[\w$.]+\((-?\d+)[LDF]?\)', r'\1', code.raw)
    fields_for_msg = defaultdict(str)
    
    for var in findall('(\w+) = new ', code):
        fields_for_msg[var]
    
    while True:
        # Case 1: handle embedded groups
        decl = list(finditer('(\(new \w+\(("\w+")\)\)(?=((?:\.\w+\(\d+, \d+, .+?\))+)\)))', code))[::-1]
        if not decl:
            # Case 2: general case, handle messages
            decl = list(finditer('( (\w+)(?=((?:\.\w+\(\d+, \d+, .+?\))+);))', code))
        if not decl:
            break
        prefix, var, fields = decl[0].groups()
        
        if var[0] == '"':
            var = var.strip('"')
            # If group, avoid name conflicts
            while var in fields_for_msg:
                var += '_'
        else:
            # If message, handle object variable reassignements
            public_var = findall(' %s = ([a-zA-Z_][\w$]*);' % var, code[:decl[0].start()])
            if public_var and public_var[-1] != 'null':
                var = public_var[-1]

        code = code.replace(prefix + fields, var, 1)
        
        # Store var, fields
        fields_for_msg[var] += fields
    
    """
    Final step: Build the DescriptorProto object
    """
    
    for var, fields in fields_for_msg.items():
        message = DescriptorProto()

        my_namer = namer()
        summary = {}
        
        print('\nIn %s.%s:' % (cls, var))
        message.name = var

        if fields:
            for ftypeandlabel, fnumber, fdefaultormsg in findall('\.\w+\((\d+), (\d+), (.+?)\)', fields):
                field = message.field.add()
                
                # Use int32 instead of enum (we don't have enum contents),
                # Use bytes and string instead of data and text (Protobuf 1 types).
                
                types = {17: 'double', 18: 'float', 19: 'int64', 20: 'uint64', 21: 'int32', 22: 'fixed64', 23: 'fixed32', 24: 'bool', 25: 'bytes', 26: 'group', 27: 'message', 28: 'string', 29: 'uint32', 30: 'int32', 31: 'sfixed32', 32: 'sfixed64', 33: 'sint32', 34: 'sint64', 35: 'bytes', 36: 'string'}
                ftype = types[int(ftypeandlabel) & 0xff]
                
                labels = {1: 'required', 2: 'optional', 4: 'repeated'}
                flabel = labels[int(ftypeandlabel) >> 8]
                
                field.name = next(my_namer)
                field.number = int(fnumber)
                field.label = label_consts[flabel]
                
                if fdefaultormsg != 'null':
                    if ftype in ('group', 'message'):
                        if '.' in fdefaultormsg:
                            field.type_name = '.' + fdefaultormsg
                            msg_to_referrers[fdefaultormsg].append((field.name, cls + '.' + var, ftype == 'group'))
                            
                            if fdefaultormsg not in msg_path_to_obj: # Classes empty or to be created
                                msg_path_to_obj[fdefaultormsg] = DescriptorProto()
                                msg_path_to_obj[fdefaultormsg].name = fdefaultormsg.split('.')[-1]
                        
                        else:
                            field.type_name = '.' + cls + '.' + fdefaultormsg
                            msg_to_referrers[cls + '.' + fdefaultormsg].append((field.name, cls + '.' + var, ftype == 'group'))
                    
                    else:
                        if fdefaultormsg in consts:
                            fdefaultormsg = consts[fdefaultormsg]

                        parse_default(field, ftype, fdefaultormsg)
                
                else:
                    fdefaultormsg = None
                    
                    if ftype in ('group', 'message'):
                        ftype = 'bytes'

                field.type = type_consts[ftype]

                summary[int(fnumber)] = (flabel, ftype, fdefaultormsg)
        
        msg_path_to_obj[cls + '.' + var] = message
        print(summary)

type_consts = {k.split('_')[1].lower(): v for k, v in FieldDescriptorProto.Type.items()}
label_consts = {k.split('_')[1].lower(): v for k, v in FieldDescriptorProto.Label.items()}

if __name__ == '__main__':
    extractor_main('jar_extract')
