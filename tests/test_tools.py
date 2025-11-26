w#code: utf-8

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

import time

from ucagent.tools import *

def print_tool_info(tool):
    print("Tool Name    :", tool.name)
    print("Description  :", tool.description)
    print("Args Schema  :", tool.args_schema)
    print("Return Direct:", tool.return_direct)
    print("Args         :", tool.args)

def test_list_path():
    print("============== test_list_path ==============")
    tool = PathList(workspace=os.path.join(current_dir, "../ucagent"))
    result = tool.invoke({"path": ".", "depth":-1})
    print_tool_info(tool)
    print("result:\n%s"%result)

def test_read_file():
    print("============== test_read_file ==============")
    tool = ReadBinFile(workspace=os.path.join(current_dir, "../ucagent"))
    print_tool_info(tool)
    result = tool.invoke({"path": "config/default.yaml", "start": 0, "end": 100})
    print("result:\n%s"%result)

def test_read_text_file():
    print("============== test_read_text_file ==============")
    tool = ReadTextFile(workspace=os.path.join(current_dir, "../ucagent"))
    print_tool_info(tool)
    result = tool.invoke({"path": "config/default.yaml", "start": 2, "end": 100})
    print("result:\n%s"%result)

def test_edit_multil_line():
    print("============== test_edit_multiline ==============")
    workspace = os.path.join(current_dir, "../output")
    if not os.path.exists(workspace):
        os.makedirs(workspace)
        import shutil as sh
        sh.copy(os.path.join(current_dir, "../config.yaml"), os.path.join(workspace, "test_config.yaml"))
    tool = MultiReplaceLinesByIndex(workspace)
    print_tool_info(tool)
    result = tool.invoke({"path": "test_config.yaml", "values": [
        (-1, 0, f"// This is a test comment: {time.time()}", False),
         (9, 0, f"// This is a test comment:\n// {time.time()}", True),
        ]})
    print("result:\n%s"%result)

def test_ref_mem():
    from ucagent.util.config import get_config
    cfg = get_config(os.path.join(current_dir, "../config.yaml"))
    tool = SemanticSearchInGuidDoc(cfg.embed, workspace=os.path.join(current_dir, "../doc"), doc_path="Guide_Doc")
    print(tool.invoke({"query": "import", "limit": 3}))


def test_replace_string_in_file():
    workspace = os.path.join(current_dir, "../output")
    if not os.path.exists(workspace):
        os.makedirs(workspace)
    import shutil as sh
    sh.copy(os.path.join(current_dir, "../config.yaml"), os.path.join(workspace, "test_config.yaml"))
    replace_string_tool = ReplaceStringInFile(workspace, un_write_dirs=["/tmp"])
    print(replace_string_tool.invoke({
        "path": "test_config.yaml",
        "old_string": "Qwen/Qwen3-Embedding-8B",
        "new_string": f"openai_{time.time()}",
    }))


if __name__ == "__main__":
    #test_read_text_file()
    #test_list_path()
    #test_read_file()
    #test_edit_multil_line()
    #test_ref_mem()
    test_replace_string_in_file()
