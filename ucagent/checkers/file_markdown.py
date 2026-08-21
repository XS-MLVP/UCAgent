#coding=utf-8
"""Markdown file checkers for UCAgent."""


from ucagent.checkers.base import Checker, UnityChipBatchTask
import ucagent.util.functions as fc
from ucagent.util.log import info
from collections import OrderedDict
import os


def check_file_path_xml_tags(workspace, target_files) -> list:
    """Check for XML tags in the specified files and return a list of file paths found within those tags."""
    ret_files = {}
    check_passed = True
    for pfile in target_files:
        if pfile not in ret_files:
            ret_files[pfile] = []
        try:
            file_list = fc.get_xml_tag_list(workspace, pfile, "ref_file")
        except Exception as e:
            info(f"Error parsing XML in file '{pfile}': {e}")
            ret_files[pfile].append(f"Error parsing XML: {e}")
            check_passed = False
            continue
        for f in file_list:
            fpath, _ = f, None
            try:
                if ':' in f:
                    fpath, line_part = f.split(':', 1)
                    start_line, end_line = line_part.split('-', 1)
                    lines = (int(start_line), int(end_line))
                    assert lines[0] > 0 and lines[1] >= lines[0], "Line numbers must be positive and in correct order."
            except Exception as e:
                info(f"Error parsing line numbers in tag '{f}' in file '{pfile}': {e}")
                ret_files[pfile].append(f"Parse '{f}' with lines  failed: {e}, please check format '<ref_file>relative_path[:line-line]</ref_file>'")
                check_passed = False
                continue
            abs_path = os.path.abspath(workspace + os.path.sep + fpath)
            if not os.path.isfile(abs_path):
                info(f"Referenced file '{abs_path}' does not exist.")
                ret_files[pfile].append(f"Referenced file '{fpath}' does not exist.")
                check_passed = False
    return check_passed, ret_files


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
        file_ref_pass, file_ref_msg = check_file_path_xml_tags(
            self.workspace, [file_path]
        )
        if not file_ref_pass:
            return False, {
                "error": f"File '{file_path}' has invalid file references",
                "details": file_ref_msg
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
        file_ref_pass, file_ref_msg = check_file_path_xml_tags(
            self.workspace, [self.file_path]
        )
        if not file_ref_pass:
            return False, {
                "error": f"File '{self.file_path}' has invalid file references",
                "details": file_ref_msg
            }
        return True, {
            "note": f"File '{self.file_path}' contains all required headers from template '{self.template_file}'."
        }


class MustHaveCKs(Checker):
    """Ensure every CK in source files exists in the functions-and-checks doc.

    Role:
        Use ``funcs_and_checks_doc`` as the allowed CK set, then verify every
        matched file in ``source_files`` only contains ``leaf_node`` labels that
        also exist in that document. Missing labels are reported with their
        source file line numbers.

    Args:
        source_files: A file path, glob/regex pattern, or list of patterns.
        funcs_and_checks_doc: Markdown doc that defines the required labels.
        leaf_node: Label level to compare, usually ``"CK"``; also supports
            levels accepted by ``get_unity_chip_doc_marks``.

    Example:
        checker:
          - name: must_have_cks
            clss: "MustHaveCKs"
            args:
              source_files: "{DUT}/*.md"
              funcs_and_checks_doc: "{OUT}/{DUT}_functions_and_checks.md"
              leaf_node: "CK"
    """

    def __init__(self,
                 source_files:str,
                 funcs_and_checks_doc:str,
                 leaf_node:str="CK",
                 **kw):
        self.source_files = source_files if isinstance(source_files, list) else [source_files]
        self.funcs_and_checks_doc = funcs_and_checks_doc
        self.leaf_node = leaf_node

    def _load_labels(self, doc_file, return_line_block=False, file_kind="documentation file"):
        try:
            return fc.get_unity_chip_doc_marks(
                self.get_path(doc_file),
                self.leaf_node,
                0,
                return_line_block=return_line_block,
            )
        except Exception as e:
            raise ValueError(f"Error parsing {file_kind} '{doc_file}': {e}") from e

    def _get_label_line_map(self, label_blocks):
        label_line_map = {}
        for label, lines in label_blocks.items():
            leaf_tag = f"<{label.split('/')[-1]}>"
            for line in lines:
                if ": " not in line:
                    continue
                line_no, content = line.split(": ", 1)
                if content == "...":
                    continue
                if leaf_tag in "".join(content.split()):
                    label_line_map[label] = int(line_no)
                    break
        return label_line_map

    def _label_with_line(self, label, label_line_map, file_path=None):
        line_no = label_line_map.get(label)
        if line_no is None:
            return label
        label_file = file_path or self.funcs_and_checks_doc
        return f"{label} ({label_file}:{line_no})"

    def do_check(self, is_complete=False, **kw) -> tuple[bool, object]:
        """Check markdown source files only contain labels from the functions-and-checks doc."""
        fc_ck_file = self.get_path(self.funcs_and_checks_doc)
        if not os.path.isfile(fc_ck_file):
            return False, {
                "error": f"Funcs and checks doc file '{self.funcs_and_checks_doc}' does not exist in workspace. Please check your configuration."
            }
        try:
            allowed_label_list = self._load_labels(self.funcs_and_checks_doc)
        except ValueError as e:
            return False, {
                "error": str(e)
            }
        allowed_label_set = set(allowed_label_list)

        source_label_map = {}
        source_file_list = sorted(fc.find_files_by_pattern(self.workspace, self.source_files))
        if len(source_file_list) == 0:
            return False, {
                "error": f"No source files found for patterns: {', '.join(self.source_files)}."
            }

        for dfile in source_file_list:
            if not os.path.exists(self.get_path(dfile)):
                return False, {"error": f"Source file '{dfile}' does not exist."}
            try:
                data_sub, data_blocks = self._load_labels(
                    dfile, return_line_block=True, file_kind="source file"
                )
            except ValueError as e:
                return False, {
                    "error": str(e)
                }
            source_label_map[dfile] = {
                "labels": data_sub,
                "line_map": self._get_label_line_map(data_blocks),
            }

        missing_label_map = {}
        for dfile, label_data in source_label_map.items():
            label_list = label_data["labels"]
            missing_label_list = [
                label for label in label_list
                if label not in allowed_label_set
            ]
            if len(missing_label_list) > 0:
                missing_label_map[dfile] = [
                    self._label_with_line(label, label_data["line_map"], dfile)
                    for label in missing_label_list
                ]
        if len(missing_label_map) > 0:
            missing_source_file_count = len(missing_label_map)
            missing_label_count = sum(len(label_list) for label_list in missing_label_map.values())
            error_details = "\n".join([
                f"File '{dfile}' contains {len(label_list)} {self.leaf_node} labels not defined in "
                f"'{self.funcs_and_checks_doc}': {', '.join(label_list[:20])}"
                f"{'' if len(label_list) <= 20 else '...(%s more)' % (len(label_list) - 20)}"
                for dfile, label_list in missing_label_map.items()
            ])
            return False, OrderedDict({
                "error": f"Some {missing_source_file_count} source file(s) contain {missing_label_count} {self.leaf_node} " + \
                         f"labels not defined in '{self.funcs_and_checks_doc}' (contained {len(allowed_label_list)} {self.leaf_node} labels).",
                "details": error_details,
                "suggestion": f"Please ensure all {self.leaf_node} labels in the source files are defined in '{self.funcs_and_checks_doc}'."
            })
        return True, {
            "note": f"All source files contain only {self.leaf_node} labels defined in '{self.funcs_and_checks_doc}'."
        }
