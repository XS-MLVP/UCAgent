#code: utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))


from vagent.tools.fileops import *

def print_tool_info(tool):
    print("Tool Name    :", tool.name)
    print("Description  :", tool.description)
    print("Args Schema  :", tool.args_schema)
    print("Return Direct:", tool.return_direct)
    print("Args         :", tool.args)

def test_list_path():
    tool = ListPath(workspace=os.path.join(current_dir, "../vagent"))
    result = tool.invoke({"path": ".", "depth":-1})
    print_tool_info(tool)
    print("result:\n%s"%result)


def test_read_file():
    tool = ReadFile(workspace=os.path.join(current_dir, "../vagent"))
    result = tool.invoke({"path": "config/default.yaml", "start": 0, "end": 100})
    print("result:\n%s"%result)

def test_read_text_file():
    tool = ReadTextFile(workspace=os.path.join(current_dir, "../vagent"))
    result = tool.invoke({"path": "config/default.yaml", "start": 0, "end": 100})
    print("result:\n%s"%result)

if __name__ == "__main__":
    test_read_text_file()
