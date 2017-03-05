#!/usr/bin/python3
#-*- encoding: Utf-8 -*-
from PyQt5.QtWidgets import QTreeWidgetItem, QLineEdit, QCheckBox, QAbstractSpinBox, QInputDialog, QMessageBox
from PyQt5.QtCore import QUrl, Qt, pyqtSignal, QByteArray, QRegExp
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtGui import QRegExpValidator

from xml.dom.minidom import parseString
from collections import defaultdict
from subprocess import run, PIPE
from functools import partial
from json import loads, dumps
from zipfile import ZipFile
from zlib import decompress
from struct import unpack
from io import BytesIO
from re import match

# Monkey-patch enum value checking,
from google.protobuf.internal import type_checkers
type_checkers.SupportsOpenEnums = lambda x: True

# Monkey-patch map object creation (suppressing the map_entry option
# from generated classes),
from google.protobuf import descriptor
descriptor._ParseOptions = lambda msg, data: msg.FromString(data.replace(b'8\001', b''))

# And then do Protobuf imports
from google.protobuf.internal.type_checkers import _VALUE_CHECKERS

from utils.common import load_proto_msgs, protoc

"""
    We extend QWebEngineView with a method that parses responses and
    displays response data in the relevant way.
"""

class MyFrame(QWebEngineView):
    def update_frame(self, data, text, url, mime, pbresp=None):
        self.setEnabled(False) # prevent from taking focus
        
        out_mime = 'text/plain; charset=utf-8'

        if 'image' in mime:
            out_mime = mime
        
        elif 'html' in mime:
            if '/embed' in url:
                text = text.replace('<head>', '<head><script>opener=1</script>')
            out_mime = 'text/html; charset=utf-8'
            data = text
        
        elif 'json' in mime:
            if text.startswith(")]}'\n"):
                text = text[5:]
            if text.endswith('/*""*/'):
                text = text[:-6]
            
            text = text.replace('[,','[null,').replace(',]',',null]').replace(',,',',null,').replace(',,',',null,')
            
            try:
                data = dumps(loads(text), indent=4)
            except Exception:
                pass
        
        elif 'protobuf' in mime:
            data = self.parse_protobuf(data, pbresp)
        
        elif 'kmz' in mime:
            with ZipFile(BytesIO(data)) as fd:
                if fd.namelist() == ['doc.kml']:
                    data = parseString(fd.read('doc.kml')).toprettyxml(indent='    ')
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
                
                dec = bytes([i^0x9b for i in data.read(size - 2)])
                if dec.startswith(b'\x78\x9c'):
                    dec = decompress(dec)
                
                out += b'%d %s\n' % (index, b'-' * 15)
                out += self.parse_protobuf(dec, pbresp)
            
            data = out
        
        elif 'text/' in mime:
            pass
        
        else:
            for key in (0x9b, 0x5f):
                dec = bytes([i^key for i in data])
                
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
                dec = run(['hexdump', '-C'], input=data, stdout=PIPE).stdout
            
            data = dec[:500000]
        
        if type(data) == str:
            data = data.encode('utf8')
        self.setContent(QByteArray(data), out_mime, QUrl(url))
        
        self.setEnabled(True)
    
    def parse_protobuf(self, data, pbresp):
        if pbresp:
            try:
                return str(pbresp.FromString(data)).encode('utf8')
            except Exception:
                pass
        return run([protoc, '--decode_raw'], input=data, stdout=PIPE, stderr=PIPE).stdout

"""
    We subclass QAbstractSpinBox as QSpinBox does not provide int64
    precision.
"""

