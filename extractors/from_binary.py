#!/usr/bin/python3
#-*- encoding: Utf-8 -*-
from google.protobuf.descriptor_pb2 import FileDescriptorProto
from google.protobuf.internal.decoder import _DecodeVarint

from os.path import dirname, realpath
__import__('sys').path.append(dirname(realpath(__file__)) + '/..')
from utils.common import register_extractor, extractor_main
from utils.descpb_to_proto import descpb_to_proto

"""
    This script extracts Protobufs metadata embedded into an executable
    (i.e a compiled C++ program, a JNI from an Android application).
    
    Metadata embedding is done at [1], serializing the [2] structure.
    
    Another implementation of this exists at [3] but it scans the file
    in an undesirable way (bruteforcing the length of messages rather
    than calculating it, also failing part of time).
    
    [1] https://github.com/google/protobuf/blob/15a15/src/google/protobuf/compiler/cpp/cpp_file.cc#L693
    [2] https://github.com/google/protobuf/blob/bb77c/src/google/protobuf/descriptor.proto#L59
    [3] https://github.com/sysdream/Protod/blob/master/protod
    
    Usage: ./from_binary.py <infile> [<outdir>]
"""

@register_extractor(name = 'from_binary',
                    desc = 'Extract Protobuf metadata from binary file (*.dll, *.so...)')
def walk_binary(binr):
    if type(binr) == str:
        with open(binr, 'rb') as fd:
            binr = fd.read()
    
    # Search for:
    # ".proto" or ".protodevel", as part of the "name" (1) field
    cursor = 0
    while cursor < len(binr):
        cursor = binr.find(b'.proto', cursor)
        
        if cursor == -1:
            break
        cursor += len('.proto')
        cursor += (binr[cursor:cursor + 5] == b'devel') * 5
        
        # Search back for the (1, length-delimited) marker
        start = binr.rfind(b'\x0a', max(cursor - 1024, 0), cursor)
        
        if start > 0 and binr[start - 1] == 0x0a == (cursor - start - 1):
            start -= 1
        
        # Check whether length byte is coherent
        if start == -1:
            continue
        varint, end = _DecodeVarint(binr, start + 1)
        if cursor - end != varint:
            continue
        
        # Look just after for subsequent markers
        tags = b'\x12\x1a\x22\x2a\x32\x3a\x42\x4a\x50\x58\x62'
        if binr[cursor] not in tags:
            continue
        
        while cursor < len(binr) and binr[cursor] in tags:
            tags = tags[tags.index(binr[cursor]):]
            
            varint, end = _DecodeVarint(binr, cursor + 1)
            cursor = end + varint * (binr[cursor] & 0b111 == 2)
        
        # Parse descriptor
        proto = FileDescriptorProto()
        proto.ParseFromString(binr[start:cursor])
        
        # Convert to ascii
        yield descpb_to_proto(proto)

if __name__ == '__main__':
    extractor_main('from_binary')
