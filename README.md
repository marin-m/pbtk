# pbtk - Reverse engineering Protobuf apps

**[Protobuf](https://developers.google.com/protocol-buffers/) is a serialization format** developed by Google and used in an increasing number of Android, web, desktop and more applications. It consists of a **language for declaring data structures**, which is then compiled to code or another kind of structure depending on the target implementation.

pbtk (*Protobuf toolkit*) is a full-fledged set of scripts, accessible through an unified GUI, that provides two main features:

- **Extracting Protobuf structures from programs**, converting them back into readable *.proto*s, supporting various implementations:
  - All the main Java runtimes (base, Lite, Nano, Micro, J2ME), with full Proguard support,
  - Binaries containing embedded reflection metadata (typically C++, sometimes Java and most other bindings),
  - Web applications using the JsProtoUrl runtime.

- **Editing, replaying and fuzzing data** sent to Protobuf network endpoints, through a handy graphical interface that allows you to edit live the fields for a Protobuf message and view the result.

![The pbtk editor GUI](https://i.imgur.com/7w6ABqy.png)

## Installation

PBTK requires Python ≥ 3.5, PyQt 5, Python-Protobuf 3, and a handful of executable programs (chromium, jad, dex2jar...) for running extractor scripts.

Archlinux users can install directly through the [package](https://aur.archlinux.org/packages/pbtk-git/):

```
$ yaourt -S pbtk-git
$ pbtk
```

On most other distributions, you'll want to run it directly:

```tcl
# For Ubuntu/Debian testing derivates:
$ sudo apt install python3-pip git openjdk-9-jre

$ sudo pip3 install protobuf pyqt5 requests websocket-client

$ git clone https://github.com/marin-m/pbtk
$ cd pbtk
$ ./gui.py
```

Windows is also supported (with the same modules required). Once you run the GUI, it should warn you on what you are missing depending on what you try to do.

## Command line usage

The GUI can be lanched through the main script:

    ./gui.py

The following scripts can also be used standalone, without a GUI:

    ./extractors/jar_extract.py [-h] input_file [output_dir]
    ./extractors/from_binary.py [-h] input_file [output_dir]
    ./extractors/web_extract.py [-h] input_url [output_dir]


## Typical workflow

Let's say you're reverse engineering an Android application. You explored a bit the application with your favorite decompiler, and figured it transports Protobuf as POST data over HTTPS in a typical way.

You open PBTK and are greeted in a meaningful manner:

![The welcome screen](https://i.imgur.com/oVsypWN.png)

The first step is getting your .protos into text format. If you're targeting an Android app, dropping in an APK and waiting should do the magic work! (unless it's a really exotic implementation)

![Done screen](https://i.imgur.com/uC9dnWV.png)

This being done, you jump to `~/.pbtk/protos/<your APK name>` (either through the command line, or the button on the bottom of the welcome screen to open your file browser, the way you prefer). All the app's .protos are indeed here.

Back in your decompiler, you stumbled upon the class that constructs data sent to the HTTPS endpoint that interests you. It serializes the Protobuf message by calling a class made of generated code.

![Your decompiler](https://i.imgur.com/x9YAChW.png)

This latter class should have a perfect match inside your .protos directory (i.e `com.foo.bar.a.b` will match `com/foo/bar/a/b.proto`). Either way, grepping its name should enable you to reference it.

That's great: the next thing is going to **Step 2**, selecting your desired input .proto, and filling some information about your endpoint.

![Endpoint creation form](https://i.imgur.com/jhu68pG.png)

You may also give some sample raw Protobuf data, that was sent to this endpoint, captured through mitmproxy or Wireshark, and that you'll paste in a hex-encoded form.

**Step 3** is about the fun part of clicking buttons and seeing what happens! You have a tree view representing every field in the Protobuf structure (repeated fields are suffixed by "+", required fields don't have checkboxes).

![Endpoint creation form](https://i.imgur.com/2lVmGoG.png)

Just hover a field to have focus. If the field is an integer type, use the mouse wheel to increment/decrement it. Enum information appears on hover too.

Here it is! You can determine the meaning of every field with that. If you extracted .protos out of minified code, you can rename fields according to what you notice they mean, by clicking their names.

Happy reversing! 👌 🎉

## Local data storage

PBTK stores extracted .proto information into `~/.pbtk/protos/` (or `%APPDATA%\pbtk\protos` on Windows).

You can move in, move out, rename, edit or erase data from this directory directly through your regular file browser and text editor, it's the expected way to do it and won't interfere with PBTK.

HTTP-based endpoints are stored into `~/.pbtk/endpoints/` as JSON objects. These objects are arrays of pairs of request/response information, which looks like this:

```javascript
[{
    "request": {
        "transport": "pburl",
        "proto": "www.google.com/VectorTown.proto",
        "url": "https://www.google.com/VectorTown",
        "pb_param": "pb",
        "samples": [{
            "pb": "!....",
            "hl": "fr"
        }]
    },
    "response": {
        "format": "other"
    }
}]
```

## Source code structure

PBTK uses two kinds of pluggable modules internally: extractors, and transports.

* An **extractor** supports extracting .proto structures from a target Protobuf implementation or platform.

Extractors are defined in `extractors/*.py`. They are defined as a method preceded by a decorator, like this:

```python
@register_extractor(name = 'my_extractor',
                    desc = 'Extract Protobuf structures from Foobar code (*.foo, *.bar)',
                    depends={'binaries': ['foobar-decompiler']})
def my_extractor(path):
    # Load contents of the `path` input file and do your stuff...
    
    # Then, yield extracted .protos using a generator:
    for i in do_your_extraction_work():
        yield proto_name + '.proto', proto_contents
    
    # Other kinds of information can be yield, such as endpoint information or progress to display.
```

* A **transport** supports a way of deserializing, reserializing and sending Protobuf data over the network. For example, the most commonly used transport is raw POST data over HTTP.

Transports are defined in `utils/transports.py`. They are defined as a class preceded by a decorator, like this:

```python
@register_transport(
    name = 'my_transport',
    desc = 'Protobuf as raw POST data',
    ui_data_form = 'hex strings'
)
class MyTransport():
    def __init__(self, pb_param, url):
        self.url = url
    
    def serialize_sample(self, sample):
        # We got a sample of input data from the user.
        # Verify that it is valid in the form described through "ui_data_form" parameter, fail with an exception or return False otherwise.
        # Optionally modify this data prior to returning it.
        bytes.fromhex(sample)
        return sample
    
    def load_sample(self, sample, pb_msg):
        # Parse input data into the provided Protobuf object.
        pb_msg.ParseFromString(bytes.fromhex(sample))
    
    def perform_request(self, pb_data, tab_data):
        # Perform a request using the provided URL and Protobuf object, and optionally other transport-specific side data.
        return post(url, pb_data.SerializeToString(), headers=USER_AGENT)
```

## Forthcoming improvements

The following could be coming for further releases:
* Finishing the automatic fuzzing part.
* Support for extracting extensions out of Java code.
* Support for the JSPB (main JavaScript) runtime.
* If there's any other platform you wish to see supported, just drop an issue and I'll look at it.

I've tried to do my best to produce thoroughly readable and commented code (except for parts that are mostly self-describing, like connecting GUI signals) for most modules, so you can contribute.


## Licensing

As pbtk uses PyQt, it is released under the [GNU GPL](https://www.gnu.org/licenses/gpl-3.0.html) license (I, hereby, etc.) I would likely have chosen something public domain-like otherwise.

There's no formalized rule for the letter case of the project name, the rule is just about following your heart ❤

