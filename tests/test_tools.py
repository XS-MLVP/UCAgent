#code: utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

import time

from vagent.tools import *

def print_tool_info(tool):
    print("Tool Name    :", tool.name)
    print("Description  :", tool.description)
    print("Args Schema  :", tool.args_schema)
    print("Return Direct:", tool.return_direct)
    print("Args         :", tool.args)

def test_list_path():
    print("============== test_list_path ==============")
    tool = PathList(workspace=os.path.join(current_dir, "../vagent"))
    result = tool.invoke({"path": ".", "depth":-1})
    print_tool_info(tool)
    print("result:\n%s"%result)

def test_read_file():
    print("============== test_read_file ==============")
    tool = ReadBinFile(workspace=os.path.join(current_dir, "../vagent"))
    print_tool_info(tool)
    result = tool.invoke({"path": "config/default.yaml", "start": 0, "end": 100})
    print("result:\n%s"%result)

def test_read_text_file():
    print("============== test_read_text_file ==============")
    tool = ReadTextFile(workspace=os.path.join(current_dir, "../vagent"))
    print_tool_info(tool)
    result = tool.invoke({"path": "config/default.yaml", "start": 2, "end": 100})
    print("result:\n%s"%result)

def test_edit_multil_line():
    print("============== test_edit_multiline ==============")
    tool = TextFileMultiReplace(workspace=os.path.join(current_dir, "../examples"))
    print_tool_info(tool)
    result = tool.invoke({"path": "Adder/Adder.v", "values": [
        (-1, 0, f"// This is a test comment: {time.time()}", False),
         (9, 0, f"// This is a test comment:\n// {time.time()}", True),
        ]})
    print("result:\n%s"%result)

def test_ref_mem():
    from vagent.util.config import get_config
    cfg = get_config(os.path.join(current_dir, "../config.yaml"))
    tool = SearchInGuidDoc(cfg.embed, workspace=os.path.join(current_dir, "../doc"), doc_path="Guide_Doc")
    print(tool.invoke({"query": "import", "limit": 3}))

if __name__ == "__main__":
    test_read_text_file()
    test_list_path()
    test_read_file()
    #test_edit_multil_line()
    test_ref_mem()
