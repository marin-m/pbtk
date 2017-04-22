#!/usr/bin/python3
#-*- encoding: Utf-8 -*-
from re import findall, MULTILINE, search, finditer, split, sub
from subprocess import run, DEVNULL, PIPE, TimeoutExpired
from tempfile import TemporaryDirectory
from collections import OrderedDict
from zipfile import ZipFile
from os.path import exists

from extractors.from_binary import walk_binary
from utils.common import dex2jar, jad

"""
    This is a catch-all class that will handle either a JAR, DEX or APK file.
"""
class JarWrapper(TemporaryDirectory):
    def __init__(self, fname):
        super().__init__()
        
        self.classes = []
        self.decompiled = {}
        
        self.bonus_protos = OrderedDict()
        
        self.handle_file(fname)

    def handle_file(self, fname):
        with open(fname, 'rb') as fd:
            if fd.read(4) == b'dex\n':
                new_jar = self.name + '/classes-dex2jar.jar'
                run([dex2jar, fname, '-f', '-o', new_jar], cwd=self.name, stderr=DEVNULL)
                fname = new_jar
    
        with ZipFile(fname) as jar:
            jar.extractall(self.name)
            
            for cls in jar.namelist():
                if cls.endswith('.class'):
                    cls = cls.replace('/', '.')[:-6]
                    self.classes.append(cls)
                
                elif cls.endswith('.dex'):
                    self.handle_file(self.name + '/' + cls)
                
                elif cls.endswith('.proto'):
                    self.bonus_protos[cls] = jar.read(cls).decode('utf8')
                
                elif cls.endswith('.so'):
                    self.bonus_protos.update(walk_binary(self.name + '/' + cls))
            
    def __enter__(self):
        super().__enter__()
        return self
    
    def read(self, cls):
        cls = cls.replace('.', '/') + '.class'
        with open(self.name + '/' + cls, 'rb') as fd:
            return fd.read()
    
    def decomp(self, cls, no_parse=False):
        if cls not in self.decompiled:
            # Handle generated class files containing a "$"
            if cls not in self.classes:
                _cls = cls
                pkg, cls = cls.rsplit('.', 1)
                cls = next((i for i in self.classes if i.startswith(pkg) and i.endswith('$' + cls)), _cls)
            
            if no_parse:
                return ClassWrapper(cls, self, True)
            self.decompiled[cls] = ClassWrapper(cls, self)
        
        return self.decompiled[cls]
    
    # Will return only a specific method from class, with its local method calls inlined
    
    def decomp_func(self, func, merged=None):
        ret, obj, name, args = func
        if obj.startswith('java.'):
            return ''
        decomp = self.decomp(obj)
        if decomp.raw:
            decomp = decomp.get_method_unfold((ret, name, args), merged)
        else:
            decomp = ''
        return decomp

