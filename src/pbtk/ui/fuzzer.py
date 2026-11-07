#!/usr/bin/env python3

from pathlib import Path
from sys import float_info

# Monkey-patch map object creation (suppressing the map_entry option
# from generated classes),
from google.protobuf import descriptor

descriptor._ParseOptions = lambda msg, data: msg.FromString(
    data.replace(b'8\001', b'')
)

# Monkey-patch enum value checking,
from google.protobuf.internal import type_checkers

type_checkers.SupportsOpenEnums = lambda x: True

# And then do Protobuf imports
from google.protobuf.internal.type_checkers import _VALUE_CHECKERS
from google.protobuf.message import Message

from pbtk.datamodel.transport import Transport, TransportDefinition
from pbtk.datamodel.endpoint import RecordedSampleRow
from pbtk.datamodel.field import ProtobufItem
from pbtk.utils.common import (
    BASE_PATH,
    ProtoMessageDeclaration,
    load_proto_msgs,
    transports,
)

import gi

gi.require_version('WebKit', '6.0')
gi.require_version('Gtk', '4.0')
gi.require_version('Pango', '1.0')
gi.require_version('Adw', '1')
gi.require_version('Soup', '3.0')

from gi.repository import Adw, Gio, GObject, Pango, Soup, Gtk
from gi.repository.WebKit import WebView


class ProtoRowFieldName(Gtk.Box):
    __gtype_name__ = 'ProtoRowFieldName'

    checkbox = GObject.Property(type=Gtk.CheckButton)
    label = GObject.Property(type=Gtk.Label)

    http_session: Soup.Session

    _item: ProtobufItem = None
    _list_row: Gtk.TreeListRow = None

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)

        self.http_session = Soup.Session.new()

        self.set_spacing(4)

        self.checkbox = Gtk.CheckButton.new()
        self.append(self.checkbox)

        self.label = Gtk.Label.new('')
        self.append(self.label)

        # ⚠️ TODO there should be click/hover handlers
        #    applied over the row nearby

    @GObject.Property(type=Gtk.TreeListRow)
    def list_row(self):
        return self._list_row

    @list_row.setter
    def list_row(self, list_row: Gtk.TreeListRow):
        # ⚠️ Unbind property whenever it changes?
        self._list_row = list_row

    @GObject.Property(type=ProtobufItem)
    def item(self):
        return self._item

    @item.setter
    def item(self, item: ProtobufItem):
        # ⚠️ Unbind property whenever it changes?
        self._item = item

        self.label.set_label(
            item.field_name + ('+' if item.is_repeated else '')
        )
        self.checkbox.set_visible(not item.is_required)

        item.bind_property(
            'is_set', self.checkbox, 'active', GObject.BindingFlags.SYNC_CREATE
        )

        item.bind_property('expanded', self.list_row, 'expanded')


class ProtoRowFieldValue(Gtk.Box):
    __gtype_name__ = 'ProtoRowFieldValue'

    child = GObject.Property(type=Gtk.Widget)
    _item: ProtobufItem = None

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)

        # ⚠️ TODO there should be click/hover handlers
        #    applied over the row nearby

    @GObject.Property(type=ProtobufItem)
    def item(self):
        return self._item

    @item.setter
    def item(self, item: ProtobufItem):
        self._item = item

        desc = self.item.desc

        if self.child:
            self.remove(self.child)
            self.child = None

        if self.item.is_message:
            pass

        elif desc.type == desc.TYPE_BOOL:
            self.child = Gtk.CheckButton.new()

        elif desc.cpp_type == desc.CPPTYPE_STRING:
            self.child = Gtk.Entry.new()

        elif desc.cpp_type == desc.CPPTYPE_FLOAT:
            self.child = Gtk.SpinButton.new_with_range(-3.4e38, 3.4e38, 1.0)
            self.child.set_digits(7)

        elif desc.cpp_type == desc.CPPTYPE_DOUBLE:
            self.child = Gtk.SpinButton.new_with_range(
                float_info.min, float_info.max, 1.0
            )
            self.child.set_digits(17)

        else:
            cpp_type = (
                desc.cpp_type
                if desc.cpp_type != desc.CPPTYPE_ENUM
                else desc.CPPTYPE_INT32
            )
            self.child = Gtk.SpinButton.new_with_range(
                _VALUE_CHECKERS[cpp_type]._MIN,
                _VALUE_CHECKERS[cpp_type]._MAX,
                1,
            )

        if isinstance(self.child, Gtk.SpinButton):
            self.child.set_update_policy(Gtk.SpinButtonUpdatePolicy.IF_VALID)
            self.item.bind_property(
                'value',
                self.child,
                'value',
                GObject.BindingFlags.BIDIRECTIONAL
                | GObject.BindingFlags.SYNC_CREATE,
                lambda _binding, value: value,
                lambda _binding, value: value,
            )

        elif isinstance(self.child, Gtk.Entry):
            self.item.bind_property(
                'value',
                self.child.get_buffer(),
                'text',
                GObject.BindingFlags.BIDIRECTIONAL
                | GObject.BindingFlags.SYNC_CREATE,
                lambda _binding, value: value,
                lambda _binding, value: value,
            )

        elif isinstance(self.child, Gtk.CheckButton):
            self.child.set_active(desc.default_value or False)
            self.item.bind_property(
                'value',
                self.child,
                'active',
                GObject.BindingFlags.BIDIRECTIONAL
                | GObject.BindingFlags.SYNC_CREATE,
                lambda _binding, value: value,
                lambda _binding, value: value,
            )

        if self.child:
            self.append(self.child)