class QwordSpinBox(QAbstractSpinBox):
    valueChanged = pyqtSignal('PyQt_PyObject')
    
    def __init__(self, min_, max_, float_=False):
        super(QwordSpinBox, self).__init__()

        self._minimum = min_
        self._maximum = max_
        self.int_ = float if float_ else int

        rx = QRegExp('-?\d{0,20}(?:\.\d{0,20})?' if float_ else '-?\d{0,20}')
        validator = QRegExpValidator(rx, self)

        self._lineEdit = QLineEdit(self)
        self._lineEdit.setText(str(self.int_(0)))
        self._lineEdit.setValidator(validator)
        self._lineEdit.textEdited.connect(partial(self.setValue, change=False))
        self.editingFinished.connect(lambda: self.setValue(self.value(), update=False) or True)
        self.setLineEdit(self._lineEdit)

    def value(self):
        try:
            return self.int_(self._lineEdit.text())
        except ValueError:
            return 0

    def setValue(self, value, change=True, update=True):
        try:
            value = self.int_(value)
            value2 = max(self._minimum, min(self._maximum, value))
            if update or not self._lineEdit.text().strip('-'):
                self.valueChanged.emit(value2)
            if value != value2 or change:
                self._lineEdit.setText(str(value2))
        except ValueError:
            pass
    
    def stepBy(self, steps):
        self.setValue(self.value() + steps)

    def stepEnabled(self):
        if self.value() > self._minimum and self.value() < self._maximum:
            return self.StepUpEnabled | self.StepDownEnabled
        elif self.value() <= self._minimum:
            return self.StepUpEnabled
        elif self.value() >= self._maximum:
            return self.StepDownEnabled

"""
    The ProtobufItem class inherits QTreeWidgetItem and is used to
    constitute the "Protobuf" tab in the editor.
"""

# This variable is used to bookkeep position of repeated fields, for when one of their siblings is removed.
item_indices = defaultdict(list)

