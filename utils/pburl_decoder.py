#!/usr/bin/python3
#-*- encoding: Utf-8 -*-
from google.protobuf.descriptor import FieldDescriptor as fd
from base64 import urlsafe_b64decode, urlsafe_b64encode
from urllib.parse import quote, unquote
from warnings import warn
from re import match

"""
    This file contains encoding/decoding routines for the serialization
    used for Protobuf data in Google Maps' private and public API URLs.
    
    A payload meant for private API will look like this:
    !3m1!4b1!4m20!4m19!1m5!1m1!1s0x1e955fe737bd22e5:0xf5b813675e007ba8!2m2!1d28.3023579!2d-25.7297871!1m5!1m1!1s0x1e955e5c875906fd:0xa65176214cdebc80!2m2!1d28.3374283!2d-25.7657075!1m5!1m1!1s0x1e9560c06dba5b73:0x57122f60632be1a1!2m2!1d28.274954!2d-25.7832822!3e0
    
    Data for the public API will be the same, except the separator is "&"
    instead of "!" and string encoding somewhat differs.
"""

types_dec = {
    "B": fd.TYPE_BYTES,
    "b": fd.TYPE_BOOL,
    "d": fd.TYPE_DOUBLE,
    "e": fd.TYPE_ENUM,
    "f": fd.TYPE_FLOAT,
    "g": fd.TYPE_SFIXED32,
    "h": fd.TYPE_SFIXED64,
    "i": fd.TYPE_INT32,
    "j": fd.TYPE_INT64,
    "m": fd.TYPE_MESSAGE,
    "n": fd.TYPE_SINT32,
    "o": fd.TYPE_SINT64,
    "s": fd.TYPE_STRING,
    "u": fd.TYPE_UINT32,
    "v": fd.TYPE_UINT64,
    "x": fd.TYPE_FIXED32,
    "y": fd.TYPE_FIXED64,
    "z": "base64_string"
}

def proto_url_decode(pburl, pbdesc, sep='!'):
    if pburl:
        consume(pburl.strip(sep).split(sep), pbdesc, sep)

def consume(obj, pb, sep):
    while obj:
        field = obj.pop(0)
        index, type_, val = match('(\d+)(\w)(.*)', field).groups()
        type_ = types_dec[type_]
        
        if int(index) not in pb.DESCRIPTOR.fields_by_number:
            warn('Unknown index: !' + field)
            if type_ == fd.TYPE_MESSAGE:
                del obj[:int(val)]
            continue
        
        field = pb.DESCRIPTOR.fields_by_number[int(index)]
        repeated = field.label == field.LABEL_REPEATED
        field = field.name
        
        if type_ == fd.TYPE_MESSAGE:
            if not repeated:
                getattr(pb, field).SetInParent()
                consume(obj[:int(val)], getattr(pb, field), sep)
            else:
                consume(obj[:int(val)], getattr(pb, field).add(), sep)
            
            del obj[:int(val)]
            continue
        
        elif type_ == fd.TYPE_STRING:
            if sep == '!':
                val = val.replace('*21', '!').replace('*2A', '*')
            else:
                val = unquote(val)
        
        elif type_ == fd.TYPE_BYTES:
            val = urlsafe_b64decode(val + '=' * (-len(val) % 4))
        elif type_ == "base64_string":
            val = urlsafe_b64decode(val + '=' * (-len(val) % 4)).decode('utf8')
        
        elif type_ == fd.TYPE_BOOL:
            val = bool(int(val))
        
        elif type_ in (fd.TYPE_DOUBLE, fd.TYPE_FLOAT):
            val = float(val)
        else:
            val = int(val)
        
        if not repeated:
            setattr(pb, field, val)
        else:
            getattr(pb, field).append(val)

"""
    Same, with encoding instead of decoding.
"""

types_enc = {v: k for k, v in types_dec.items()}

def proto_url_encode(pbmsg, sep='!'):
    return sep.join(produce([''] * (sep == '!'), pbmsg, sep))

def produce(obj, pb, sep):
    for ds, val in pb.ListFields():
        for val in (val if ds.label == ds.LABEL_REPEATED else [val]):
            
            if ds.cpp_type == ds.CPPTYPE_MESSAGE:
                origlen = len(obj)
                produce(obj, val, sep)
                obj.insert(origlen, '%dm%d' % (ds.number, len(obj) - origlen))
                continue
            
            elif ds.type == ds.TYPE_STRING:
                if sep == '!':
                    val = val.replace('*', '*2A').replace('!', '*21')
                else:
                    val = quote(val, safe='~()*!.\'')
            
            elif ds.type == ds.TYPE_BYTES:
                val = urlsafe_b64encode(val).decode('ascii').strip('=')
            
            elif ds.type == ds.TYPE_BOOL:
                val = int(val)
            
            obj.append('%d%s%s' % (ds.number, types_enc[ds.type], val))
    
    return obj

if __name__ == '__main__':
    from argparse import ArgumentParser
    from common import load_proto_msgs

    parser = ArgumentParser(description='Decode a JsProtoUrl text message, providing a .proto.')
    parser.add_argument('pburl_data')
    parser.add_argument('proto_file')
    parser.add_argument('proto_msg_name', nargs='?')
    args = parser.parse_args()
    
    sep = '!' if args.pburl_data[0] == '!' else '&'
    
    msg = None
    for name, cls in load_proto_msgs(args.proto_file):
        if not args.proto_msg_name or args.proto_msg_name == name:
            msg = cls()
            break
    if not msg:
        raise ValueError('Provided message name was not found in .proto.')
    
    proto_url_decode(args.pburl_data, msg, sep)
    
    print(msg)
