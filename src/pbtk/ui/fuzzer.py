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
from re import match

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
from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.message import Message

from pbtk.datamodel.field import (
    ProtobufItem,
    ProtobufItemEnum,
    ProtobufItemBytes,
    ExtraDataItem,
)
from pbtk.datamodel.transport import Transport, TransportDefinition
from pbtk.datamodel.endpoint import RecordedSampleRow
from pbtk.utils.common import (
    BASE_PATH,
    ProtoMessageDeclaration,
    ProtoFileDescription,
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

from gi.repository import (
    Adw,
    Gio,
    GObject,
    Pango,
    Gdk,
    GLib,
    WebKit,
    Soup,
    Gtk,
)
from gi.repository.WebKit import WebView


class ProtoRowFieldName(Gtk.Box):
    __gtype_name__ = 'ProtoRowFieldName'

    checkbox = GObject.Property(type=Gtk.CheckButton)
    label = GObject.Property(type=Gtk.Label)
    repeated_suffix = GObject.Property(type=Gtk.Label)

    _item: ProtobufItem = None
    _list_row: Gtk.TreeListRow = None

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)

        self.set_spacing(4)

        self.repeated_suffix = Gtk.Label.new('+')
        self.repeated_suffix.set_visible(False)
        self.append(self.repeated_suffix)

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

        if self.checkbox:
            self.remove(self.checkbox)
            self.checkbox = None

        if self.label:
            self.remove(self.label)
            self.label = None

        self.label = Gtk.Label.new('')
        self.prepend(self.label)

        if isinstance(item, ProtobufItemEnum):
            self.set_tooltip_text(item.tooltip)
        else:
            self.set_tooltip_text(None)

        item.bind_property(
            'field_name',
            self.label,
            'label',
            GObject.BindingFlags.SYNC_CREATE,
        )

        self.repeated_suffix.set_visible(item.is_repeated)

        if not item.is_required:
            self.checkbox = Gtk.CheckButton.new()
            self.prepend(self.checkbox)

            item.bind_property(
                'is_set',
                self.checkbox,
                'active',
                GObject.BindingFlags.BIDIRECTIONAL
                | GObject.BindingFlags.SYNC_CREATE,
            )

        item.bind_property('expanded', self.list_row, 'expanded')


class LabelWithOptionalTooltip(Gtk.Label):
    __gtype_name__ = 'LabelWithOptionalTooltip'

    _item: ProtobufItem = None

    @GObject.Property(type=ProtobufItem)
    def item(self):
        return self._item

    @item.setter
    def item(self, item: ProtobufItem):
        self._item = item

        if isinstance(item, ProtobufItemEnum):
            self.set_tooltip_text(item.tooltip)
        else:
            self.set_tooltip_text(None)


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

        if isinstance(item, ProtobufItemEnum):
            self.set_tooltip_text(item.tooltip)
        else:
            self.set_tooltip_text(None)

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
                lambda _binding, value: (
                    value.decode('utf-8')
                    if isinstance(value, bytes)
                    else value
                ),
                lambda _binding, value: value,
            )

        elif isinstance(self.child, Gtk.CheckButton):
            self.item.bind_property(
                'value',
                self.child,
                'active',
                GObject.BindingFlags.BIDIRECTIONAL
                | GObject.BindingFlags.SYNC_CREATE,
            )

        if self.child:
            self.append(self.child)


class ExtraDataRowFieldValue(Gtk.Box):
    __gtype_name__ = 'ExtraDataRowFieldValue'

    child = GObject.Property(type=Gtk.Entry)
    _item: ExtraDataItem = None

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)

        self.child = Gtk.Entry.new()
        self.append(self.child)

        # ⚠️ TODO there should be click/hover handlers
        #    applied over the row nearby

    @GObject.Property(type=ExtraDataItem)
    def item(self):
        return self._item

    @item.setter
    def item(self, item: ExtraDataItem):
        self._item = item

        if self.item:
            self.item.bind_property(
                'value',
                self.child.get_buffer(),
                'text',
                GObject.BindingFlags.BIDIRECTIONAL
                | GObject.BindingFlags.SYNC_CREATE,
            )


