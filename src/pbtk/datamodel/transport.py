# ⚠️ WIP

from google.protobuf.message import Message
from abc import ABC, abstractmethod

# ⚠️ SEE https://docs.python.org/fr/3/library/abc.html#abc.abstractproperty
# to replace decorator arguments

"""
    Abstract class used to define a possible wire transport
    for Protobuf data requests
"""
@ABC
class Transport:

    """
        Used to refer to in JSON data files
    """
    @property
    @abstractmethod
    def name() -> str:
        ...

    """
        Used to describe protocol in GUI
    """
    @property
    @abstractmethod
    def description() -> str:
        ...

    """
        Used to name the protocol data tab in fuzzer GUI (if any)
    """
    @property
    @abstractmethod
    def ui_tab() -> str | None:
        ...

    """
        Used to describe the nature of protocol data
    """
    @property
    @abstractmethod
    def ui_data_form() -> str | None:
        ...

    """
        Whether keys in protocol data are integer
    """
    @property
    @abstractmethod
    def enforce_int_parameter() -> bool:
        ...

    pb_param: str | None
    url: str

    def __init__(self, pb_param, url):
        self.pb_param = pb_param
        self.url = url

    """
        We got a sample of input data from the user.
        Verify that it is valid in the form described
        through "ui_data_form" parameter, fail with an
        exception or return False otherwise.

        Optionally modify this data prior to returning it.

    """
    @abstractmethod
    def serialize_sample(self, sample: str) -> str | dict:
        ...

    """
        Parse input data into the provided Protobuf object.
    """
    @abstractmethod
    def load_sample(self, sample: str | dict, pb_msg: Message):
        ...

    """
        Perform a request using the provided URL and Protobuf
        object, and optionally other transport-specific side data.
    """
    @abstractmethod
    def perform_request(self, pb_data: Message, tab_data: dict | None):
        ...
