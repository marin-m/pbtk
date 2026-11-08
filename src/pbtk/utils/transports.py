#!/usr/bin/env python3
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse
from base64 import urlsafe_b64decode, urlsafe_b64encode
from google.protobuf.message import Message
from collections import OrderedDict
from functools import reduce
from re import match, sub
from requests import get
from json import loads


from pbtk.datamodel.transport import Transport
from pbtk.utils.common import register_transport
from pbtk.utils.pburl_decoder import (
    proto_url_decode,
    proto_url_check_format,
    proto_url_encode,
)

import gi

gi.require_version('Soup', '3.0')

from gi.repository import GLib, Soup

USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.116 Safari/537.36'


# ⚠️ ===> TURN DECORATOR ARGUMENTS INTO ABC BASE CLASS
#    ABSTRACT PROPERTIES?


@register_transport
class RawPOST(Transport):
    name = 'raw_post'
    description = 'Protobuf as raw POST data'
    ui_tab = 'Headers'
    ui_data_form = 'hex strings'
    has_pb_param = False

    def __init__(self, pb_param: None, url: str):
        self.url = url

    def serialize_sample(self, sample: str) -> str:
        bytes.fromhex(sample)
        return sample

    def load_sample(self, sample: str, pb_msg: Message) -> dict:
        pb_msg.ParseFromString(bytes.fromhex(sample))
        self.headers = OrderedDict({'User-Agent': USER_AGENT})
        self.headers['Content-Type'] = 'application/x-protobuf'
        return self.headers

    def create_request(
        self, pb_data: Message, tab_data: dict | None
    ) -> Soup.Message:
        msg = Soup.Message.new('POST', self.url)
        msg.set_request_body_from_bytes(
            None, GLib.Bytes.new(pb_data.SerializeToString())
        )

        headers: Soup.MessageHeaders = msg.get_request_headers()

        for key, value in self.headers.items():
            headers.append(key, value)

        return msg


def my_quote(x: str) -> str:
    return quote_plus(str(x), safe='~()*!.')


@register_transport
class Base64GET(Transport):
    name = 'base64_get'
    description = 'Protobuf as Base64url GET component (use "{param_name}" for templating)'
    ui_tab = 'GET'
    ui_data_form = 'regular GET query strings'
    has_pb_param = True

    def __init__(self, pb_param: str, url: str):
        self.pb_param = pb_param
        self.url = url.split('?')[0]

    def serialize_sample(self, sample: str) -> dict | bool:
        sample = OrderedDict(parse_qsl(sample, keep_blank_values=True))
        if self.pb_param not in sample:
            return False
        base64 = sample[self.pb_param]
        urlsafe_b64decode(base64 + '=' * (4 - len(base64) % 4))
        return sample

    def load_sample(self, sample: dict, pb_msg: Message) -> dict:
        sample = OrderedDict(sample or {self.pb_param: ''})
        base64 = sample.pop(self.pb_param)
        base64 = urlsafe_b64decode(base64 + '=' * (4 - len(base64) % 4))
        pb_msg.ParseFromString(base64)
        return sample

    def create_request(
        self, pb_data: Message, tab_data: dict | None
    ) -> Soup.Message:
        base64 = urlsafe_b64encode(pb_data.SerializeToString()).decode('utf8')
        params = OrderedDict({self.pb_param: base64.strip('=')})
        params.update(tab_data)
        url = sub(
            r'\{(\w+)\}',
            lambda i: my_quote(params.pop(i.group(1), '')),
            self.url,
        )
        if params:
            url += '?' + urlencode(
                params, safe='~()*!.'
            )  # Do not escape '!' for readibility.

        msg = Soup.Message.new('GET', url)

        headers: Soup.MessageHeaders = msg.get_request_headers()
        headers.append('User-Agent', USER_AGENT)

        return msg


