from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.message import Message
from gi.repository import GObject, Gio
from typing import Self


TYPE_NAME_LUT: dict[int, str] = {
    1: 'double',
    2: 'float',
    3: 'int64',
    4: 'uint64',
    5: 'int32',
    6: 'fixed64',
    7: 'fixed32',
    8: 'bool',
    9: 'string',
    10: 'group',
    11: '',
    12: 'bytes',
    13: 'uint32',
    14: 'enum',
    15: 'sfixed32',
    16: 'sfixed64',
    17: 'sint32',
    18: 'sint64',
}

class ProtobufItem(GObject.Object):
    __gtype_name__ = 'ProtobufItem'

    children = GObject.Property(type=Gio.ListStore)  # of ProtobufItem

    desc: FieldDescriptor
    path: list[str]

    field_name = GObject.Property(type=str)  # ⚠️ TODO this should be editable eventually...
    type_txt = GObject.Property(type=str)

    def __init__(self, desc: FieldDescriptor, path: list[str]):
        super().__init__()

        self.desc = desc
        self.path = path

        self.field_name = desc.full_name.rsplit('.', 1).pop()
        self.type_txt = TYPE_NAME_LUT[desc.type]

        pass  # ⚠️ XX WIP

    def get_children(self):

        if not self.children and self.desc.message_type:
            self.children = Gio.ListStore.new(ProtobufItem)
            for child in self.desc.message_type.fields:
                self.children.append(
                    ProtobufItem(child, self.path + [child.full_name])
                )

        return self.children
