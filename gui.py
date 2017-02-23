#!/usr/bin/python3
#-*- encoding: Utf-8 -*-
from PyQt5.QtWidgets import QApplication, QListWidgetItem, QDesktopWidget, QFileDialog, QInputDialog, QProgressDialog, QMessageBox, QFileSystemModel, QHeaderView
from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QThread
from PyQt5.QtGui import QDesktopServices, QTextOption
from PyQt5.uic import loadUi

from signal import signal, SIGINT, SIG_DFL
from os.path import dirname, realpath
from collections import defaultdict
from urllib.parse import urlparse
from os import listdir, remove
from functools import partial
from json import load, dump
from binascii import crc32
from pathlib import Path
from sys import argv

from utils.common import extractors, transports, BASE_PATH, assert_installed, extractor_save, insert_endpoint, load_proto_msgs
from views.fuzzer import ProtobufItem, ProtocolDataItem
from utils.transports import *
from extractors import *

"""
    This script runs the main code for the PBTK GUI, and essentially
    links loaded QtDesigner *.uis within themselves using signals, and
    with the other parts of code composing PBTK. The order of methods
    more or less follows the action flow of a graphical user.
"""

class PBTKGUI(QApplication):
    def __init__(self):
        super().__init__(argv)
        signal(SIGINT, SIG_DFL)
        
        views = dirname(realpath(__file__)) + '/views/'
        
        self.welcome = loadUi(views + 'welcome.ui')
        self.choose_extractor = loadUi(views + 'choose_extractor.ui')
        self.choose_proto = loadUi(views + 'choose_proto.ui')
        self.create_endpoint = loadUi(views + 'create_endpoint.ui')
        self.choose_endpoint = loadUi(views + 'choose_endpoint.ui')
        self.fuzzer = loadUi(views + 'fuzzer.ui')

        self.welcome.step1.clicked.connect(self.load_extractors)
        self.choose_extractor.rejected.connect(partial(self.set_view, self.welcome))
        self.choose_extractor.extractors.itemClicked.connect(self.prompt_extractor)
        
        self.welcome.step2.clicked.connect(self.load_protos)
        self.proto_fs = QFileSystemModel()
        self.choose_proto.protos.setModel(self.proto_fs)
        self.proto_fs.directoryLoaded.connect(self.choose_proto.protos.expandAll)
        
        for i in range(1, self.proto_fs.columnCount()):
            self.choose_proto.protos.hideColumn(i)
        self.choose_proto.protos.setRootIndex(self.proto_fs.index(str(BASE_PATH / 'protos')))
        self.choose_proto.rejected.connect(partial(self.set_view, self.welcome))
        self.choose_proto.protos.clicked.connect(self.new_endpoint)
        
        self.create_endpoint.transports.itemClicked.connect(self.pick_transport)
        self.create_endpoint.loadRespPbBtn.clicked.connect(self.load_another_pb)
        self.create_endpoint.rejected.connect(partial(self.set_view, self.choose_proto))
        self.create_endpoint.buttonBox.accepted.connect(self.write_endpoint)
                
        self.welcome.step3.clicked.connect(self.load_endpoints)
        self.choose_endpoint.rejected.connect(partial(self.set_view, self.welcome))
        self.choose_endpoint.endpoints.itemClicked.connect(self.launch_fuzzer)
        
        self.fuzzer.rejected.connect(partial(self.set_view, self.choose_endpoint))
        self.fuzzer.fuzzFields.clicked.connect(self.fuzz_endpoint)
        self.fuzzer.deleteThis.clicked.connect(self.delete_endpoint)
        self.fuzzer.comboBox.activated.connect(self.launch_fuzzer)
        self.fuzzer.getAdd.clicked.connect(self.add_tab_data)

        self.fuzzer.urlField.setWordWrapMode(QTextOption.WrapAnywhere)
        
        for tree in (self.fuzzer.pbTree, self.fuzzer.getTree):
            tree.itemEntered.connect(lambda item, _: item.edit() if hasattr(item, 'edit') else None)
            tree.itemClicked.connect(lambda item, col: item.update_check(col=col))
            tree.itemExpanded.connect(lambda item: item.expanded() if hasattr(item, 'expanded') else None)
            tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        
        self.welcome.mydirLabel.setText(self.welcome.mydirLabel.text() % BASE_PATH)
        self.welcome.mydirBtn.clicked.connect(partial(QDesktopServices.openUrl, QUrl.fromLocalFile(str(BASE_PATH))))
        
        self.set_view(self.welcome)
        self.exec_()
    
    """
        Step 1 - Extract .proto structures from apps
    """
    
    def load_extractors(self):
        self.choose_extractor.extractors.clear()
        
        for name, meta in extractors.items():
            item = QListWidgetItem(meta['desc'], self.choose_extractor.extractors)
            item.setData(Qt.UserRole, name)
        
        self.set_view(self.choose_extractor)
    
    def prompt_extractor(self, item):
        extractor = extractors[item.data(Qt.UserRole)]
        inputs = []
        if not assert_installed(self.view, **extractor.get('depends', {})):
            return
        
        if not extractor.get('pick_url', False):
            files, mime = QFileDialog.getOpenFileNames()
            for path in files:
                inputs.append((path, Path(path).stem))
        else:
            text, good = QInputDialog.getText(self.view, ' ', 'Input an URL:')
            if text:
                url = urlparse(text)
                inputs.append((url.geturl(), url.netloc))
        
        if inputs:
            wait = QProgressDialog('Extracting .proto structures...', None, 0, 0)
            wait.setWindowTitle(' ')
            self.set_view(wait)
            
            self.worker = Worker(inputs, extractor)
            self.worker.progress.connect(self.extraction_progress)
            self.worker.finished.connect(self.extraction_done)
            self.worker.start()
    
    def extraction_progress(self, info, progress):
        self.view.setLabelText(info)
        
        if progress is not None:
            self.view.setRange(0, 100)
            self.view.setValue(progress * 100)
        else:
            self.view.setRange(0, 0)
    
    def extraction_done(self, outputs):
        nb_written_all, wrote_endpoints = 0, False
        
        for folder, output in outputs.items():
            nb_written, wrote_endpoints = extractor_save(BASE_PATH, folder, output)
            nb_written_all += nb_written
        
        if wrote_endpoints:
            self.set_view(self.welcome)
            QMessageBox.information(self.view, ' ', '%d endpoints and their <i>.proto</i> structures have been extracted! You can now reuse the <i>.proto</i>s or fuzz the endpoints.' % nb_written_all)
        
        elif nb_written_all:
            self.set_view(self.welcome)
            QMessageBox.information(self.view, ' ', '%d <i>.proto</i> structures have been extracted! You can now reuse the <i>.protos</i> or define endpoints for them to fuzz.' % nb_written_all)
        
        else:
            self.set_view(self.choose_extractor)
            QMessageBox.warning(self.view, ' ', 'This extractor did not find Protobuf structures in the corresponding format for specified files.')
    
    """
        Step 2 - Link .protos to endpoints
    """
    
    # Don't load .protos from the filesystem until asked to, in order
    # not to slow down startup.
    
    def load_protos(self):
        self.proto_fs.setRootPath(str(BASE_PATH / 'protos'))
        self.set_view(self.choose_proto)
    
    def new_endpoint(self, path):
        if not self.proto_fs.isDir(path):
            path = self.proto_fs.filePath(path)
            
            if not getattr(self, 'only_resp_combo', False):
                self.create_endpoint.pbRequestCombo.clear()
            self.create_endpoint.pbRespCombo.clear()
            
            has_msgs = False
            for name, cls in load_proto_msgs(path):
                has_msgs = True
                if not getattr(self, 'only_resp_combo', False):
                    self.create_endpoint.pbRequestCombo.addItem(name, (path, name))
                self.create_endpoint.pbRespCombo.addItem(name, (path, name))
            if not has_msgs:
                QMessageBox.warning(self.view, ' ', 'There is no message defined in this .proto.')
                return
            
            self.create_endpoint.reqDataSubform.hide()

            if not getattr(self, 'only_resp_combo', False):
                self.create_endpoint.endpointUrl.clear()
                self.create_endpoint.transports.clear()
                self.create_endpoint.sampleData.clear()
                self.create_endpoint.pbParamKey.clear()
                self.create_endpoint.parsePbCheckbox.setChecked(False)
                
                for name, meta in transports.items():
                    item = QListWidgetItem(meta['desc'], self.create_endpoint.transports)
                    item.setData(Qt.UserRole, (name, meta.get('ui_data_form')))
            
            elif getattr(self, 'saved_transport_choice'):
                self.create_endpoint.transports.setCurrentItem(self.saved_transport_choice)
                self.pick_transport(self.saved_transport_choice)
                self.saved_transport_choice = None
            
            self.only_resp_combo = False
            self.set_view(self.create_endpoint)
    
    def pick_transport(self, item):
        name, desc = item.data(Qt.UserRole)
        self.has_pb_param = desc and 'regular' in desc
        self.create_endpoint.reqDataSubform.show()
        if self.has_pb_param:
            self.create_endpoint.pbParamSubform.show()
        else:
            self.create_endpoint.pbParamSubform.hide()
        self.create_endpoint.sampleDataLabel.setText('Sample request data, one per line (in the form of %s):' % desc)
    
    def load_another_pb(self):
        self.only_resp_combo = True
        self.saved_transport_choice = self.create_endpoint.transports.currentItem()
        self.set_view(self.choose_proto)
    
    def write_endpoint(self):
        request_pb = self.create_endpoint.pbRequestCombo.itemData(self.create_endpoint.pbRequestCombo.currentIndex())
        url = self.create_endpoint.endpointUrl.text()
        transport = self.create_endpoint.transports.currentItem()
        sample_data = self.create_endpoint.sampleData.toPlainText()
        pb_param = self.create_endpoint.pbParamKey.text()
        has_resp_pb = self.create_endpoint.parsePbCheckbox.isChecked()
        resp_pb = self.create_endpoint.pbRespCombo.itemData(self.create_endpoint.pbRespCombo.currentIndex())
        
        if not (request_pb and urlparse(url).netloc and transport and (not self.has_pb_param or pb_param) and (not has_resp_pb or resp_pb)):
            QMessageBox.warning(self.view, ' ', 'Please fill all relevant information fields.')
        
        else:
            json = {
                'request': {
                    'transport': transport.data(Qt.UserRole)[0],
                    'proto_path': request_pb[0].replace(str(BASE_PATH / 'protos'), '').strip('/\\'),
                    'proto_msg': request_pb[1],
                    'url': url
                }
            }
            if self.has_pb_param:
                json['request']['pb_param'] = pb_param
            
            sample_data = list(filter(None, sample_data.split('\n')))
            if sample_data:
                transport_obj = transports[transport.data(Qt.UserRole)[0]]
                transport_obj = transport_obj['func'](pb_param, url)
                
                for sample_id, sample in enumerate(sample_data):
                    try:
                        sample = transport_obj.serialize_sample(sample)
                    except Exception:
                        return QMessageBox.warning(self.view, ' ', 'Some of your sample data is not in the specified format.')
                    if not sample:
                        return QMessageBox.warning(self.view, ' ', "Some of your sample data didn't contain the Protobuf parameter key you specified.")
                    sample_data[sample_id] = sample
                
                json['request']['samples'] = sample_data
            
            if has_resp_pb:
                json['response'] = {
                    'format': 'raw_pb',
                    'proto_path': resp_pb[0].replace(str(BASE_PATH / 'protos'), '').strip('/\\'),
                    'proto_msg': resp_pb[1]
                }
            insert_endpoint(BASE_PATH / 'endpoints', json)
            
            QMessageBox.information(self.view, ' ', 'Endpoint created successfully.')
            self.set_view(self.welcome)
    
    """
        Step 3: Fuzz and test endpoints live
    """
    
    def load_endpoints(self):
        self.choose_endpoint.endpoints.clear()
        
        for name in listdir(str(BASE_PATH / 'endpoints')):
            if name.endswith('.json'):
                item = QListWidgetItem(name.split('.json')[0], self.choose_endpoint.endpoints)
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                
                pb_msg_to_endpoints = defaultdict(list)
                with open(str(BASE_PATH / 'endpoints' / name)) as fd:
                    for endpoint in load(fd, object_pairs_hook=OrderedDict):
                        pb_msg_to_endpoints[endpoint['request']['proto_msg'].split('.')[-1]].append(endpoint)
                
                for pb_msg, endpoints in pb_msg_to_endpoints.items():
                    item = QListWidgetItem(' ' * 4 + pb_msg, self.choose_endpoint.endpoints)
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                    
                    for endpoint in endpoints:
                        path_and_qs = '/' + endpoint['request']['url'].split('/', 3).pop()
                        item = QListWidgetItem(' ' * 8 + path_and_qs, self.choose_endpoint.endpoints)
                        item.setData(Qt.UserRole, endpoint)
        
        self.set_view(self.choose_endpoint)
    
    def launch_fuzzer(self, item):
        if type(item) == int:
            data, sample_id = self.fuzzer.comboBox.itemData(item)
        else:
            data, sample_id = item.data(Qt.UserRole), 0
        
        if data:
            self.current_req_proto = BASE_PATH / 'protos' / data['request']['proto_path']
            
            self.pb_request = load_proto_msgs(self.current_req_proto)
            self.pb_request = dict(self.pb_request)[data['request']['proto_msg']]()
            
            if data.get('response') and data['response']['format'] == 'raw_pb':
                self.pb_resp = load_proto_msgs(BASE_PATH / 'protos' / data['response']['proto_path'])
                self.pb_resp = dict(self.pb_resp)[data['response']['proto_msg']]

            self.pb_param = data['request'].get('pb_param')
            self.base_url = data['request']['url']
            self.endpoint = data
            
            self.transport_meta = transports[data['request']['transport']]
            self.transport = self.transport_meta['func'](self.pb_param, self.base_url)
            
            sample = ''
            if data['request'].get('samples'):
                sample = data['request']['samples'][sample_id]
            self.get_params = self.transport.load_sample(sample, self.pb_request)
            
            # Get initial data into the Protobuf tree view
            self.fuzzer.pbTree.clear()
            
            self.ds_items = defaultdict(dict)
            self.ds_full_names = {}
            
            for ds in self.pb_request.DESCRIPTOR.fields:
                ProtobufItem(self.fuzzer.pbTree, ds, self, [ds.full_name])
            self.parse_fields(self.pb_request)
            
            # Do the same for transport-specific data
            self.fuzzer.getTree.clear()
            self.fuzzer.tabs.setTabText(1, self.transport_meta.get('ui_tab', ''))
            if self.get_params:
                for key, val in self.get_params.items():
                    ProtocolDataItem(self.fuzzer.getTree, key, val, self)
            
            # Fill the request samples combo box if we're loading a new
            # endpoint.
            if type(item) != int:
                if len(data['request'].get('samples', [])) > 1:
                    self.fuzzer.comboBox.clear()
                    for sample_id, sample in enumerate(data['request']['samples']):
                        self.fuzzer.comboBox.addItem(sample[self.pb_param] if self.pb_param else str(sample), (data, sample_id))
                    self.fuzzer.comboBoxLabel.show()
                    self.fuzzer.comboBox.show()
                else:
                    self.fuzzer.comboBoxLabel.hide()
                    self.fuzzer.comboBox.hide()
                
                self.set_view(self.fuzzer)
            
            self.fuzzer.frame.setUrl(QUrl("about:blank"))
            self.update_fuzzer()

    """
        Parsing and rendering the Protobuf message to a tree view:

        Every Protobuf field is fed to ProtobufItem (a class inheriting
        QTreeWidgetItem), and the created object is saved in the ds_items
        entry for the corresponding descriptor.
    """
    
    def parse_fields(self, msg, base_path=[]):
        for ds, val in msg.ListFields():
            path = base_path + [ds.full_name]
            
            if ds.label == ds.LABEL_REPEATED:
                for val_index, val_value in enumerate(val):
                    if ds.cpp_type == ds.CPPTYPE_MESSAGE:
                        self.ds_items[id(ds)][tuple(path)].setExpanded(True)
                        self.ds_items[id(ds)][tuple(path)].setDefault(parent=msg, msg=val, index=val_index)
                        self.parse_fields(val_value, path)
                    
                    else:
                        self.ds_items[id(ds)][tuple(path)].setDefault(val_value, parent=msg, msg=val, index=val_index)
                    
                    self.ds_items[id(ds)][tuple(path)].duplicate(True)
            
            else:
                if ds.cpp_type == ds.CPPTYPE_MESSAGE:
                    self.ds_items[id(ds)][tuple(path)].setExpanded(True)
                    self.ds_items[id(ds)][tuple(path)].setDefault(parent=msg, msg=val)
                    self.parse_fields(val, path)
                
                else:
                    self.ds_items[id(ds)][tuple(path)].setDefault(val, parent=msg, msg=val)
    
    def update_fuzzer(self):
        resp = self.transport.perform_request(self.pb_request, self.get_params)
        
        data, text, url, mime = resp.content, resp.text, resp.url, resp.headers['Content-Type'].split(';')[0]
        
        meta = '%s %d %08x\n%s' % (mime, len(data), crc32(data) & 0xffffffff, resp.url)
        self.fuzzer.urlField.setText(meta)
        
        self.fuzzer.frame.update_frame(data, text, url, mime, getattr(self, 'pb_resp', None))
    
    def fuzz_endpoint(self):
        QMessageBox.information(self.view, ' ', 'Automatic fuzzing is not implemented yet.')
    
    def delete_endpoint(self):
        if QMessageBox.question(self.view, ' ', 'Delete this endpoint?') == QMessageBox.Yes:
            path = str(BASE_PATH / 'endpoints' / (urlparse(self.base_url).netloc + '.json'))
            
            with open(path) as fd:
                json = load(fd, object_pairs_hook=OrderedDict)
            json.remove(self.endpoint)
            
            with open(path, 'w') as fd:
                dump(json, fd, ensure_ascii=False, indent=4)
            if not json:
                remove(path)
            
            self.load_endpoints()
    
    def add_tab_data(self):
        text, good = QInputDialog.getText(self.view, ' ', 'Field name:')
        if text:
            ProtocolDataItem(self.fuzzer.getTree, text, '', self).edit()
    
    """
        Utility methods follow
    """
    
    def set_view(self, view):
        if hasattr(self, 'view'):
            self.view.hide()
        view.show()
        self.view = view
        
        resolution = QDesktopWidget().screenGeometry()
        view.move((resolution.width() / 2) - (view.frameSize().width() / 2),
                  (resolution.height() / 2) - (view.frameSize().height() / 2))

"""
    Simple wrapper for running extractors in background.
"""

class Worker(QThread):
    finished = pyqtSignal(object)
    progress = pyqtSignal(object, object)

    def __init__(self, inputs, extractor):
        super().__init__()
        self.inputs = inputs
        self.extractor = extractor
    
    def run(self):
        output = defaultdict(list)
        for input_, folder in self.inputs:
            # Extractor is runned here
            for name, contents in self.extractor['func'](input_):
                if name == '_progress':
                    self.progress.emit(*contents)
                else:
                    output[folder].append((name, contents))
        
        self.finished.emit(output)

PBTKGUI()
