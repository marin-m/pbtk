#!/usr/bin/python3
#-*- encoding: Utf-8 -*-
from urllib.parse import quote, quote_plus, unquote_plus, parse_qsl, urlencode
from tempfile import TemporaryDirectory
from subprocess import Popen, DEVNULL
from logging import getLogger, DEBUG
from collections import OrderedDict
from re import search, sub, findall
from urllib.request import urlopen
from json import loads, dumps
from random import randint
from shutil import which
from time import sleep

from os.path import dirname, realpath
__import__('sys').path.append(dirname(realpath(__file__)) + '/..')
from utils.transports import GMapsAPIPublic, GMapsAPIPrivate
from utils.common import register_extractor, extractor_main

"""
    Protobuf-URL (named internally JsProtoUrl) is the way I call the
    text encoding you can observe in Google Maps-related URLs (both the
    frontend web application, private API requests and public API
    requests).

    This script opens a Chrome instance controlled through the remote
    debugging API [1] to the URL of your choice, searches for and hooks
    JavaScript functions related to Protobuf-URL, and when an URL query
    string is generated through this function and AJAX-called (or browsed
    to through the history API), it generates both reconstructed .protos
    and HTTP endpoint information.
    
    For Chrome debugging protocol's calls documentation, see [2]. As of
    January 2017, using a developement version is advised.
    
    [1] https://developer.chrome.com/devtools/docs/debugger-protocol
    [2] https://chromedevtools.github.io/debugger-protocol-viewer/tot/
"""

browser = which('C:/Program Files (x86)/Google/Chrome/Application/chrome.exe') or \
          which('chromium-browser') or which('chromium') or which('chrome') or 'google-chrome'

@register_extractor(name = 'pburl_extract',
                    desc = 'Extract and capture Protobuf-URL endpoints from a Chrome instance (http://*)',
                    pick_url = True,
                    depends={'binaries': [browser], 'modules': ['websocket']})
def pburl_extract(url):
    global URL, req_id, req_data, sent_msgs, awaiting_srcs, endpoints, sid_to_vars, proto_to_urls
    URL = url

    req_id = 1
    req_data = {}
    sent_msgs = {}
    awaiting_srcs = []
    endpoints = []
    sid_to_vars = {}
    proto_to_urls = OrderedDict()
    
    port = randint(1024, 32767)
    temp_profile = True
    
    yield '_progress', ('Opening a browser window...\n(Your activity from the first tab will be captured, until you close it)', None)
    
    with TemporaryDirectory() as profile:
        cmd = [browser, '--remote-debugging-port=%d' % port, 'about:blank']
        if temp_profile == True:
            cmd += ['--user-data-dir=' + profile, '--no-first-run', '--start-maximized', '--no-default-browser-check']
        
        chrome = Popen(cmd, stdout=DEVNULL, stderr=DEVNULL)

        try:
            while True:
                try:
                    tabs = urlopen('http://localhost:%d/json' % port).read().decode('utf8')
                    tab = next(tab for tab in loads(tabs) if tab['type'] == 'page')
                    break
                except OSError:
                    sleep(0.1)
            
            from websocket import WebSocketApp
            
            getLogger('websocket').setLevel(DEBUG)
            ws = WebSocketApp(tab['webSocketDebuggerUrl'],
                              on_message=on_message,
                              on_open=on_open).run_forever()
        
        finally:
            # Make sure that Chromium is killed when quitting by error
            chrome.terminate()
            
            # Avoid race condition with it writing to profile directory
            sleep(0.2)
    
    for proto in list(proto_to_urls):
        # Determine .proto name based on endpoint URL
        pbname = min(proto_to_urls[proto], key=len)
        pbname = sub('/contrib/\{contrib\}/[a-z]+/@', '/@', pbname)
        pbname = sub('/([^/=]+[/=]|@)\{.+?\}(/\{.+?\})?', '', pbname)
        pbname = pbname.split('/')[3:]
        if pbname[0] in ('maps', 'rt') and len(pbname) > 1:
            pbname.pop(0)
        if pbname[0] == 'preview':
            pbname.pop(0)
        pbname = ''.join(map(lambda x: x[0].upper() + x[1:], pbname))
        pbname = sub('[^A-Za-z0-9]', '', pbname)
        pbname = {'Vt': 'VectorTown', 'S': 'Search'}.get(pbname, pbname)
        pbname_, tries = pbname, 0
        while pbname in proto_to_urls:
            tries += 1
            pbname = pbname_ + str(tries)
        
        # Save generated .proto to ~/.pbtk
        if len(pbname) == 1:
            yield pbname + '.proto', proto.replace('message Top', 'message ' + pbname).replace('Top', '.' + pbname)
        else:
            yield pbname + '.proto', proto.replace('Top', pbname)
        proto_to_urls[pbname] = proto_to_urls[proto]
        del proto_to_urls[proto]
        
        print(pbname, '=>', proto_to_urls[pbname])
    
    # Save endpoint to ~/.pbtk
    for sample in endpoints:
        yield next(k for k, v in proto_to_urls.items() if sample['url'] in v) + '.sample', sample