@Gtk.Template(
    resource_path='/re/fossplant/pbtk/templates/fuzzer-autogenerated.ui'
)
class FuzzerWindow(Adw.Window):
    __gtype_name__ = 'FuzzerWindow'

    initing_values: bool = False
    processing_user_action: bool = False

    action_group = GObject.Property(type=Gio.ActionGroup)

    http_session: Soup.Session
    http_cancellable: Gio.Cancellable = None

    endpoint: dict = None
    transport_meta: TransportDefinition
    transport: Transport

    base_url: str
    pb_param: str | None = None

    current_req_proto: Path
    current_req_proto_msgs: list[ProtoMessageDeclaration]
    pb_request_type: type[Message]

    current_resp_proto: Path = None
    current_resp_proto_msgs: list[ProtoMessageDeclaration] = None
    pb_response_type: type[Message] = None

    rename_input_dialog: Adw.AlertDialog = Gtk.Template.Child()
    input_rename_entry: Gtk.Entry = Gtk.Template.Child()
    input_rename_buffer: Gtk.EntryBuffer = Gtk.Template.Child()

    add_extra_field_dialog: Adw.AlertDialog = Gtk.Template.Child()
    add_extra_field_entry: Gtk.Entry = Gtk.Template.Child()
    add_extra_field_buffer: Gtk.EntryBuffer = Gtk.Template.Child()

    fuzzer_preview_html: WebKit.WebView = Gtk.Template.Child()
    fuzzer_preview_buffer: Gtk.TextBuffer = Gtk.Template.Child()

    proto_model_selection: Gtk.SingleSelection = Gtk.Template.Child()
    proto_items = GObject.Property(type=Gio.ListStore)  # of ProtobufItem

    extra_data_page: Adw.ViewStackPage = Gtk.Template.Child()
    extra_data_remove: Gtk.Button = Gtk.Template.Child()

    extra_data_model_selection: Gtk.SingleSelection = Gtk.Template.Child()
    extra_data_items: Gio.ListStore[ExtraDataItem] = Gtk.Template.Child()

    fuzzer_samples_combo_box: Gtk.DropDown = Gtk.Template.Child()
    fuzzer_samples_list: Gio.ListStore = Gtk.Template.Child()

    def __init__(self):
        super().__init__()

        # Initialize HTTP session

        self.http_session = Soup.Session.new()

        # Initialize Protobuf items tree model

        self.proto_items = Gio.ListStore.new(ProtobufItem)

        self.proto_model_selection.set_model(
            Gtk.TreeListModel.new(
                self.proto_items,
                passthrough=False,
                autoexpand=False,
                create_func=lambda item: item.get_children(self),
            )
        )

        # Pre-draw URL prompt dialog

        self.rename_input_dialog.add_response('cancel', 'Cancel')
        self.rename_input_dialog.add_response('ok', 'Ok')

        self.rename_input_dialog.set_response_appearance(
            'ok', Adw.ResponseAppearance.SUGGESTED
        )

        # Pre-draw extra field add prompt dialog

        self.add_extra_field_dialog.add_response('cancel', 'Cancel')
        self.add_extra_field_dialog.add_response('ok', 'Ok')

        self.add_extra_field_dialog.set_response_appearance(
            'ok', Adw.ResponseAppearance.SUGGESTED
        )

        # Event callbacks

        def on_sample_selected(*args):
            if (
                not self.initing_values
                and self.fuzzer_samples_combo_box.get_selected_item()
            ):
                self.load(
                    self.endpoint, self.fuzzer_samples_combo_box.get_selected()
                )

        self.fuzzer_samples_combo_box.connect(
            'notify::selected-item', on_sample_selected
        )

        # Connect actions

        self.connect_actions()

    """
    def connect_context_menu(self, XX):
        click_handler = Gtk.GestureClick.new()
        click_handler.set_button(Gdk.BUTTON_SECONDARY)
        click_handler.connect('pressed', touch_closure)
        XX.add_controller(click_handler)
    """

    def connect_actions(self):

        self.action_group = Gio.SimpleActionGroup.new()

        self.insert_action_group('win', self.action_group)

        def open_proto_definition(*args):
            proto_path = Gio.File.new_for_path(str(self.current_req_proto))
            Gtk.FileLauncher.new(proto_path).launch(self, None, None)

        self.add_simple_action('open-proto-definition', open_proto_definition)

        def add_extra_data(*args):

            def on_choose(dialog: Adw.AlertDialog, result: Gio.AsyncResult):
                result = dialog.choose_finish(result)

                text = self.add_extra_field_buffer.get_text()

                if result == 'ok' and text:
                    if not match(r'^[a-zA-Z0-9_%-]+$', text):
                        self.alert_popup(
                            'This is not a valid alphanumeric name.'
                        )
                    else:
                        new_item = ExtraDataItem(text, '')
                        self.extra_data_items.append(new_item)
                        new_item.connect('notify::value', self.update_fuzzer)
                        self.update_fuzzer()

            self.add_extra_field_buffer.set_text('', -1)

            self.add_extra_field_dialog.choose(self, None, on_choose)
            self.add_extra_field_entry.grab_focus()

        self.add_simple_action('add-extra-data', add_extra_data)

        def remove_extra_data(*args):

            if self.extra_data_model_selection.get_selected_item():
                self.extra_data_items.remove(
                    self.extra_data_model_selection.get_selected()
                )
                self.update_fuzzer()

        action = self.add_simple_action('remove-extra-data', remove_extra_data)
        self.extra_data_model_selection.bind_property(
            'selected-item',
            action,
            'enabled',
            GObject.BindingFlags.SYNC_CREATE,
            lambda _binding, value: value is not None,
        )

        self.add_simple_action('prompt-rename', self.prompt_rename)

    def add_simple_action(
        self, name, callback, param_type=None
    ) -> Gio.SimpleAction:
        action = Gio.SimpleAction.new(name, param_type)
        action.connect('activate', callback)
        self.action_group.add_action(action)

        return action

    def load(self, endpoint: dict, sample_id: int = 0):

        if self.initing_values:
            return

        self.initing_values = True
        self.processing_user_action = False

        if endpoint != self.endpoint:
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
            self.pb_request_type = next(
                (
                    item
                    for item in self.current_req_proto_msgs
                    if item.name == endpoint['request']['proto_msg']
                ),
                None,
            ).definition

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
                self.pb_response_type = next(
                    (
                        item
                        for item in self.current_resp_proto_msgs
                        if item.name == endpoint['response']['proto_msg']
                    ),
                    None,
                ).definition

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

        self.endpoint = endpoint

        # Load currently selected sample into
        # initial_pb_request + protocol_specific_params

        initial_pb_request = self.pb_request_type()

        sample = ''
        if endpoint['request'].get('samples'):
            sample = endpoint['request']['samples'][sample_id]

        protocol_specific_params: dict[str, str] = self.transport.load_sample(
            sample, initial_pb_request
        )

        # Present fuzzer window

        self.present()

        # ⚠️ 🪧 WIP... (importing code from pbtk._ui_legacy.gui.launch_fuzzer)

        # Get initial data into the Protobuf tree view

        self.proto_items.remove_all()

        for desc in initial_pb_request.DESCRIPTOR.fields:
            node = ProtobufItem.new(
                desc, None, self.proto_items, [desc.full_name]
            )
            self.proto_items.append(node)
            node.connect('notify::is-set', self.node_value_set)
            node.connect('notify::value', self.node_value_changed)

        self.use_sample_values(initial_pb_request, None, self.proto_items)

        # Do the same for transport-specific data

        self.extra_data_items.remove_all()

        for key, value in protocol_specific_params.items():
            new_item = ExtraDataItem(key, value)
            self.extra_data_items.append(new_item)
            new_item.connect('notify::value', self.update_fuzzer)

        # Load initial view

        self.fuzzer_preview_html.load_uri('about:blank')
        self.fuzzer_preview_buffer.set_text('')

        self.update_fuzzer()

        self.initing_values = False

    def update_fuzzer(self, *args):
        pb_request: Message = self.pb_request_type()

        def consume(pb_msg: Message, item: ProtobufItem):
            if not item.is_set:
                return

            field: FieldDescriptor = pb_msg.DESCRIPTOR.fields_by_number[
                item.proto_id
            ]

            if item.is_message:
                if not item.is_repeated:
                    sub_msg = getattr(pb_msg, field.name)
                else:
                    sub_msg = getattr(pb_msg, field.name).add()
                sub_msg.SetInParent()
                for child in item.get_children(self):
                    consume(sub_msg, child)

            else:
                if not item.is_repeated:
                    setattr(
                        pb_msg,
                        field.name,
                        item.value.encode('utf-8')
                        if isinstance(item, ProtobufItemBytes)
                        else item.value,
                    )
                else:
                    getattr(pb_msg, field.name).append(
                        item.value.encode('utf-8')
                        if isinstance(item, ProtobufItemBytes)
                        else item.value
                    )

        for item in self.proto_items:
            consume(pb_request, item)

        request: Soup.Message = self.transport.create_request(
            pb_request,
            {item.key: item.value for item in self.extra_data_items},
        )

        # ^ ⚠️ THE OBJECT MODEL FOR protocol_specific_params
        #    SHOULD BE TRANSPOSED TOO

        def on_recv(http_session: Soup.Session, result: Gio.AsyncResult):
            try:
                response: bytes = self.http_session.send_and_read_finish(
                    result
                ).get_data()
            except GLib.GError as err:
                if not (
                    err.domain == 'g-io-error-quark'
                    and err.code == Gio.IOErrorEnum.CANCELLED
                ):
                    self.alert_popup(
                        'Could not send network request', err.message
                    )
                return

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

            self.update_frame(response, response_url, content_type)

        if self.http_cancellable:
            self.http_cancellable.cancel()
        self.http_cancellable = Gio.Cancellable.new()
        self.http_session.send_and_read_async(
            request, GLib.PRIORITY_DEFAULT, self.http_cancellable, on_recv
        )

    def update_frame(
        self,
        data: bytes,
        url: str,
        mime: str,
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
            data = self.parse_protobuf(data)

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
                out += self.parse_protobuf(dec)

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

                dec = self.parse_protobuf(dec)
                if dec:
                    break

            if not dec:
                dec = self.hex_dump(data)

            data = dec[:100000]

        if isinstance(data, str):
            data = data.encode('utf8')

        # This should be the correct way to go
        # with but it doesn't seem to load
        # correctly raw images:
        if 'html' in out_mime:
            self.fuzzer_preview_html.load_bytes(
                GLib.Bytes.new(data), None, out_mime, url
            )

        else:
            self.fuzzer_preview_html.load_uri(
                'data:%s;base64,%s'
                % (out_mime, b64encode(data).decode('utf-8'))
            )

    def hex_dump(self, data: bytes) -> str:
        subst_chars = ''.join(
            j if j.isprintable() else '.'
            for j in bytes(range(256)).decode('ibm850')
        )

        raw_buffer = BytesIO(data)
        text_buffer = ''
        while True:
            pos = raw_buffer.tell()
            byte_slice = raw_buffer.read(16)
            if not byte_slice:
                break

            # Write position
            text_buffer += '%08x  ' % pos

            # Write hex data
            for col, char in enumerate(byte_slice):
                if col == 8:
                    text_buffer += ' '
                text_buffer += '%02x ' % char
            for extra_col in range(col + 1, 16):
                if extra_col == 8:
                    text_buffer += ' '
                text_buffer += '   '

            # Write raw data
            text_buffer += ' |'
            for col, char in enumerate(byte_slice):
                text_buffer += subst_chars[char]
            for extra_col in range(col + 1, 16):
                text_buffer += ' '
            text_buffer += '|\n'

        return text_buffer

    def parse_protobuf(self, data: bytes):
        if self.pb_response_type:
            try:
                return str(self.pb_response_type.FromString(data)).encode(
                    'utf8'
                )
            except Exception:
                pass
        return run(
            [protoc, '--decode_raw'], input=data, stdout=PIPE, stderr=PIPE
        ).stdout

    """
        Wheck field name is clicked, offer to rename the field

        In order to rewrite field name in the .proto without discarding
        comments or other information, we'll ask protoc to generate file
        source information [1], that we'll parse and that will give us
        text offset for it.

        [1] https://github.com/google/protobuf/blob/7f3e23/src/google/protobuf/descriptor.proto#L715
    """

    def prompt_rename(self, *args):

        item: ProtobufItem = (
            self.proto_model_selection.get_selected_item().get_item()
        )

        def on_choose(dialog: Adw.AlertDialog, result: Gio.AsyncResult):
            result = dialog.choose_finish(result)

            text = self.input_rename_buffer.get_text()

            if result == 'ok' and text:
                if not match(r'^[a-zA-Z0-9_]+$', text):
                    self.alert_popup('This is not a valid alphanumeric name.')
                else:
                    if self.do_rename(item, text):
                        return
                    self.alert_popup(
                        'Field was not found in .proto, did you edit it elsewhere?'
                    )

        self.input_rename_buffer.set_text(item.field_name, -1)

        self.rename_input_dialog.choose(self, None, on_choose)
        self.input_rename_entry.grab_focus()

    """
        Rename a field contained in a .proto file, returns
        a boolean indicating whether the concerned field
        was found in the original file
    """

    def do_rename(self, item: ProtobufItem, new_name: str) -> bool:
        file_desc: ProtoFileDescription = next(
            load_proto_msgs(self.current_req_proto, True), None
        )
        file_set = file_desc.definition.file

        """
        First, recursively iterate over descriptor fields until we have
        a numeric path that leads to it in the structure, as explained
        in [1] above
        """

        for file_ in file_set:
            field_path = self.find_path_for_field(
                item, file_.message_type, [4], file_.package
            )

            if field_path:
                for location in file_.source_code_info.location:
                    if location.path == field_path:
                        start_line, start_col, end_col = location.span[:3]

                        # Once we have file position information, do
                        # write the new field name in .proto

                        file_path = str(file_desc.file_path / file_.name)
                        with open(file_path) as fd:
                            lines = fd.readlines()
                        assert (
                            lines[start_line][start_col:end_col]
                            == item.field_name
                        )

                        lines[start_line] = (
                            lines[start_line][:start_col]
                            + new_name
                            + lines[start_line][end_col:]
                        )
                        with open(file_path, 'w') as fd:
                            fd.writelines(lines)

                        # Update the name on GUI items corresponding to
                        # this field and its duplicates (if repeated)

                        for node in item.parent_tree:
                            if node.proto_id == item.proto_id:
                                node.field_name = new_name

                        return True

        return False

    def find_path_for_field(
        self, item: ProtobufItem, msg_types: list, path: list, pkg_prefix: str
    ):
        if pkg_prefix:
            pkg_prefix += '.'

        for i, msg in enumerate(msg_types):
            if item.full_name.startswith(pkg_prefix + msg.name + '.'):
                for j, field in enumerate(msg.field):
                    if (
                        pkg_prefix + msg.name + '.' + field.name
                        == item.full_name
                    ):
                        return [*path, i, 2, j, 1]

                return self.find_path_for_field(
                    item, msg.nested_type, [*path, i, 3], pkg_prefix + msg.name
                )

    def alert_popup(self, *args):

        dialog = Adw.AlertDialog.new(*args)
        dialog.add_response('ok', 'Ok')
        dialog.set_default_response('ok')
        dialog.set_close_response('ok')
        dialog.choose(self, None, None)

    """
        Parsing and rendering a Protobuf message parsed from
        sample data to our tree model
    """

    def use_sample_values(
        self,
        msg: Message,
        parent: ProtobufItem | None,
        tree_fields: Gio.ListStore[ProtobufItem],
    ):

        for field_desc, field_val in msg.ListFields():
            for node_index, node in reversed(list(enumerate(tree_fields))):
                if node.desc.number == field_desc.number:
                    break
            else:
                raise ValueError(
                    'Item not found in Protobuf message: %r' % field_val
                )

            if field_desc.label == field_desc.LABEL_REPEATED:
                for instance in field_val:
                    node.is_set = True

                    if field_desc.cpp_type == field_desc.CPPTYPE_MESSAGE:
                        node.expanded = True
                        self.use_sample_values(
                            instance, node, node.get_children(self)
                        )

                    else:
                        node.value = instance

                    node = ProtobufItem.new(
                        node.desc, parent, tree_fields, node.path
                    )
                    tree_fields.insert(node_index + 1, node)
                    node.connect('notify::is-set', self.node_value_set)
                    node.connect('notify::value', self.node_value_changed)

                    node_index += 1

            else:
                node.is_set = True

                if field_desc.cpp_type == field_desc.CPPTYPE_MESSAGE:
                    node.expanded = True
                    self.use_sample_values(
                        field_val, node, node.get_children(self)
                    )

                else:
                    node.value = field_val

    """
        Callback when the value of an individual Protobuf
        node has been changed
    """

    def node_value_changed(self, item: ProtobufItem, spec: GObject.ParamSpec):

        if self.initing_values:
            return

        # Ensure that we're the data source of
        # the value set before firing a
        # Fuzzer state update

        if self.processing_user_action:
            return

        self.processing_user_action = True

        # Check item as newly set if needed

        if item.value and not item.is_set:
            item.is_set = True

        self.processing_user_action = False

        # Log data change

        print(
            '⚠️⚠️ WIP Protobuf data changed =>',
            item.path,
            '/',
            item.field_name,
            '/',
            item.value,
        )

        self.update_fuzzer()

    def node_value_set(self, item: ProtobufItem, spec: GObject.ParamSpec):

        if self.initing_values:
            return

        # Do deferred triggers:

        was_processing = self.processing_user_action

        if not was_processing:
            self.processing_user_action = True

        # a. Set all parents as set too

        parent = item.parent
        while parent:
            parent.is_set = True
            parent = parent.parent

        # b. Duplicate repeated Protobuf item if needed

        if item.is_repeated and item.is_set:
            for last_node_index, last_node in reversed(
                list(enumerate(item.parent_tree))
            ):
                if last_node.proto_id == item.proto_id:
                    break
            else:
                raise ValueError(
                    'Item not found in Protobuf message: %r' % item.proto_id
                )

            if last_node == item:
                node = ProtobufItem.new(
                    item.desc, item.parent, item.parent_tree, item.path
                )
                item.parent_tree.insert(last_node_index + 1, node)
                node.connect('notify::is-set', self.node_value_set)
                node.connect('notify::value', self.node_value_changed)

        if not was_processing:
            self.processing_user_action = False

        # Ensure that we're the data source of
        # the value set before firing a
        # Fuzzer state update

        if not was_processing:
            # Log data change

            print(
                '⚠️⚠️ WIP Protobuf data set/unset =>',
                item.path,
                '/',
                item.field_name,
                '/',
                item.is_set,
            )

            self.update_fuzzer()
