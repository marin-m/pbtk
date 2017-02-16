#!/usr/bin/python3
#-*- encoding: Utf-8 -*-
from PyQt5.QtWidgets import QTreeWidgetItem, QLineEdit, QCheckBox, QAbstractSpinBox, QInputDialog, QMessageBox
from PyQt5.QtCore import QUrl, Qt, pyqtSignal, QByteArray, QRegExp
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtGui import QRegExpValidator

from google.protobuf.descriptor_pb2 import FileDescriptorSet
from xml.dom.minidom import parseString
from subprocess import run, PIPE
from functools import partial
from json import loads, dumps
from zipfile import ZipFile
from zlib import decompress
from struct import unpack
from io import BytesIO
from re import match

# Monkey-patch enum value checking, and then do Protobuf imports
from google.protobuf.internal import type_checkers
type_checkers.SupportsOpenEnums = lambda x: True
from google.protobuf.internal.type_checkers import _VALUE_CHECKERS

from utils.common import load_proto_msgs

"""
    We extend QWebEngineView with a method that parses responses and
    displays response data in the relevant way.
"""

class MyFrame(QWebEngineView):
    def update_frame(self, data, text, url, mime, pbresp=None):
        self.setEnabled(False) # prevent from taking focus

        if 'image' in mime:
            self.setContent(QByteArray(data), mime, QUrl(url))
        
        elif 'html' in mime:
            if '/embed' in url:
                text = text.replace('<head>', '<head><script>opener=1</script>')
            self.setHtml(text, QUrl(url))
        
        elif 'json' in mime:
            if text.startswith(")]}'\n"):
                text = text[5:]
            if text.endswith('/*""*/'):
                text = text[:-6]
            
            text = text.replace('[,','[null,').replace(',]',',null]').replace(',,',',null,').replace(',,',',null,')
            
            try:
                text = dumps(loads(text), indent=4).encode('utf8')
            except Exception:
                text = text.encode('utf8')
            
            self.setContent(QByteArray(text), 'text/plain', QUrl(url))
        
        elif 'protobuf' in mime:
            data = self.parse_protobuf(data, pbresp)
            self.setContent(QByteArray(data), 'text/plain', QUrl(url))
        
        elif 'kmz' in mime:
            with ZipFile(BytesIO(data)) as fd:
                if fd.namelist() == ['doc.kml']:
                    self.setContent(QByteArray(parseString(fd.read('doc.kml')).toprettyxml(indent='    ').encode('utf8')), 'text/plain', QUrl(url))
                else:
                    self.setContent(QByteArray('\n'.join(fd.namelist()).encode('utf8')), 'text/plain', QUrl(url))
        
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
            
            self.setContent(QByteArray(out), 'text/plain', QUrl(url))
        
        elif 'text/' in mime:
            self.setContent(QByteArray(data), 'text/plain', QUrl(url))
        
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
            
            self.setContent(QByteArray(dec[:500000]), 'text/plain', QUrl(url))
        
        self.setEnabled(True)
    
    def parse_protobuf(self, data, pbresp):
        if pbresp:
            try:
                return str(pbresp.FromString(data)).encode('utf8')
            except Exception:
                pass
        return run(['protoc', '--decode_raw'], input=data, stdout=PIPE, stderr=PIPE).stdout

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
item_indices = {}

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
        self.selfPb = None
        self.parentPb = None
        self.app = app
        self.path = path
        self.isMsg = ds.type == ds.TYPE_MESSAGE
        self.settingDefault = False
        
        if not ds.full_name in path:
            super().__init__(item, [ds.full_name.split('.')[-1] + '+' * self.repeated + '  ', type_txt + '  '])
        else:
            super().__init__(item, ['...' + '  ', ''])
            self.updateCheck = self.createCollapsed
            return
        
        if not self.required:
            self.setCheckState(0, Qt.Unchecked)
            self.lastCheckState = Qt.Unchecked
        
        if not hasattr(ds, '_items'):
            ds._items = {}
        ds._items[tuple(path)] = self # Hierarchy array
        
        if self.isMsg:
            return
        
        elif ds.type == ds.TYPE_BOOL:
            self.widget = QCheckBox()
            self.widget.stateChanged.connect(self.valueChanged)
            default = False
        
        elif ds.cpp_type == ds.CPPTYPE_STRING:
            self.widget = QLineEdit()
            self.widget.setFrame(False)
            self.widget.setStyleSheet('padding: 1px 0')
            self.widget.textEdited.connect(self.valueChanged)
            default = ''
        
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
            self.widget.valueChanged.connect(self.valueChanged)
        
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
    
    """
        The following code that handles the interaction and different
        states of a tree item may be a bit entangled, sorry for this.
    """
    
    def unvoid(self, recur=True):
        if self.void or self.isMsg:
            if not self.required:
                self.setCheckState(0, Qt.Checked)
                self.lastCheckState = Qt.Checked
            
            if recur and self.parent():
                self.parent().unvoid(True)
            
            self.void = False
    
    def setDefault(self, val=None, parent=None, msg=None, index=None, unvoid=True):
        self.settingDefault = True
        
        if parent:
            self.parentPb = parent
            self.selfPb = msg
            self.index = index
            if index is not None:
                item_indices.setdefault(id(self.selfPb), [])
                assert index == len(item_indices[id(self.selfPb)])
                item_indices[id(self.selfPb)].append(self)
        
        if val:
            if type(val) == bool:
                self.widget.setChecked(val)
            elif type(val) == str:
                self.widget.setText(val)
            elif type(val) == bytes:
                self.widget.setText(val.decode('utf8'))
            else:
                self.widget.setValue(val)
        
        if unvoid:
            self.unvoid(False)
        
        self.value = val
        self.settingDefault = False
    
    def valueChanged(self, val):
        if not self.settingDefault:
            if self.ds.type == self.ds.TYPE_BYTES:
                val = val.encode('utf8')
            elif self.ds.type == self.ds.TYPE_BOOL:
                val = bool(val)
            
            self.update(val)
            self.app.update_fuzzer()
    
    def getParentPb(self):
        if self.parentPb is None:
            if self.parent():
                self.parentPb = self.parent().getSelfPb()
            else:
                self.parentPb = self.app.pb_request
        
        return self.parentPb
    
    def getSelfPb(self):
        if self.selfPb is None:
            self.selfPb = getattr(self.getParentPb(), self.ds.name)
                
            if self.repeated:
                self.index = len(self.selfPb)
                
                item_indices.setdefault(id(self.selfPb), [])
                item_indices[id(self.selfPb)].append(self)
                
                if self.isMsg:
                    self.selfPb.add()
                    
            if self.isMsg:
                for i in range(self.childCount()):
                    if self.child(i).required:
                        self.child(i).parentPb = None
                        self.child(i).selfPb = None
                        self.child(i).update(self.child(i).value)
                
                if hasattr(self.selfPb, 'SetInParent'):
                    self.selfPb.SetInParent()
                
                if not self.required:
                    self.setCheckState(0, Qt.Checked)
                    self.lastCheckState = Qt.Checked
        
        # Return value is for getParentPb recursion
        if self.isMsg:
            if not self.repeated:
                return self.selfPb
            else:
                return self.selfPb[self.index]
    
    def update(self, val):
        if val is not None:
            self.unvoid()
            self.duplicate()
            self.value = val
        
        self.getSelfPb() # Ensure created
        
        if not self.repeated:
            if val is not None:
                setattr(self.parentPb, self.ds.name, val)
            
            else:
                self.parentPb._fields.pop(self.ds, None)
                self.selfPb = None
                self.void = True
        
        else:
            if val is not None:
                if len(self.selfPb) > self.index: # We exist already
                    self.selfPb[self.index] = val
                
                else: # We were just created by getSelfPb
                    self.selfPb.append(val)
            
            else: # We must have existed already right?
                del self.selfPb[self.index]
                del item_indices[id(self.selfPb)][self.index]
                
                for i in range(self.index, len(item_indices[id(self.selfPb)])):
                    item_indices[id(self.selfPb)][i].index -= 1
                
                self.selfPb = None # So that if we're repeated we're recreated further
                self.void = True
    
    def createCollapsed(self, recursive=False, col=None):
        if not recursive:
            self.path = []
            
            new = self.duplicate(True, True)
            new.setExpanded(True)
            
            if self.parent():
                index = self.parent().indexOfChild(self)
                self.parent().takeChild(index)
            else:
                index = self.treeWidget().indexOfTopLevelItem(self)
                self.treeWidget().takeTopLevelItem(index)
    
    def duplicate(self, settingDefault=False, force=False):
        if not self.dupped:
            self.dupped = True
            
            if self.parent() and not settingDefault:
                self.parent().duplicate()
            
            if self.repeated or force:
                newObj = ProtobufItem(None, self.ds, self.app, self.path)
                
                if self.parent():
                    index = self.parent().indexOfChild(self)
                    self.parent().insertChild(index + 1, newObj)
                
                else:
                    index = self.treeWidget().indexOfTopLevelItem(self)
                    self.treeWidget().insertTopLevelItem(index + 1, newObj)
                
                if hasattr(newObj, 'widget'):
                    self.app.fuzzer.pbTree.setItemWidget(newObj, 2, newObj.widget)
                
                if self.isMsg:
                    self.app.parse_desc(self.ds.message_type, newObj, self.path + [self.ds.full_name])
                
                self.dupe_obj = newObj
                newObj.orig_obj = self
                return newObj
    
    # A message is checked -> all parents are checked
    # A message is unchecked -> all children are unchecked
    
    def updateCheck(self, recursive=False, col=None):
        if not self.required and self.lastCheckState != self.checkState(0):
            self.lastCheckState = self.checkState(0)
            
            if not self.isMsg:
                if self.lastCheckState == Qt.Checked:
                    self.update(self.value)
                else:
                    self.update(None)
            
            elif not self.selfPb: # We have just checked the message !
                assert self.lastCheckState == Qt.Checked
                self.getSelfPb() # Recreates parent
                
                for i in range(self.childCount()):
                    if self.child(i).required:
                        self.child(i).parentPb = None
                        self.child(i).selfPb = None
                        self.child(i).update(self.child(i).value)
            
            else: # We have just unchecked the message !
                assert self.lastCheckState != Qt.Checked
                for i in range(self.childCount()):
                    if not self.child(i).required:
                        self.child(i).setCheckState(0, Qt.Unchecked)
                        self.child(i).updateCheck(True)
                        self.child(i).parentPb = None
                        self.child(i).selfPb = None
                
                self.getSelfPb().Clear()
                self.update(None)

            if not recursive:
                self.app.update_fuzzer()
        
        elif col == 0:
            self.promptRename()
        
    
    """
        Wheck field name is clicked, offer to rename the field
        
        In order to rewrite field name in the .proto without discarding
        comments or other information, we'll ask protoc to generate file
        source information [1], that we'll parse and that will give us
        text offset for it.
        
        [1] https://github.com/google/protobuf/blob/7f3e23/src/google/protobuf/descriptor.proto#L715
    """
    
    def promptRename(self):
        text, good = QInputDialog.getText(self.app.view, ' ', 'Rename this field:', text=self.text(0).strip('+ '))
        if text:
            if not match('^\w+$', text):
                QMessageBox.warning(self.app.view, ' ', 'This is not a valid alphanumeric name.')
                self.promptRename()
            else:
                try:
                    if self.doRename(text):
                        return
                except Exception:
                    pass
                QMessageBox.warning(self.app.view, ' ', 'Field was not found in .proto, did you edit it elsewhere?')
    
    def doRename(self, new_name):
        file_set, proto_path = next(load_proto_msgs(self.app.current_req_proto, True), None)
        file_set = file_set.file
        
        """
        First, recursively iterate over descriptor fields until we have
        a numeric path that leads to it in the structure, as explained
        in [1] above
        """
        
        for file_ in file_set:
            field_path = self.findPathForField(file_.message_type, [4], file_.package)
            
            if field_path:
                for location in file_.source_code_info.location:
                    if location.path == field_path:
                        start_line, start_col, end_col = location.span[:3]
                        
                        # Once we have file position information, do
                        # write the new field name in .proto
                        
                        file_path = proto_path / file_.name
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
                            obj.ds.full_name = obj.ds.full_name.rsplit('.', 1)[0] + '.' + new_name
                            obj.setText(0, new_name + '+' * self.repeated + '  ')
                            obj = obj.dupe_obj
                        return True
    
    def findPathForField(self, msgs, path, cur_name):
        if cur_name:
            cur_name += '.'
        
        for i, msg in enumerate(msgs):
            if self.ds.full_name.startswith(cur_name + msg.name + '.'):
                for j, field in enumerate(msg.field):
                    if cur_name + msg.name + '.' + field.name == self.ds.full_name:
                        return path + [i, 2, j, 1]
                
                return self.findPathForField(msg.nested_type, path + [i, 3], cur_name + msg.name)
    
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
            self.lastCheckState = Qt.Checked

        self.widget = QLineEdit()
        self.widget.setFrame(False)
        self.widget.setStyleSheet('padding: 1px 0')
        self.widget.textEdited.connect(self.valueChanged)
        self.app.fuzzer.getTree.setItemWidget(self, 1, self.widget)
        
        self.widget.setText(val)
        self.value = val
        
        self.widget.setMouseTracking(True)
        self.widget.enterEvent = self.edit
    
    def valueChanged(self, val):
        self.app.get_params[self.name] = val
        self.value = val
        
        self.app.update_fuzzer()
    
    def updateCheck(self):
        if not self.required and self.lastCheckState != self.checkState(0):
            self.lastCheckState = self.checkState(0)
            if self.lastCheckState != Qt.Checked:
                del self.app.get_params[self.name]
            else:
                self.app.get_params[self.name] = self.value
            self.app.update_fuzzer()
    
    def edit(self, ev=None):
        if not self.widget.hasFocus():
            self.widget.setFocus(Qt.MouseFocusReason)
            self.widget.selectAll()