def on_open(ws):
    send(ws, 'Runtime.enable')
    send(ws, 'Debugger.enable')
    send(ws, 'Network.enable')
    send(ws, 'Page.navigate', {'url': URL})

def send(ws, call, params=None, data=None):
    global req_id
    req_data[req_id] = (call, data)
    if params:
        ws.send(dumps({'id': req_id, 'method': call, 'params': params}))
    else:
        ws.send(dumps({'id': req_id, 'method': call}))
    req_id += 1

def on_message(ws, msg):
    global seen_scripts
    msg = loads(msg)
    
    if 'method' in msg:
        call, msg = msg['method'], msg['params']
        
        if call == 'Network.requestWillBeSent':
            msg = msg['request']
            if '=!' in msg['url'] or search('&[0-9]', msg['url']):
                logUrl(msg['url'])
        
        elif call == 'Runtime.executionContextCreated':
            seen_scripts = set()
            send(ws, 'Runtime.evaluate', {'expression': '''
var wrap = function(orig) {
    return function() {
        var new_path = arguments[2];
        if(new_path[0] == '/') {
            new_path = location.origin + new_path;
        }
        console.log(JSON.stringify(['__URL', new_path]));
        return orig.apply(this, arguments);
    };
};
history.replaceState = wrap(history.replaceState);'''})
        
        elif call == 'Debugger.scriptParsed':
            myId = (msg['url'], msg['startLine'], msg['startColumn'])
            if myId not in seen_scripts and not (msg['startLine'] == msg['endLine'] and msg['endColumn'] - msg['startColumn'] < 100):
                seen_scripts.add(myId)
                awaiting_srcs.append(msg['scriptId'])
                send(ws, 'Debugger.pause')
                send(ws, 'Debugger.getScriptSource', {'scriptId': msg['scriptId']},
                    (msg['scriptId'], '\n' * msg['startLine'] + ' ' * msg['startColumn']))
        
        elif call == 'Debugger.paused':
            loc = msg['callFrames'][0]['location']
            
            if msg['hitBreakpoints'] and msg['reason'] == 'other' and msg['callFrames']:
                send(ws, 'Debugger.pause')
                defaultVar, msgChildrenVar, childrenVar, indexOffsetVar = sid_to_vars[loc['scriptId']]
                
                # Converting the Protobuf structure object into JSON
                # isn't possible since it has circular references, and
                # accessing variables individually through the API is
                # very slow, so conversion to text is done on the
                # JavaScript side.
                
                send(ws, 'Debugger.evaluateOnCallFrame', {
                    'callFrameId': msg['callFrames'][0]['callFrameId'],
                    'expression': '''
var objToName = new WeakMap();
var typeArray = {'d': 'double', 'f': 'float', 'i': 'int32', 'j': 'int64', 'u': 'uint32', 'v': 'uint64', 'x': 'fixed32', 'y': 'fixed64', 'g': 'sfixed32', 'h': 'sfixed64', 'n': 'sint32', 'o': 'sint64', 'e': 'enum', 's': 'string', 'z': 'string (base64)', 'B': 'bytes', 'b': 'bool', 'm': 'message'};
var labelArray = {1: 'optional', 2: 'required', 3: 'repeated'};
var namerGen = function* () {
    for(var len = 0; ; len++)
        yield* (function* namer2(len) {
            for(var char of 'abcdefghijklmnopqrstuvwxyz')
                for(var suffix of len ? namer2(len - 1) : [''])
                    yield char + suffix;
        })(len);
};
var parseMsg = function(msg, tab, name) {
    var namer = namerGen();
    var namer_msg = namerGen();
    
    var text = `${tab}message ${name.split('.').pop()} {\\n`;
    tab += '    ';
    objToName.set(msg, name);
    msg = msg.%s;
    
    for(var i in msg) {
        var label = labelArray[msg[i].label];
        var type = typeArray[msg[i].type];
        var cmt = '';
        if(type == 'enum') {
            cmt = ' // enum';
            type = 'int32';
        }
        if(type == 'message') {
            type = objToName.get(msg[i].%s);
            if(!type) {
                type = namer_msg.next().value;
                type = `${name}.${type[0].toUpperCase()}${type.slice(1)}`;
                text += parseMsg(msg[i].%s, tab, type);
            }
            if(type.split('.').slice(0, -1).join('.') == name) {
                type = type.split('.').pop();
            }
            var def = '';
        }
        else {
            var def = msg[i].%s;
            if(def && (type == 'string' || type == 'string (base64)' || type == 'bytes')) {
                def = `"${def}"`;
            }
            def = def ? ` [default = ${def}]` : '';
        }
        text += `${tab}${label} ${type} ${namer.next().value} = ${i}${def};${cmt}\\n`;
    }
    
    return `${text}${tab.slice(0, -4)}}\n`;
};
console.log(JSON.stringify(['__HOOK', [parseMsg(b, '', 'Top'), c.join('')[0] === '!' ? c.join('') : c.join('&').replace(/'/g, '%%27')]]));''' % (childrenVar, msgChildrenVar, msgChildrenVar, defaultVar)
                })
            
            if not awaiting_srcs:
                send(ws, 'Debugger.resume')

        elif call == 'Runtime.consoleAPICalled':
            msg = msg['args'][0]['value']
            if '__URL' in msg:
                logUrl(loads(msg)[1])
            elif '__HOOK' in msg:
                proto, protoMsg = loads(msg)[1]
                
                proto = 'syntax = "proto2";\n\n' + proto
                
                if protoMsg:
                    sent_msgs[protoMsg] = proto
                    sent_msgs[protoMsg.replace(' ', '+')] = proto
                    sent_msgs[quote(protoMsg, safe='~()*!.')] = proto
                    sent_msgs[quote(protoMsg, safe='~()*!.\'')] = proto
                    sent_msgs[quote(protoMsg, safe='~()*!.\':')] = proto
                    sent_msgs[quote_plus(protoMsg, safe='~()*!.')] = proto
                    sent_msgs[quote_plus(protoMsg, safe='~()*!.\'')] = proto
                    sent_msgs[quote_plus(protoMsg, safe='~()*!.\':')] = proto
    
    elif 'error' in msg:
        req_id, error = msg['id'], msg['error']
        call, data = req_data.pop(req_id)
        if call in ('Debugger.resume', 'Debugger.evaluateOnCallFrame'):
            return
        if call == 'Debugger.getScriptSource':
            sid = error['message'].split(': ')[1]
            awaiting_srcs.remove(sid)
            if not awaiting_srcs:
                send(ws, 'Debugger.resume')
            return
        print('[Error]', call + ':', error)
        exit()
    
    else:
        req_id, msg = msg['id'], msg['result']
        call, data = req_data.pop(req_id)
        
        if call == 'Debugger.getScriptSource':
            sid, padding = data
            src = padding + msg['scriptSource']
            
            targets = ['0);return c.join("")}', 'return c.join("&").replace(']
            for target in targets:
                if target in src:
                    needle = search('\.label=b;this\.([\w$]+)=c;this\.([\w$]+)=d', src)
                    if needle:
                        defaultVar, msgChildrenVar = needle.groups()
                    else:
                        defaultVar, msgChildrenVar = 'none', search('"m"==b\.type&&\(c\+=\w+\(a,b\.([\w$]+)', src).group(1)
                    childrenVar, indexOffsetVar = search('\w=\w\.([\w$]+)\[\w\],\w=a\[\w\+\(?b\.([\w$]+)', src).groups()
                    before = src.split(target)[0]
                    sid_to_vars[sid] = defaultVar, msgChildrenVar, childrenVar, indexOffsetVar
                    
                    send(ws, 'Debugger.setBreakpoint', {
                        'location': {
                            'scriptId': sid,
                            'lineNumber': before.count('\n'),
                            'columnNumber': len(before.split('\n')[-1])
                        }
                    })
                    print('[Script successfully hooked]')
            
            awaiting_srcs.remove(sid)
            if not awaiting_srcs:
                send(ws, 'Debugger.resume')

