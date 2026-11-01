from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.message import Message
from gi.repository import GObject, Gio
from typing import Self


class ProtobufItem(GObject.Object):
    children = GObject.Property(type=Gio.ListStore)  # of ProtobufItem
    desc: FieldDescriptor
    path: list[str]

    def __init__(self, desc: FieldDescriptor, path: list[str]):
        super().__init__()

        self.desc = desc
        self.path = path

        pass  # ⚠️ XX WIP

    def get_children(self):

        if not self.children:
            self.children = Gio.ListStore.new(ProtobufItem)
            for child in self.desc.message_type.fields:
                self.children.append(
                    ProtobufItem(child, self.path + [child.full_name])
                )

        return self.children
