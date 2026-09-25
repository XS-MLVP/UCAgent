"""Utils for the Bug Review workflow."""
import ast
import hashlib
import logging
import os
import re
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable, List, Optional, Sequence, Set


def init_logging(level: int = logging.WARNING, log_path: Optional[str] = None) -> None:
    """Configure console logging and optionally persist one benchmark run log."""
    log_format = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
    logging.basicConfig(format=log_format, level=level)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if not log_path:
        return
    absolute_path = os.path.abspath(log_path)
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) and os.path.abspath(handler.baseFilename) == absolute_path:
            return
    file_handler = logging.FileHandler(absolute_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


STOPWORDS = {
    "bug",
    "failure",
    "failed",
    "test",
    "tests",
    "signal",
    "timeout",
    "rtl",
    "root",
    "cause",
    "current",
    "should",
    "must",
    "design",
    "function",
    "assert",
    "done",
}


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return slug or "item"


def dataclass_to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: dataclass_to_dict(item) for key, item in value.items()}
    if isinstance(value, list):
        return [dataclass_to_dict(item) for item in value]
    return value


def extract_local_name(text: str, prefix: str) -> Optional[str]:
    pattern = re.compile(rf"(?:<)?({prefix}-[A-Za-z0-9_:\-]+)(?:>)?")
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1)


def extract_local_names(text: str) -> List[str]:
    return [match.group(1) for match in re.finditer(r"<((?:BG|FG|FC|CK|TC)-[^>]+)>", text)]


def normalize_nodeid(text: str) -> str:
    candidate = text.strip().strip("<>` ")
    if candidate.startswith("TC-"):
        candidate = candidate[3:]
    candidate = candidate.replace("\\", "/")
    match = re.search(
        r"(tests/[^:\s]+(?:\:\d+(?:-\d+)?)?(?:::[^<>\s]+)+)",
        candidate,
    )
    if match:
        candidate = match.group(1)
    candidate = re.sub(r"(tests/[^:]+):\d+(?:-\d+)?::", r"\1::", candidate)
    if candidate.endswith(".py") or "::" not in candidate:
        return candidate
    if candidate.startswith("tests/"):
        return candidate
    if re.match(r"[^/\s]+\.py::", candidate):
        return f"tests/{candidate}"
    return candidate


def base_test_name(nodeid: str) -> str:
    suffix = nodeid.split("::")[-1]
    return suffix.split("[", 1)[0]


def extract_test_report_fields(report_text: str) -> dict:
    match = re.search(
        r"<TestReport '([^']+)' when='([^']+)' outcome='([^']+)'>",
        report_text,
    )
    if not match:
        return {"nodeid": "", "when": "", "outcome": ""}
    return {
        "nodeid": normalize_nodeid(match.group(1)),
        "when": match.group(2),
        "outcome": match.group(3),
    }


def extract_exception_fields(call_text: str) -> dict:
    match = re.search(
        r"ExceptionInfo\s+([A-Za-z_][A-Za-z0-9_]*)\((.*)\)\s+tblen=",
        call_text,
    )
    if not match:
        return {"type": None, "message": None}
    exc_type = match.group(1)
    raw_message = match.group(2)
    try:
        message = ast.literal_eval(raw_message)
    except Exception:
        message = raw_message.strip("'\"")
    return {"type": exc_type, "message": str(message)}


def clean_markdown_text(text: str) -> str:
    text = re.sub(r"<(?:BG|FG|FC|CK|TC)-[^>]+>", "", text)
    text = re.sub(r"`", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -:\n\t")


def literal_value(node: Any) -> Optional[Any]:
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def normalised_tokens(text: str) -> Set[str]:
    lowered = clean_markdown_text(text).lower()
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]+|[\u4e00-\u9fff]{2,}", lowered)
    results = set()
    for token in tokens:
        if token in STOPWORDS:
            continue
        if token.startswith(("fg_", "fc_", "ck_", "bg_")):
            continue
        results.add(token)
    return results


def jaccard_score(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def exception_archetype(message: Optional[str]) -> Optional[str]:
    if not message:
        return None
    lowered = message.lower()
    if "timeout" in lowered or "超时" in message:
        return "timeout"
    if "assert" in lowered or "断言" in message:
        return "assertion"
    if "reset" in lowered or "复位" in message:
        return "reset"
    return "other"


def dedupe_preserve_order(values: Sequence[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def infer_signal_names(text: str, known_signals: Sequence[str]) -> List[str]:
    matches = []
    for signal in known_signals:
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(signal)}(?![A-Za-z0-9_])", text):
            matches.append(signal)
    if matches:
        return dedupe_preserve_order(matches)
    fallback = re.findall(
        r"(?:`|\b)(done|rst|ld|text_out|text_in|key|dcnt|busy|state)(?:`|\b)",
        text,
        re.IGNORECASE,
    )
    return dedupe_preserve_order([item.lower() for item in fallback])


def common_prefix_path(paths: Sequence[str]) -> str:
    if not paths:
        return ""
    return os.path.commonpath(paths)


def shorten_text(text: str, limit: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."
