#!/usr/bin/python3
#-*- encoding: Utf-8 -*-
from urllib.parse import quote_plus, urlencode, parse_qsl, urlparse, unquote
from utils.pburl_decoder import proto_url_encode, proto_url_decode
from utils.common import register_transport
from collections import OrderedDict
from requests import get, post
from functools import reduce
from re import sub, match
from json import loads

USER_AGENT = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.116 Safari/537.36'}

@register_transport(
    name = 'raw_post',
    desc = 'Protobuf as raw POST data',
    ui_tab = 'Headers',
    ui_data_form = 'hex strings'
)
class RawPOST():
    def __init__(self, pb_param, url):
        self.url = url
    
    def serialize_sample(self, sample):
        bytes.fromhex(sample)
        return sample
    
    def load_sample(self, sample, pb_msg):
        pb_msg.ParseFromString(bytes.fromhex(sample))
        self.headers = OrderedDict(USER_AGENT)
        self.headers['Content-Type'] = 'application/x-protobuf'
        return self.headers
    
    def perform_request(self, pb_data, tab_data):
        return post(self.url, pb_data.SerializeToString(), headers=self.headers)

my_quote = lambda x: quote_plus(str(x), safe='~()*!.')

@register_transport(
    name = 'pburl_private',
    desc = 'Protobuf-URL, Google Maps private API style ("!"-separated)',
    ui_tab = 'GET',
    ui_data_form = 'regular GET query strings'
)
class GMapsAPIPrivate():
    def __init__(self, pb_param, url):
        self.pb_param = pb_param
        self.url = url.split('?')[0]
    
    def serialize_sample(self, sample):
        sample = OrderedDict(parse_qsl(sample))
        if self.pb_param not in sample:
            return False
        if 'token' in sample:
            del sample['token']
        if 'callback' in sample:
            sample['callback'] = ''
        return sample
    
    def load_sample(self, sample, pb_msg):
        sample = OrderedDict(sample or {self.pb_param: ''})
        if 'callback' in sample:
            sample['callback'] = '_xdc_._'
        proto_url_decode(sample.pop(self.pb_param), pb_msg)
        return sample
    
    def perform_request(self, pb_data, tab_data):
        params = OrderedDict({self.pb_param: proto_url_encode(pb_data)})
        params.update(tab_data)
        url = sub('\{(\w+)\}', lambda i: my_quote(params.pop(i.group(1), '')), self.url)
        if params:
            url += '?' + urlencode(params, safe='~()*!.') # Do not escape '!' for readibility.
        return get(url, headers=USER_AGENT)

@register_transport(
    name = 'pburl_public',
    desc = 'Protobuf-URL, Google Maps public API style ("&"-separated)',
    ui_tab = 'GET',
    ui_data_form = 'GET query strings copied as-is'
)
class GMapsAPIPublic():
    def __init__(self, pb_param, url):
        self.url = url.split('?')[0]
    
    def serialize_sample(self, sample):
        sample = self.parse_qs(sample)
        if 'token' in sample:
            del sample['token']
        if 'callback' in sample:
            sample['callback'] = ''
        return self.rebuild_qs(sample)
    
    def parse_qs(self, sample):
        pb = match('(?:&?\d[^&=]+)*', sample)
        return OrderedDict([(pb.group(0), ''),
                            *parse_qsl(sample[pb.end() + 1:], True)])
    
    def rebuild_qs(self, sample):
        return '&'.join(k if not k or k[0].isdigit() else
                        my_quote(k) + '=' + my_quote(v)
                        for k, v in sample.items())
    
    def load_sample(self, sample, pb_msg):
        sample = self.parse_qs(sample)
        pb_data = '&'.join(k for k in sample.keys()
                             if not k or k[0].isdigit())
        get_data = OrderedDict((k, v) for k, v in sample.items()
                                      if k and not k[0].isdigit())
        if 'callback' in get_data:
            get_data['callback'] = '_xdc_._'
        proto_url_decode(pb_data, pb_msg, '&')
        return get_data
    
    def perform_request(self, pb_data, tab_data):
        params = OrderedDict({proto_url_encode(pb_data, '&'): ''})
        params.update(tab_data)
        params['token'] = self.hash_token(urlparse(self.url).path + '?' + self.rebuild_qs(params))
        return get(self.url + '?' + self.rebuild_qs(params), headers=USER_AGENT)
    
    def hash_token(self, url):
        if not hasattr(self, 'token'):
            self.token = get('https://maps.google.com/maps/api/js', headers=USER_AGENT).text
            self.token = loads(self.token.split('apiLoad(')[1].split(', ')[0])[4][0]
        mask = (1 << 17) - 1
        return reduce(lambda a, b: a * 1729 + ord(b), url, self.token) % mask