class ProtobufItem(QTreeWidgetItem):
    def __init__(self, item, ds, app, path):
        type_txt = {1: 'double', 2: 'float', 3: 'int64', 4: 'uint64', 5: 'int32', 6: 'fixed64', 7: 'fixed32', 8: 'bool', 9: 'string', 10: 'group', 11: '', 12: 'bytes', 13: 'uint32', 14: 'enum', 15: 'sfixed32', 16: 'sfixed64', 17: 'sint32', 18: 'sint64'}[ds.type]
        
        self.ds = ds
        self.required = ds.label == ds.LABEL_REQUIRED
        self.repeated = ds.label == ds.LABEL_REPEATED
        self.void = True
        self.dupped = False
        self.dupe_obj, self.orig_obj = None, None
        self.value = None
        self.self_pb = None
        self.parent_pb = None
        self.app = app
        self.path = path
        self.is_msg = ds.cpp_type == ds.CPPTYPE_MESSAGE
        self.setting_default = False
        
        self.full_name = self.app.ds_full_names.setdefault(id(ds), ds.full_name)
        
        super().__init__(item, [self.full_name.split('.')[-1] + '+' * self.repeated + '  ', type_txt + '  '])
        
        if not self.required:
            self.setCheckState(0, Qt.Unchecked)
            self.last_check_state = Qt.Unchecked
        
        self.app.ds_items[id(ds)][tuple(path)] = self # Hierarchy array
        
        if self.is_msg:
            self.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            self.expanded = self.lazy_initialize
            return
        
        elif ds.type == ds.TYPE_BOOL:
            self.widget = QCheckBox()
            self.widget.stateChanged.connect(self.value_changed)
            default = False
        
        elif ds.cpp_type == ds.CPPTYPE_STRING:
            self.widget = QLineEdit()
            self.widget.setFrame(False)
            self.widget.setStyleSheet('padding: 1px 0')
            self.widget.textEdited.connect(self.value_changed)
            default = '' if ds.type != ds.TYPE_BYTES else b''
        
        else:
            if ds.cpp_type in (ds.CPPTYPE_DOUBLE, ds.CPPTYPE_FLOAT):
                self.widget = QwordSpinBox(-2**64, 2**64, True)
                default = 0.0
            else:
                cpp_type = ds.cpp_type if ds.cpp_type != ds.CPPTYPE_ENUM else ds.CPPTYPE_INT32
                self.widget = QwordSpinBox(_VALUE_CHECKERS[cpp_type]._MIN, _VALUE_CHECKERS[cpp_type]._MAX)
                default = 0
            
            self.widget.setFrame(False)
            self.widget.setFixedWidth(120)
            self.widget.valueChanged.connect(self.value_changed)
        
        if ds.type == ds.TYPE_ENUM:
            tooltip = '\n'.join('%d : %s' % (i.number, i.name) for i in ds.enum_type.values)
            for col in range(self.columnCount()):
                self.setToolTip(col, tooltip)
        
        self.edit = self._edit
        self.widget.setMouseTracking(True)
        self.widget.enterEvent = self.edit
        
        if item:
            self.app.fuzzer.pbTree.setItemWidget(self, 2, self.widget)
        
        self.setDefault(ds.default_value or default, unvoid=False)
        
        if self.required and not self.parent() and \
           not self.app.pb_request.HasField(self.ds.name):
            self.update(self.value)
    
    # Create children items only when expanded, to avoid problems with
    # huge multi-referencing protos.
    
    def lazy_initialize(self):
        for ds in self.ds.message_type.fields:
            ProtobufItem(self, ds, self.app, self.path + [ds.full_name])
        del self.expanded
    
    """
        The following code that handles the interaction and different
        states of a tree item may be a bit entangled, sorry for this.
    """
    
    def unvoid(self, recur=True):
        if self.void or self.is_msg:
            if not self.required:
                self.setCheckState(0, Qt.Checked)
                self.last_check_state = Qt.Checked
            
            if recur and self.parent():
                self.parent().unvoid(True)
            
            self.void = False
    
    def setDefault(self, val=None, parent=None, msg=None, index=None, unvoid=True):
        self.setting_default = True
        
        if parent:
            self.parent_pb = parent
            self.self_pb = msg
            self.index = index
            if index is not None:
                assert index == len(item_indices[id(self.self_pb)])
                item_indices[id(self.self_pb)].append(self)
        
        if val or (unvoid and val is not None):
            if type(val) == bool:
                self.widget.setChecked(val)
            elif type(val) == str:
                self.widget.setText(val)
            elif type(val) == bytes:
                self.widget.setText(val.decode('latin1').encode('unicode_escape').decode('latin1'))
            else:
                self.widget.setValue(val)
        
        if unvoid:
            self.unvoid(False)
        
        self.value = val
        self.setting_default = False
    
    def value_changed(self, val):
        if not self.setting_default:
            if self.ds.type == self.ds.TYPE_BYTES:
                try:
                    val = val.encode('latin1').decode('unicode_escape').encode('latin1')
                except Exception:
                    return
            elif self.ds.type == self.ds.TYPE_BOOL:
                val = bool(val)
            
            self.update(val)
            self.app.update_fuzzer()
    
    def get_parent_pb(self):
        if self.parent_pb is None:
            if self.parent():
                self.parent_pb = self.parent().get_self_pb()
            else:
                self.parent_pb = self.app.pb_request
        
        return self.parent_pb
    
    def get_self_pb(self):
        if self.self_pb is None:
            self.self_pb = getattr(self.get_parent_pb(), self.ds.name)

            if self.repeated:
                self.index = len(self.self_pb)
                
                item_indices[id(self.self_pb)].append(self)
                
                if self.is_msg:
                    self.self_pb.add()
                    
            if self.is_msg:
                for i in range(self.childCount()):
                    if self.child(i).required:
                        self.child(i).parent_pb = None
                        self.child(i).self_pb = None
                        self.child(i).update(self.child(i).value)
                
                if hasattr(self.self_pb, 'SetInParent'):
                    self.self_pb.SetInParent()
                
                if not self.required:
                    self.setCheckState(0, Qt.Checked)
                    self.last_check_state = Qt.Checked
        
        # Return value is for get_parent_pb recursion
        if self.is_msg:
            if not self.repeated:
                return self.self_pb
            else:
                return self.self_pb[self.index]
    
    def update(self, val):
        if val is not None:
            self.unvoid()
            self.duplicate()
            self.value = val
        
        self.get_self_pb() # Ensure created
        
        if not self.repeated:
            if val is not None:
                setattr(self.parent_pb, self.ds.name, val)
            
            else:
                self.parent_pb.ClearField(self.ds.name)
                self.self_pb = None
                self.void = True
        
        else:
            if val is not None:
                if len(self.self_pb) > self.index: # We exist already
                    self.self_pb[self.index] = val
                
                else: # We were just created by get_self_pb
                    self.self_pb.append(val)
            
            else: # We must have existed already right?
                del self.self_pb[self.index]
                del item_indices[id(self.self_pb)][self.index]
                
                for i in range(self.index, len(item_indices[id(self.self_pb)])):
                    item_indices[id(self.self_pb)][i].index -= 1
                
                self.self_pb = None # So that if we're repeated we're recreated further
                self.void = True
    
    def duplicate(self, setting_default=False):
        if not self.dupped:
            self.dupped = True
            
            if self.parent() and not setting_default:
                self.parent().duplicate()
            
            if self.repeated:
                new_obj = ProtobufItem(None, self.ds, self.app, self.path)
                
                if self.parent():
                    index = self.parent().indexOfChild(self)
                    self.parent().insertChild(index + 1, new_obj)
                
                else:
                    index = self.treeWidget().indexOfTopLevelItem(self)
                    self.treeWidget().insertTopLevelItem(index + 1, new_obj)
                
                if hasattr(new_obj, 'widget'):
                    self.app.fuzzer.pbTree.setItemWidget(new_obj, 2, new_obj.widget)
                
                self.dupe_obj = new_obj
                new_obj.orig_obj = self
                return new_obj
    
    # A message is checked -> all parents are checked
    # A message is unchecked -> all children are unchecked
    
    def update_check(self, recursive=False, col=None):
        if not self.required and self.last_check_state != self.checkState(0):
            self.last_check_state = self.checkState(0)
            
            if not self.is_msg:
                if self.last_check_state == Qt.Checked:
                    self.update(self.value)
                else:
                    self.update(None)
            
            elif not self.self_pb: # We have just checked the message !
                assert self.last_check_state == Qt.Checked
                self.get_self_pb() # Recreates parent
                
                for i in range(self.childCount()):
                    if self.child(i).required:
                        self.child(i).parent_pb = None
                        self.child(i).self_pb = None
                        self.child(i).update(self.child(i).value)
            
            else: # We have just unchecked the message !
                assert self.last_check_state != Qt.Checked
                for i in range(self.childCount()):
                    if not self.child(i).required:
                        self.child(i).setCheckState(0, Qt.Unchecked)
                        self.child(i).update_check(True)
                        self.child(i).parent_pb = None
                        self.child(i).self_pb = None
                
                self.get_self_pb().Clear()
                self.update(None)

            if not recursive:
                self.app.update_fuzzer()
        
        elif col == 0:
            self.prompt_rename()
        
    
    """
        Wheck field name is clicked, offer to rename the field
        
        In order to rewrite field name in the .proto without discarding
        comments or other information, we'll ask protoc to generate file
        source information [1], that we'll parse and that will give us
        text offset for it.
        
        [1] https://github.com/google/protobuf/blob/7f3e23/src/google/protobuf/descriptor.proto#L715
    """
    
    def prompt_rename(self):
        text, good = QInputDialog.getText(self.app.view, ' ', 'Rename this field:', text=self.text(0).strip('+ '))
        if text:
            if not match('^[a-zA-Z0-9_]+$', text):
                QMessageBox.warning(self.app.view, ' ', 'This is not a valid alphanumeric name.')
                self.prompt_rename()
            else:
                try:
                    if self.do_rename(text):
                        return
                except Exception:
                    pass
                QMessageBox.warning(self.app.view, ' ', 'Field was not found in .proto, did you edit it elsewhere?')
    
    def do_rename(self, new_name):
        file_set, proto_path = next(load_proto_msgs(self.app.current_req_proto, True), None)
        file_set = file_set.file
        
        """
        First, recursively iterate over descriptor fields until we have
        a numeric path that leads to it in the structure, as explained
        in [1] above
        """
        
        for file_ in file_set:
            field_path = self.find_path_for_field(file_.message_type, [4], file_.package)
            
            if field_path:
                for location in file_.source_code_info.location:
                    if location.path == field_path:
                        start_line, start_col, end_col = location.span[:3]
                        
                        # Once we have file position information, do
                        # write the new field name in .proto
                        
                        file_path = str(proto_path / file_.name)
                        with open(file_path) as fd:
                            lines = fd.readlines()
                        assert lines[start_line][start_col:end_col] == self.text(0).strip('+ ')
                        
                        lines[start_line] = lines[start_line][:start_col] + new_name + \
                                            lines[start_line][end_col:]
                        with open(file_path, 'w') as fd:
                            fd.writelines(lines)
                        
                        # Update the name on GUI items corresponding to
                        # this field and its duplicates (if repeated)
                        
                        obj = self
                        while obj.orig_obj:
                            obj = obj.orig_obj
                        while obj:
                            obj.full_name = obj.full_name.rsplit('.', 1)[0] + '.' + new_name
                            self.app.ds_full_names[id(obj.ds)] = obj.full_name
                            obj.setText(0, new_name + '+' * self.repeated + '  ')
                            obj = obj.dupe_obj
                        return True
    
    def find_path_for_field(self, msgs, path, cur_name):
        if cur_name:
            cur_name += '.'
        
        for i, msg in enumerate(msgs):
            if self.full_name.startswith(cur_name + msg.name + '.'):
                for j, field in enumerate(msg.field):
                    if cur_name + msg.name + '.' + field.name == self.full_name:
                        return path + [i, 2, j, 1]
                
                return self.find_path_for_field(msg.nested_type, path + [i, 3], cur_name + msg.name)
    
    def _edit(self, ev=None):
        if not self.widget.hasFocus():
            self.widget.setFocus(Qt.MouseFocusReason)
            if hasattr(self.widget, 'selectAll'):
                self.widget.selectAll()

