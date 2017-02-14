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

types_enc = {
    fd.TYPE_BYTES: "B",
    fd.TYPE_BOOL: "b",
    fd.TYPE_DOUBLE: "d",
    fd.TYPE_ENUM: "e",
    fd.TYPE_FLOAT: "f",
    fd.TYPE_SFIXED32: "g",
    fd.TYPE_SFIXED64: "h",
    fd.TYPE_INT32: "i",
    fd.TYPE_INT64: "j",
    fd.TYPE_MESSAGE: "m",
    fd.TYPE_SINT32: "n",
    fd.TYPE_SINT64: "o",
    fd.TYPE_STRING: "s",
    fd.TYPE_UINT32: "u",
    fd.TYPE_UINT64: "v",
    fd.TYPE_FIXED32: "x",
    fd.TYPE_FIXED64: "y"
}

def proto_url_encode(pbmsg, sep='!'):
    return sep.join(produce([''] * (sep == '!'), pbmsg, sep))

def produce(obj, pb, sep):
    for ds, val in pb.ListFields():
        for val in (val if ds.label == ds.LABEL_REPEATED else [val]):
            if ds.type == ds.TYPE_MESSAGE:
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
    pass
