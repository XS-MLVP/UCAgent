import io
import logging

import ucagent.util.log as log_util


def test_file_loggers_do_not_duplicate_records_through_root(tmp_path, monkeypatch):
    root = logging.getLogger()
    previous_log_logger = log_util.get_log_logger()
    previous_msg_logger = log_util.get_msg_logger()
    root_output = io.StringIO()
    capture = logging.StreamHandler(root_output)
    capture.setFormatter(logging.Formatter("%(filename)s:%(lineno)d\n%(message)s"))
    root.addHandler(capture)
    monkeypatch.setattr(log_util, "__silent__", False)

    try:
        log_path = tmp_path / "ucagent.log"
        msg_path = tmp_path / "messages.log"
        log_util.init_log_logger(name="ucagent-test-log", log_file=str(log_path))
        log_util.init_msg_logger(name="ucagent-test-msg", log_file=str(msg_path))

        log_util.log_msg("runtime event")
        log_util.msg_msg("agent message")

        assert root_output.getvalue() == ""
        assert "runtime event" in log_path.read_text(encoding="utf-8")
        assert "agent message" in msg_path.read_text(encoding="utf-8")
    finally:
        root.removeHandler(capture)
        for logger in (log_util.get_log_logger(), log_util.get_msg_logger()):
            if logger is None:
                continue
            for handler in logger.handlers:
                handler.close()
            logger.handlers.clear()
        log_util.__log_logger__ = previous_log_logger
        log_util.__msg_logger__ = previous_msg_logger