def logUrl(url):
    url = sub('//www.google.[a-z]+', '//www.google.com', url)
    if '=!' in url:
        datas = findall('(?<==)\!\d[^/?&]+', url)
    else:
        datas = [i.strip('?&') for i in findall('\?(?:\d[^&]+&?)+', url)]
    if not datas:
        return
    for data in sorted(datas, key=len, reverse=True):
        if data in sent_msgs:
            proto = sent_msgs[data]
            
            url = url.replace('/pb=', '?pb=')
            if '?' not in url:
                url += '?'
            url, qs = url.split('?')

            if '=!' in url + '?' + qs:
                qsl = OrderedDict(parse_qsl(qs, True))
                for k, v in findall('/(space/|place/|search/|contrib/|[^/]+=|@)([^/]*)', url) +\
                            findall('/(dir/)([^/]*/[^/]*)', url):
                    k2 = k.strip('/=') if k != '@' else 'coords'
                    if '/' not in v:
                        qsl[k2] = unquote_plus(v)
                        url = url.replace(k + v, k + '{' + k2 + '}')
                    else:
                        qsl[k2+'1'], qsl[k2+'2'] = map(unquote_plus, v.split('/'))
                        url = url.replace(k + v, k + '{%s1}/{%s2}' % (k2, k2))
                qs = urlencode(qsl)
                
                pb_param = next(k for k, v in qsl.items() if v == unquote_plus(data))
                endpoints.append({
                    'transport': 'pburl_private',
                    'proto_path': '',
                    'proto_msg': '',
                    'url': url,
                    'pb_param': pb_param,
                    'samples': [GMapsAPIPrivate(pb_param, url).serialize_sample(qs)]
                })

            else:
                endpoints.append({
                    'transport': 'pburl_public',
                    'proto_path': '',
                    'proto_msg': '',
                    'url': url,
                    'samples': [GMapsAPIPublic(None, url).serialize_sample(qs)]
                })
            
            print('[Captured]', url, qs, data)
            if proto not in proto_to_urls:
                proto_to_urls[proto] = set()
            proto_to_urls[proto].add(url)
            return
    
    print('[Not captured]', url, data)

if __name__ == '__main__':
    extractor_main('pburl_extract')