@register_transport
class GMapsAPIPrivate(Transport):
    name = 'pburl_private'
    description = 'Protobuf-URL, Google Maps private API style ("!"-separated)'
    ui_tab = 'GET'
    ui_data_form = 'regular GET query strings'
    has_pb_param = True

    def __init__(self, pb_param: str, url: str):
        self.pb_param = pb_param
        self.url = url.split('?')[0]

    def serialize_sample(self, sample: str) -> dict | bool:
        sample = OrderedDict(parse_qsl(sample, keep_blank_values=True))
        if self.pb_param not in sample:
            return False
        if 'token' in sample:
            del sample['token']
        if 'callback' in sample:
            sample['callback'] = ''
        if not proto_url_check_format(sample[self.pb_param]):
            return False
        return sample

    def load_sample(self, sample: dict, pb_msg: Message) -> dict:
        sample = OrderedDict(sample or {self.pb_param: ''})
        if 'callback' in sample:
            sample['callback'] = '_xdc_._'
        proto_url_decode(sample.pop(self.pb_param), pb_msg)
        return sample

    def create_request(
        self, pb_data: Message, tab_data: dict | None
    ) -> Soup.Message:
        params = OrderedDict({self.pb_param: proto_url_encode(pb_data)})
        params.update(tab_data)
        url = sub(
            r'\{(\w+)\}',
            lambda i: my_quote(params.pop(i.group(1), '')),
            self.url,
        )
        if params:
            url += '?' + urlencode(
                params, safe='~()*!.'
            )  # Do not escape '!' for readibility.

        msg = Soup.Message.new('GET', url)

        headers: Soup.MessageHeaders = msg.get_request_headers()
        headers.append('User-Agent', USER_AGENT)

        return msg


@register_transport
class GMapsAPIPublic(Transport):
    name = 'pburl_public'
    description = 'Protobuf-URL, Google Maps public API style ("&"-separated)'
    ui_tab = 'GET'
    ui_data_form = 'GET query strings copied as-is'
    has_pb_param = False

    def __init__(self, pb_param: None, url: str):
        self.url = url.split('?')[0]

    def serialize_sample(self, sample: str) -> str:
        sample = self.parse_qs(sample)
        if 'token' in sample:
            del sample['token']
        if 'callback' in sample:
            sample['callback'] = ''
        return self.rebuild_qs(sample)

    def parse_qs(self, sample: str) -> dict:
        pb = match(r'(?:&?\d[^&=]+)*', sample)
        return OrderedDict(
            [
                (pb.group(0), ''),
                *parse_qsl(sample[pb.end() + 1 :], keep_blank_values=True),
            ]
        )

    def rebuild_qs(self, sample: str) -> str:
        return '&'.join(
            k if not k or k[0].isdigit() else my_quote(k) + '=' + my_quote(v)
            for k, v in sample.items()
        )

    def load_sample(self, sample: str, pb_msg: Message) -> dict:
        sample = self.parse_qs(sample)
        pb_data = '&'.join(k for k in sample if not k or k[0].isdigit())
        get_data = OrderedDict(
            (k, v) for k, v in sample.items() if k and not k[0].isdigit()
        )
        if 'callback' in get_data:
            get_data['callback'] = '_xdc_._'
        proto_url_decode(pb_data, pb_msg, '&')
        return get_data

    def create_request(
        self, pb_data: Message, tab_data: dict | None
    ) -> Soup.Message:
        params = OrderedDict({proto_url_encode(pb_data, '&'): ''})
        params.update(tab_data)
        params['token'] = self.hash_token(
            urlparse(self.url).path + '?' + self.rebuild_qs(params)
        )

        msg = Soup.Message.new('GET', self.url + '?' + self.rebuild_qs(params))

        headers: Soup.MessageHeaders = msg.get_request_headers()
        headers.append('User-Agent', USER_AGENT)

        return msg

    def hash_token(self, url: str) -> int:
        if not hasattr(self, 'token'):
            self.token = get(
                'https://maps.google.com/maps/api/js',
                headers={'User-Agent': USER_AGENT},
            ).text
            self.token = loads(self.token.split('apiLoad(')[1].split(', ')[0])[
                4
            ][0]
        mask = (1 << 17) - 1
        return reduce(lambda a, b: a * 1729 + ord(b), url, self.token) % mask
