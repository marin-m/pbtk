#!/usr/bin/env python3

from xml.dom.minidom import parseString
from subprocess import run, PIPE
from json import dumps, loads
from base64 import b64encode
from zipfile import ZipFile
from zlib import decompress
from binascii import crc32
from sys import float_info
from struct import unpack
from pathlib import Path
from io import BytesIO

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
    protoc,
    transports,
)

import gi

gi.require_version('WebKit', '6.0')
gi.require_version('Gtk', '4.0')
gi.require_version('Pango', '1.0')
gi.require_version('Adw', '1')
gi.require_version('Soup', '3.0')

from gi.repository import Adw, Gio, GObject, Pango, GLib, WebKit, Soup, Gtk
from gi.repository.WebKit import WebView


class ProtoRowFieldName(Gtk.Box):
    __gtype_name__ = 'ProtoRowFieldName'

    checkbox = GObject.Property(type=Gtk.CheckButton)
    label = GObject.Property(type=Gtk.Label)

    _item: ProtobufItem = None
    _list_row: Gtk.TreeListRow = None

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)

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

    http_session: Soup.Session
    http_cancellable: Gio.Cancellable = None

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

    fuzzer_preview_html: WebKit.WebView = Gtk.Template.Child()
    fuzzer_preview_buffer: Gtk.TextBuffer = Gtk.Template.Child()

    extra_data_page: Adw.ViewStackPage = Gtk.Template.Child()

    proto_model_selection: Gtk.NoSelection = Gtk.Template.Child()
    proto_items = GObject.Property(type=Gio.ListStore)  # of ProtobufItem

    fuzzer_samples_combo_box: Gtk.DropDown = Gtk.Template.Child()
    fuzzer_samples_list: Gio.ListStore = Gtk.Template.Child()

    def __init__(self):
        super().__init__()

        self.http_session = Soup.Session.new()

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

        self.fuzzer_preview_html.load_uri('about:blank')
        self.fuzzer_preview_buffer.set_text('')

        self.update_fuzzer()

    def update_fuzzer(self):
        request: Soup.Message = self.transport.create_request(
            self.pb_request, self.protocol_specific_params
        )

        # ^ ⚠️ THE OBJECT MODEL FOR protocol_specific_params
        #    SHOULD BE TRANSPOSED TOO

        def on_recv(http_session: Soup.Session, result: Gio.AsyncResult):
            response: bytes = self.http_session.send_and_read_finish(
                result
            ).get_data()

            response_headers: dict[str, str] = {}

            def process_header(key, value):
                response_headers[key] = value

            request.get_response_headers().foreach(process_header)

            response_url: str = request.get_uri().to_string()

            content_type: str = (
                request.get_response_headers().get_content_type()[0]
            )

            # ⚠️ WIP adaptation:

            meta = '%s %d %08x\n%s' % (
                content_type,
                len(response),
                crc32(response) & 0xFFFFFFFF,
                response_url,
            )
            self.fuzzer_preview_buffer.set_text(meta, -1)

            self.update_frame(
                response, response_url, content_type, self.pb_response
            )

        if self.http_cancellable:
            self.http_cancellable.cancel()
        self.http_cancellable = Gio.Cancellable.new()
        self.http_session.send_and_read_async(
            request, GLib.PRIORITY_DEFAULT, self.http_cancellable, on_recv
        )

    def update_frame(
        self, data: bytes, url: str, mime: str, pbresp: Message | None = None
    ):

        out_mime = 'text/plain; charset=utf-8'

        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            text = data.decode('ibm850')

        # self.fuzzer_preview_html.load_html(response, response_url)

        if 'image' in mime:
            out_mime = mime

        elif 'html' in mime:
            if '/embed' in url:
                text = text.replace(
                    '<head>', '<head><script>opener=1</script>'
                )
            out_mime = 'text/html; charset=utf-8'
            data = text

        elif 'json' in mime:
            if text.startswith(")]}'\n"):
                text = text[5:]
            if text.endswith('/*""*/'):
                text = text[:-6]

            text = (
                text.replace('[,', '[null,')
                .replace(',]', ',null]')
                .replace(',,', ',null,')
                .replace(',,', ',null,')
            )

            try:
                data = dumps(loads(text), indent=4)
            except Exception:
                pass

        elif 'protobuf' in mime:
            data = self.parse_protobuf(data, pbresp)

        elif 'kmz' in mime:
            with ZipFile(BytesIO(data)) as fd:
                if fd.namelist() == ['doc.kml']:
                    data = parseString(fd.read('doc.kml')).toprettyxml(
                        indent='    '
                    )
                else:
                    data = '\n'.join(fd.namelist())

        elif data.startswith(b'XHR1'):
            data = BytesIO(data[4:])
            out = b''

            while True:
                header = data.read(6)
                if not header:
                    break
                size, index = unpack('>IBx', header)

                dec = bytes([i ^ 0x9B for i in data.read(size - 2)])
                if dec.startswith(b'\x78\x9c'):
                    dec = decompress(dec)

                out += b'%d %s\n' % (index, b'-' * 15)
                out += self.parse_protobuf(dec, pbresp)

            data = out

        elif 'text/' in mime:
            pass

        else:
            for key in (0x9B, 0x5F):
                dec = bytes([i ^ key for i in data])

                try:
                    dec = decompress(dec, -15)
                except Exception:
                    try:
                        dec = decompress(dec)
                    except Exception:
                        pass

                dec = self.parse_protobuf(dec, pbresp)
                if dec:
                    break

            if not dec:
                # ⚠️ We shouldn't use an external subprocess like this
                dec = run(['hexdump', '-C'], input=data, stdout=PIPE).stdout

            data = dec[:100000]

        if isinstance(data, str):
            data = data.encode('utf8')

        """
        # This should be the correct way to go
        # with but it doesn't seem to load
        # correctly raw images:
        self.fuzzer_preview_html.load_bytes(
            GLib.Bytes.new(data), None, out_mime, url
        )
        """

        self.fuzzer_preview_html.load_uri(
            'data:%s;base64,%s' % (out_mime, b64encode(data).decode('utf-8'))
        )

    def parse_protobuf(self, data, pbresp):
        if pbresp:
            try:
                return str(pbresp.FromString(data)).encode('utf8')
            except Exception:
                pass
        return run(
            [protoc, '--decode_raw'], input=data, stdout=PIPE, stderr=PIPE
        ).stdout

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
