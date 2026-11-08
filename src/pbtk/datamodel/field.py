from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.message import Message
from gi.repository import GObject, Gio
from typing import Self


class ExtraDataItem(GObject.Object):
    __gtype_name__ = 'ExtraDataItem'

    key = GObject.Property(type=str)
    value = GObject.Property(type=str)

    def __init__(self, key: str, value: str):
        super().__init__()

        self.key = key
        self.value = value


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

    is_set = GObject.Property(type=bool, default=False)
    expanded = GObject.Property(type=bool, default=False)

    @staticmethod
    def new(desc: FieldDescriptor, path: list[str]):
        is_message = desc.cpp_type == desc.CPPTYPE_MESSAGE

        if not is_message:
            if desc.type == desc.TYPE_BOOL:
                return ProtobufItemBool(desc, path)

            elif desc.cpp_type == desc.CPPTYPE_STRING:
                # ⚠️ ⚠️ GTK+ is unlikely to accept bytes here
                if desc.type != desc.TYPE_BYTES:
                    return ProtobufItemString(desc, path)
                else:
                    return ProtobufItemBytes(desc, path)

            elif desc.cpp_type in (desc.CPPTYPE_DOUBLE, desc.CPPTYPE_FLOAT):
                return ProtobufItemFloat(desc, path)

            else:
                return ProtobufItemInt(desc, path)

        else:
            return ProtobufItemMessage(desc, path)

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

    def get_children(self, fuzzer_window):
        """
        The list of children is loaded lazily only
        when the current node is visible in the
        GTK+ tree view.
        """

        if not self.is_message:
            return None

        if not self.children:
            was_initing = fuzzer_window.initing_values

            if not was_initing:
                fuzzer_window.initing_values = True

            self.children = Gio.ListStore.new(ProtobufItem)
            for child in self.desc.message_type.fields:
                node = ProtobufItem.new(child, self.path + [child.full_name])
                self.children.append(node)
                node.connect('notify::is-set', fuzzer_window.node_value_set)
                node.connect('notify::value', fuzzer_window.node_value_changed)

            if not was_initing:
                fuzzer_window.initing_values = False

        return self.children


class ProtobufItemMessage(ProtobufItem):
    value = GObject.Property(type=int)


class ProtobufItemFloat(ProtobufItem):
    value = GObject.Property(type=float)

    def __init__(self, desc: FieldDescriptor, path: list[str]):
        super().__init__(desc, path)

        self.value = desc.default_value or 0.0


class ProtobufItemBool(ProtobufItem):
    value = GObject.Property(type=bool, default=False)

    def __init__(self, desc: FieldDescriptor, path: list[str]):
        super().__init__(desc, path)

        self.value = desc.default_value or False


class ProtobufItemInt(ProtobufItem):
    value = GObject.Property(type=int)

    def __init__(self, desc: FieldDescriptor, path: list[str]):
        super().__init__(desc, path)

        self.value = desc.default_value or 0


class ProtobufItemString(ProtobufItem):
    value = GObject.Property(type=str)

    def __init__(self, desc: FieldDescriptor, path: list[str]):
        super().__init__(desc, path)

        self.value = desc.default_value or ''


class ProtobufItemBytes(ProtobufItem):
    value = GObject.Property(type=str)

    def __init__(self, desc: FieldDescriptor, path: list[str]):
        super().__init__(desc, path)

        self.value = (desc.default_value or b'').decode('utf-8')