"""
    The ProtocolDataItem class inherits QTreeWidgetItem and is used to
    constitute the second tab in the editor.
"""

class ProtocolDataItem(QTreeWidgetItem):
    def __init__(self, item, name, val, app):
        super().__init__(item, [name + '  '])
        self.name = name
        self.app = app
        self.required = '{%s}' % name in self.app.base_url
        
        if not self.required:
            self.setCheckState(0, Qt.Checked)
            self.last_check_state = Qt.Checked

        self.widget = QLineEdit()
        self.widget.setFrame(False)
        self.widget.setStyleSheet('padding: 1px 0')
        self.widget.textEdited.connect(self.value_changed)
        self.app.fuzzer.getTree.setItemWidget(self, 1, self.widget)
        
        self.widget.setText(val)
        self.value = val
        
        self.widget.setMouseTracking(True)
        self.widget.enterEvent = self.edit
    
    def value_changed(self, val):
        self.app.get_params[self.name] = val
        self.value = val
        
        self.app.update_fuzzer()
    
    def update_check(self, col):
        if not self.required and self.last_check_state != self.checkState(0):
            self.last_check_state = self.checkState(0)
            if self.last_check_state != Qt.Checked:
                del self.app.get_params[self.name]
            else:
                self.app.get_params[self.name] = self.value
            self.app.update_fuzzer()
    
    def edit(self, ev=None):
        if not self.widget.hasFocus():
            self.widget.setFocus(Qt.MouseFocusReason)
            self.widget.selectAll()