"""
    A class to perform decompilation and basic parsing of Java classes.
"""
class ClassWrapper:
    def __init__(self, cls, jar, no_parse=False):
        inpath = jar.name + '/' + cls.replace('.', '/') + '.class'
        outpath = jar.name + '/' + cls.replace('.', '/') + '.java'
        
        jad_args = [jad, '-af', '-b', '-d', jar.name, '-dead', '-f', '-i', '-ff', '-noinner', '-o', '-r', '-radix10', '-lradix10', '-s', '.java', inpath]
        if no_parse:
            jad_args.remove('-af')
            jad_args.insert(1, '-nofd')
        try:
            run(jad_args, timeout=5, cwd=jar.name, stdout=DEVNULL, stderr=DEVNULL)
        except TimeoutExpired:
            print('(Jad timed out)')

        if not exists(outpath):
            self.raw = ''
            return
        
        with open(outpath) as fd:
            self.raw = fd.read()
        
        if not self.raw.strip().endswith('\n}'): # Truncated source
            self.raw = ''
        if self.raw.count('{\n    }') == self.raw.count(' {'): # Interface or abstract
            self.raw = ''
        
        if not self.raw or no_parse:
            return
        
        # Parse Jad annotations
        self.annotes = []
        while True:
            annote = search('\n {4,}//(?:[* ] {0,3}[0-9]{1,5}){2}:.+(?:\n {4,}//.+)*', self.raw, flags=MULTILINE)
            if not annote:
                break
            self.annotes.extend(findall('<Method ([\w.$\[\]]+) ([\w.$]+)\.([\w$]+)\((.*)\)>', annote.group(0)))
            self.raw = self.raw[:annote.start()] + self.raw[annote.end():]
        
        # Parse package/extends directives
        
        self.pkg = search('^package (.+?);', self.raw, flags=MULTILINE) or ''
        if self.pkg:
            self.pkg = self.pkg.group(1)
        
        self.extends = search(' extends ([\w.$]+)', self.raw) or ''
        if self.extends:
            self.extends = self.extends.group(1)
            
            if self.annotes and '.'.join(self.annotes[0][1:3]) == self.extends:
                self.annotes.pop(0)
        
        # Handle CodedOutputStream subclasses
        if 'write as much data as' in self.raw and 'return new ' in self.raw:
            self.extends = self.raw.split('return new ')[1].split('(')[0]
            if self.pkg and '.' not in self.extends:
                self.extends = self.pkg + '.' + self.extends
        
        self.jar = jar
        self.cls = cls
        
        """
        Iterate over Java code in order to gather some information:
        
        1. Store methods' code, along with their calls to both local and external other methods.
        
        2. Store bounds for methods and first-level conditions blocks.
        """
    
        self.method_cache = OrderedDict()

        self.method_calls = OrderedDict()
        self.method_loc_calls = OrderedDict()

        self.method_bounds = OrderedDict() # Blocks with 1st level indent
        self.cond_bounds = [] # Blocks with 2nd level indent

        last_indent = 0 # Defines indent at previous iteration
        cls_indent = 0 # Defines indent at class definition-level
        cond_indent = 0 # Defined indent at last block condition-level
        
        method_sig = None # Checked to know whether we're in a method
        cond_start = None # Checked to know whether we're in a condition block
        
        pos = 0 # Keep track of position in file
        
        for line in self.raw.splitlines(True):
            indent = (len(line) - len(line.lstrip(' '))) / 4

            if line.strip().startswith('throws') or line.strip().startswith('implements ') or line.strip().startswith('//'):
                pos += len(line)
                continue
            
            # We see a class declaration
            if ' class ' in line or (' new ' in line and line.strip().endswith('{')):
                cls_indent = indent
            
            # We see a method declaration
            if indent == cls_indent + 1 and line.strip().endswith(')'):
                funcline = search('([\w.$]+) ([\w$]+)\((.*)\)', line)
                
                if funcline and funcline.group(2) not in ('if', 'for', 'while', 'switch', 'catch', 'super', 'this', 'synchronized'):
                    ret, name, args = funcline.groups()
                    method_sig = (ret, name, ', '.join(i.split(' ')[0] for i in args.split(', ')))

                    method_code = ''
                    method_loc_calls = []
                    method_glob_calls = []
            
            # We're entering a method
            if method_sig:
                if indent >= cls_indent + 2 > last_indent:
                    method_start = pos
                
                if indent >= cls_indent + 2 and line.strip().endswith(')') and not cond_indent:
                    cond_start = pos
                    cond_indent = indent
                elif line.startswith('label') and not cond_indent:
                    cond_start = pos
                
                # We're in a method
                if indent >= cls_indent + 2:
                    
                    nostrings_line = sub(r'"(?:.*?[^"\\])?"', '""', line)
                    
                    # Store calls to local methods
                    for match in finditer('(?<!new )(?<![\w.$])(\w+)\((?=([^;]+))', nostrings_line):
                        if match.group(1) not in ('if', 'for', 'while', 'switch', 'catch', 'super', 'this', 'synchronized', 'getClass'):
                            (name, args), (call_start, call_end) = match.groups(), match.span()
                            
                            ret, obj, name, args = self.prototype_from_annote(name, args)
                            call_sig = ret, name, args
                            
                            self.method_loc_calls[call_start + pos] = (call_sig, call_end + pos)
                            method_loc_calls.append(call_sig)
                    
                    # Store calls to external methods
                    for match in reversed(list(finditer('\.(\w+)\((?=([^;]+))', nostrings_line))):
                        (name, args), (call_start, call_end) = match.groups(), match.span()
                        
                        call_sig = self.prototype_from_annote(name, args)
                        
                        self.method_calls[call_start + pos] = (call_sig, call_end + pos)
                        method_glob_calls.append(call_sig)
                    
                    method_code += line
                    
                # We're getting out of a block

                if indent >= cls_indent + 2 and line.strip().startswith('}') and cond_start and (not cond_indent or indent <= cond_indent):
                    self.cond_bounds.append((cond_start, pos + len(line) - 1))
                    cond_start = None
                    cond_indent = None
                
                if indent < cls_indent + 2 and line.strip() == '}':
                    if last_indent >= cls_indent + 2:
                        self.method_bounds[method_sig] = (method_start, pos)
                        self.method_cache[method_sig] = (method_code, method_loc_calls, method_glob_calls)
                    
                    method_sig = None
            
            if indent <= cls_indent and indent < last_indent and line.strip(' \r\n;') == '}':
                cls_indent = max(0, indent - 1)
                
            pos += len(line)
            if line.strip('\n') and indent:
                last_indent = indent

    """
    Return the method signature for a given method call, parsed out of
    Jad annotations.
    """
    def prototype_from_annote(self, name, args):
        # Perform minimal disambiguation
        has_args = args[0] != ')'
        while search('\(.*?\)', args):
            args = sub('\((.*?)\)', lambda x: sub('[^()]', '', x.group(1)), args)
        num_commas = args.split(')')[0].count(',')
        
        annote = next((i for i, v in enumerate(self.annotes) if v[2] == name and \
                                                                (has_args == bool(v[3])) and \
                                                                (v[3].count(',') == num_commas)), None)
        if annote is None:
            print("Error: Jad annotation couldn't be parsed:", repr(name + '(' + args), '/', self.cls, '/', self.annotes)
            raise ValueError
        
        return self.annotes.pop(annote)
    
    """
    Return the code for a given method in the Java class, along with
    code for other methods it calls that haven't been merged yet.
    """
    
    def get_method_unfold(self, ret_method, merged=None, unfold=True):
        ret_code = ''
        ret, name, args = ret_method
        
        if merged is None:
            merged = set()
        elif (ret, self.cls, name, args) in merged:
            return ''
        merged.add((ret, self.cls, name, args))
        
        if self.extends and self.extends != self.cls and ret_method not in self.method_cache:
            return self.jar.decomp_func((ret, self.extends, name, args), merged)
        
        if ret_method not in self.method_cache:
            return ''
        method_code, method_loc_calls, method_glob_calls = self.method_cache[ret_method]
        
        if unfold:
            for func in method_glob_calls:
                if func not in merged:
                    ret_code += self.jar.decomp_func(func, merged)
            
            for func in method_loc_calls:
                ret2, name2, args2 = func
                if (ret2, self.cls, name2, args2) not in merged:
                    ret_code += self.get_method_unfold(func, merged)
        
        return ret_code + method_code
    
    """
    Used for switch structures extraction.
    
    Switch structures as they are rendered by Jad may be a bit complex to parse, but that's a minor drawback.
    """
    
    def parse_switch(self, start, next_lines):
        label_to_val = {}
        
        if 'INSTR lookupswitch' in next_lines: # Handling first switch construct
            in_switch = True
            vals = []
            for line in self.raw[start:].split('INSTR lookupswitch')[1].splitlines()[1:]:
                line = line.strip('/ ')
                if not line.startswith('goto '):
                    vals.append(int(line.split(': ')[0]))
                else:
                    for tag, label in zip(vals, line.split(' ')[2:]):
                        if tag != 0:
                            label_start = self.raw.index('\n%s:' % label, start) + len('\n%s:' % label)
                            func_end = self.raw.index('\n    }', label_start)
                            label_to_val[label_start] = (tag, func_end)
                    break
            label_to_val = sorted(label_to_val.items())
            
            # Make sure labels don't overlap
            for i in range(len(label_to_val) - 1):
                label_start, (tag, label_end) = label_to_val[i]
                next_label_start, (next_tag, next_label_end) = label_to_val[i + 1]
                assert label_start < next_label_start
                label_to_val[i] = label_start, (tag, next_label_start)
        
        elif ' switch(' in next_lines: # Handling second switch construct
            in_switch = True
            switch_indent = next_lines.split('switch(')[0].split('\n')[-1]
            switch_code = self.raw[:start] + split('break;\n%s\}' % switch_indent, self.raw[start:], flags=MULTILINE)[0]
            while True:
                start = switch_code.find('case ', start + 1)
                if start == -1:
                    break
                tag = int(switch_code[start + 4:].split(':')[0])
                case_end = switch_code.find('case ', start + 1)
                if case_end == -1:
                    case_end = len(switch_code)
                label_to_val[start] = (tag, case_end)
            label_to_val = sorted(label_to_val.items())
        
        return label_to_val