@Gtk.Template(
    resource_path='/re/fossplant/pbtk/templates/fuzzer-autogenerated.ui'
)
class FuzzerWindow(Adw.Window):
    __gtype_name__ = 'FuzzerWindow'

    action_group = GObject.Property(type=Gio.ActionGroup)

    endpoint: dict
    transport_meta: TransportDefinition
    transport: Transport

    base_url: str
    pb_param: str | None = None

    protocol_specific_params: dict

    current_req_proto: Path
    current_req_proto_msgs: list[ProtoMessageDeclaration]
    pb_request: Message

    current_resp_proto: Path = None
    current_resp_proto_msgs: list[ProtoMessageDeclaration] = None
    pb_response: Message = None

    extra_data_page: Adw.ViewStackPage = Gtk.Template.Child()

    proto_model_selection: Gtk.NoSelection = Gtk.Template.Child()
    proto_items = GObject.Property(type=Gio.ListStore)  # of ProtobufItem

    fuzzer_samples_combo_box: Gtk.DropDown = Gtk.Template.Child()
    fuzzer_samples_list: Gio.ListStore = Gtk.Template.Child()

    def __init__(self):
        super().__init__()

        self.proto_items = Gio.ListStore.new(ProtobufItem)

        self.proto_model_selection.set_model(
            Gtk.TreeListModel.new(
                self.proto_items,
                passthrough=False,
                autoexpand=False,
                create_func=lambda item: item.get_children(),
            )
        )

        self.connect_actions()

    def connect_actions(self):

        self.action_group = Gio.SimpleActionGroup.new()

        self.insert_action_group('win', self.action_group)

        def open_proto_definition(*args):
            proto_path = Gio.File.new_for_path(str(self.current_req_proto))
            Gtk.FileLauncher.new(proto_path).launch(self, None, None)

        self.add_simple_action('open-proto-definition', open_proto_definition)

    def add_simple_action(self, name, callback, param_type=None):

        action = Gio.SimpleAction.new(name, param_type)
        action.connect('activate', callback)
        self.add_action(action)

    def add_simple_action(self, name, callback, param_type=None):

        action = Gio.SimpleAction.new(name, param_type)
        action.connect('activate', callback)
        self.action_group.add_action(action)

    def load(self, endpoint: dict, sample_id: int = 0):

        self.endpoint = endpoint

        self.base_url = endpoint['request']['url']
        self.pb_param = endpoint['request'].get('pb_param')

        self.transport_meta = transports[endpoint['request']['transport']]
        self.transport = self.transport_meta.transport_class(
            self.pb_param, self.base_url
        )

        self.extra_data_page.set_title(self.transport.ui_tab)

        # Load Protobuf request message

        self.current_req_proto = (
            BASE_PATH / 'protos' / endpoint['request']['proto_path']
        )

        self.current_req_proto_msgs = list(
            load_proto_msgs(self.current_req_proto)
        )
        self.pb_request = next(
            (
                item
                for item in self.current_req_proto_msgs
                if item.name == endpoint['request']['proto_msg']
            ),
            None,
        ).definition()

        # Load Protobuf response message, if any

        if (
            endpoint.get('response')
            and endpoint['response']['format'] == 'raw_pb'
        ):
            self.current_resp_proto = (
                BASE_PATH / 'protos' / endpoint['response']['proto_path']
            )

            self.current_resp_proto_msgs = list(
                load_proto_msgs(self.current_resp_proto)
            )
            self.pb_response = next(
                (
                    item
                    for item in self.current_resp_proto_msgs
                    if item.name == endpoint['response']['proto_msg']
                ),
                None,
            ).definition()

        # Load list of samples

        with self.fuzzer_samples_list.freeze_notify():
            self.fuzzer_samples_list.remove_all()

            for raw_sample_data in endpoint['request'].get('samples', []):
                readable_sample_data = (
                    raw_sample_data[self.pb_param]
                    if self.pb_param
                    else str(raw_sample_data)
                )

                sample_item = RecordedSampleRow(
                    raw_sample_data, readable_sample_data
                )

                self.fuzzer_samples_list.append(sample_item)

        # Load currently selected sample into
        # self.pb_request + self.protocol_specific_params

        sample = ''
        if endpoint['request'].get('samples'):
            sample = endpoint['request']['samples'][sample_id]

        self.protocol_specific_params = self.transport.load_sample(
            sample, self.pb_request
        )

        # Present fuzzer window

        self.present()

        pass  # ⚠️ 🪧 WIP... (importing code from pbtk._ui_legacy.gui.launch_fuzzer)

        # Get initial data into the Protobuf tree view

        self.proto_items.remove_all()

        for desc in self.pb_request.DESCRIPTOR.fields:
            self.proto_items.append(ProtobufItem(desc, [desc.full_name]))

        self.use_sample_values(self.pb_request, self.proto_items)

        # ⚠️ ➡️ WIP

        # Do the same for transport-specific data

        # ⚠️ ➡️ TODO

        """
            XX WIP: TRANSPOSE ➡️ ⚠️

            self.fuzzer.frame.setUrl(QUrl('about:blank'))
            self.update_fuzzer()

            def update_fuzzer(self):
                resp = self.transport.perform_request(self.pb_request, self.get_params)
                # ^ ⚠️ USE GLIB/SOUP FOR NETWORKING?
                # OR A THREAD?
                # ℹ️ 🪧 SOUP SOUNDS REASONABLE AS ONLY THE GUI USES THIS

                # ^ ⚠️ THE OBJECT MODEL FOR GET_PARAMS SHOULD BE TRANSPOSED TOO

                data, text, url, mime = (
                    resp.content,
                    resp.text,
                    resp.url,
                    resp.headers['Content-Type'].split(';')[0],
                )

                meta = '%s %d %08x\n%s' % (
                    mime,
                    len(data),
                    crc32(data) & 0xFFFFFFFF,
                    resp.url,
                )
                self.fuzzer.urlField.setText(meta)

                self.fuzzer.frame.update_frame(
                    data, text, url, mime, getattr(self, 'pb_resp', None)
                )
        """

    """
        Parsing and rendering a Protobuf message parsed from
        sample data to our tree model
    """

    def use_sample_values(
        self, msg: Message, tree_fields: Gio.ListStore[ProtobufItem]
    ):

        for field_desc, field_val in msg.ListFields():
            for node_index, node in reversed(list(enumerate(tree_fields))):
                if node.desc.number == field_desc.number:
                    break
            else:
                raise ValueError(
                    'Item not found in Protobuf message: %r' % field_val
                )

            node.is_set = True

            if field_desc.label == field_desc.LABEL_REPEATED:
                for instance in field_val:
                    if field_desc.cpp_type == field_desc.CPPTYPE_MESSAGE:
                        node.expanded = True
                        self.use_sample_values(instance, node.get_children())

                    else:
                        node.value = instance

                    duplicate = ProtobufItem(node.desc, node.path)
                    tree_fields.insert(node_index + 1, duplicate)

            else:
                if field_desc.cpp_type == field_desc.CPPTYPE_MESSAGE:
                    node.expanded = True
                    self.use_sample_values(field_val, node.get_children())

                else:
                    node.value = field_val
