#coding=utf-8
"""Markdown file checkers for UCAgent."""


from ucagent.checkers.base import Checker, UnityChipBatchTask
import ucagent.util.functions as fc
from ucagent.util.log import info
import copy
import os


class BatchFileProcess(Checker):
    """process files in batch"""

    def __init__(self, name, file_pattern, batch_size=1, mini_inputs=1, need_human_check=False):
        self.file_pattern = file_pattern if isinstance(file_pattern, list) else [file_pattern]
        self.batch_size = batch_size
        self.mini_inputs = mini_inputs
        self.batch_task = UnityChipBatchTask(name, self)
        self.set_human_check_needed(need_human_check)

    def get_pfile_list(self) -> list:
        markdown_files = []
        for p in self.file_pattern:
            markdown_files.extend(fc.find_files_by_pattern(self.workspace, p))
        return markdown_files

    def init_batch_task(self):
        markdown_files = self.get_pfile_list()
        if len(markdown_files) == 0:
            info("No files found with patterns: {}".format('\n'.join(self.file_pattern)))
            return False
        if len(self.batch_task.source_task_list) > 0 or len(self.batch_task.cmp_task_list) > 0:
            return True
        self.batch_task.source_task_list = markdown_files
        self.batch_task.update_current_tbd()
        init_files = '\n'.join(self.batch_task.source_task_list)
        info(f"Load file list(size={len(self.batch_task.source_task_list)}): {init_files}")
        return True

    def on_init(self):
        """Initialization tasks."""
        self.init_batch_task()
        return super().on_init()

    def get_template_data(self):
        ret = self.batch_task.get_template_data(
            "TOTAL_FILES", "COMPLETED_FILES", "CURRENT_FILES"
        )
        ret["COMPLETE_PROGRESS"] = f"{ret['COMPLETED_FILES']}/{ret['TOTAL_FILES']}"
        ret["CURRENT_FILE_NAME"] = ",".join(self.batch_task.tbd_task_list)
        return ret

    def do_check(self, is_complete=False, **kw) -> tuple[bool, object]:
        """Check markdown files for headers of specified levels in batch."""
        if self.init_batch_task() is False:
            if self.mini_inputs > 0:
                return True, {
                    "error": "No target files find, please check your file patterns."
                }
            return True, "Not target files found, skip check, default pass."
        if len(self.batch_task.source_task_list) < self.mini_inputs:
            self.batch_task.source_task_list = []
            return False, {
                "error": f"Not enough target files found({len(self.batch_task.source_task_list)}) for check, need at least {self.mini_inputs} files."
            }
        # Get task file list
        if len(self.batch_task.source_task_list) == 0 and \
           len(self.batch_task.gen_task_list) == 0:
            return False, {
                "error": "No target files find, please check your file patterns."
            }
        for task_file in self.batch_task.tbd_task_list:
            ret, msg = self.do_one_file_check(task_file)
            if not ret:
                return False, {
                    "error": msg
                }
        note_msg = []
        # Complete
        self.batch_task.sync_gen_task(
            self.batch_task.gen_task_list + self.batch_task.tbd_task_list,
            note_msg,
            "Completed file changed."
        )
        return self.batch_task.do_complete(note_msg, is_complete, "", "", "")


    def do_one_file_check(self, file_path):
        raise NotImplemented("Need imp do_one_file_check")


class WalkFilesOneByOne(BatchFileProcess):
    """Walk files one by one"""

    def __init__(self, name, file_pattern, need_human_check=False, **kw):
        super().__init__(name, file_pattern, batch_size=1, need_human_check=need_human_check)
        self.readed_files = []

    def on_init(self):
        self.stage_manager.tool_read_text.append_callback(self.on_file_read)
        return super().on_init()

    def on_file_read(self, success, pfile, message):
        if success:
            if pfile.startswith(os.sep):
                pfile = pfile[1:]
            info("File read callback: {}, append to readed_files".format(pfile))
            self.readed_files.append(pfile)

    def do_one_file_check(self, file_path):
        for f in self.readed_files:
            if f in file_path:
                return True, ""
        return False, f"File '{file_path}' was not read during the process. you Need use tool '{self.stage_manager.tool_read_text.name}' to read it."

    def do_check(self, is_complete=False, **kw) -> tuple[bool, object]:
        """Check markdown files one by one."""
        ret, msg = super().do_check(is_complete, **kw)
        if is_complete and ret:
            self.stage_manager.tool_read_text.remove_callback(self.on_file_read)
        return ret, msg


class BatchMarkDownHeadChecker(BatchFileProcess):
    """Checker for markdown file headers."""

    def __init__(self, name:str, file_pattern:list, template_file:str, header_levels,  mini_inputs=1, need_human_check=False, **kw):
        self.template_file = template_file
        self.header_levels = tuple(header_levels) if isinstance(header_levels, list) else header_levels
        super().__init__(name, file_pattern, batch_size=1, mini_inputs=mini_inputs, need_human_check=need_human_check)

    def do_one_file_check(self, file_path):
        source_file = self.template_file
        missed_headers, note_msg = fc.markdown_get_miss_headers(
            self.workspace, file_path, self.template_file, self.header_levels
        )
        if len(missed_headers) > 0:
            return False, {
                "error" f"File '{file_path}' is missing {len(missed_headers)} headers from template '{source_file}'. " + note_msg
            }
        return True, ""


class MarkDownHeadChecker(Checker):
    """Checker for single markdown file headers."""

    def __init__(self, file_path:str, template_file:str, header_levels, need_human_check=False, **kw):
        self.file_path = file_path
        self.template_file = template_file
        self.header_levels = tuple(header_levels) if isinstance(header_levels, list) else header_levels
        self.set_human_check_needed(need_human_check)

    def do_check(self, is_complete=False, **kw) -> tuple[bool, object]:
        """Check markdown file for headers of specified levels."""
        if not os.path.isfile(self.get_path(self.file_path)):
            return False, {
                "error": f"File '{self.file_path}' does not exist in workspace. Please create it first."
            }
        if not os.path.isfile(self.get_path(self.template_file)):
            return False, {
                "error": f"Template file '{self.template_file}' does not exist in workspace. Please check your configuration."
            }
        missed_headers, note_msg = fc.markdown_get_miss_headers(
            self.workspace, self.file_path, self.template_file, self.header_levels
        )
        if len(missed_headers) > 0:
            return False, {
                "error": f"File '{self.file_path}' is missing {len(missed_headers)} headers from template '{self.template_file}'. " + note_msg
            }
        return True, {
            "note": f"File '{self.file_path}' contains all required headers from template '{self.template_file}'."
        }
