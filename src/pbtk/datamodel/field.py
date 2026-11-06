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

    is_message: bool
    is_required: bool
    is_repeated: bool

    field_name = GObject.Property(
        type=str
    )  # ⚠️ TODO this should be editable eventually...
    proto_id = GObject.Property(type=int)
    type_txt = GObject.Property(type=str)

    value = GObject.Property(type=object)
    is_set = GObject.Property(type=bool, default=False)
    expanded = GObject.Property(type=bool, default=False)

    def __init__(self, desc: FieldDescriptor, path: list[str]):
        super().__init__()

        self.desc = desc
        self.path = path

        self.is_message = desc.cpp_type == desc.CPPTYPE_MESSAGE
        self.is_required = desc.label == desc.LABEL_REQUIRED
        self.is_repeated = desc.label == desc.LABEL_REPEATED

        self.field_name = desc.full_name.rsplit('.', 1).pop()
        self.proto_id = desc.number
        self.type_txt = TYPE_NAME_LUT[desc.type]

        if desc.type == desc.CPPTYPE_STRING:
            self.value = desc.default_value or False

        elif desc.cpp_type == desc.CPPTYPE_STRING:
            # ⚠️ ⚠️ FIXME: GTK+ is unlikely to accept bytes here
            self.value = desc.default_value or (
                '' if desc.type != desc.TYPE_BYTES else b''
            )

        elif desc.cpp_type in (desc.CPPTYPE_DOUBLE, desc.CPPTYPE_FLOAT):
            self.value = desc.default_value or 0.0

        elif not self.is_message:
            self.value = desc.default_value or 0

    def get_children(self):
        """
        The list of children is loaded lazily only
        when the current node is visible in the
        GTK+ tree view.
        """

        if not self.is_message:
            return None

        if not self.children:
            self.children = Gio.ListStore.new(ProtobufItem)
            for child in self.desc.message_type.fields:
                self.children.append(
                    ProtobufItem(child, self.path + [child.full_name])
                )

        return self.children
