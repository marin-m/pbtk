#!/usr/bin/env python3

from abc import ABC, abstractmethod

from gi.repository import GObject
from google.protobuf.message import Message
from requests import Response

# ⚠️ SEE https://docs.python.org/fr/3/library/abc.html#abc.abstractproperty
# to replace decorator arguments

"""
    Abstract class used to define a possible wire transport
    for Protobuf data requests
"""


class Transport(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Used to refer to in JSON data files"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Used to describe protocol in GUI"""
        ...

    """Used to name the protocol data tab in fuzzer GUI (if any)"""
    ui_tab: str | None = None

    """Used to describe the nature of protocol data"""
    ui_data_form: str | None = None

    """Whether keys in protocol data are integer"""
    enforce_int_parameter: bool = False

    has_pb_param: bool = False

    pb_param: str | None = None
    url: str

    def __init__(self, pb_param, url):
        self.pb_param = pb_param
        self.url = url

    @abstractmethod
    def serialize_sample(self, sample: str) -> str | dict | bool:
        """
        We got a sample of input data from the user.
        Verify that it is valid in the form described
        through "ui_data_form" parameter, fail with an
        exception or return False otherwise.

        Optionally modify this data prior to returning it,
        so that it can readily be serialized in the saved
        JSON endpoint information file.
        """
        ...

    @abstractmethod
    def load_sample(self, sample: str | dict, pb_msg: Message) -> dict:
        """
        Parse data returned by serialize_sample() and
        stored into pbtk's disk-persistent JSON state
        into the provided Protobuf object, and return
        editable additional protocol-specific data (extra
         query string part if any, or extra HTTPS
         headers if the input is a raw ex-encoded
         binary POST body)
        """
        ...

    @abstractmethod
    def perform_request(
        self, pb_data: Message, tab_data: dict | None
    ) -> Response:
        """
        Perform a request using the provided URL and Protobuf
        object, and optionally other transport-specific side data.
        """
        ...


"""
    Used to list transport types in the GUI
"""


class TransportDefinition(GObject.Object):
    __gtype_name__ = 'TransportDefinition'

    description = GObject.Property(type=str)
    transport_class: Transport

    def __init__(self, transport_class):
        super().__init__()

        self.description = transport_class.description
        self.transport_class = transport_class
