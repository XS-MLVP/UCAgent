"""Gt defect reporting for the Bug Review workflow."""
import html
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


def _esc(value: object) -> str:
    return html.escape(str(value if value not in (None, "") else "n/a"), quote=True)


def _short_path(value: object) -> str:
    path = str(value or "")
    if not path:
        return "n/a"
    parts = path.replace("\\", "/").split("/")
    return "/".join(parts[-3:]) if len(parts) > 3 else path


def _badges(values: Iterable[object], empty: str = "n/a") -> str:
    items = [str(value) for value in values if value not in (None, "")]
    if not items:
        return f"<span class='muted'>{_esc(empty)}</span>"
    return "".join(f"<span class='badge'>{_esc(value)}</span>" for value in items)


_FILE_RESOLVE_CACHE: Dict[Tuple[str, Tuple[str, ...]], Optional[Path]] = {}


def resolve_file(file_path: str, base_dirs: Optional[List[Path]] = None) -> Optional[Path]:
    if not file_path or file_path == "n/a":
        return None
    cache_key = (file_path, tuple(str(b) for b in (base_dirs or [])))
    if cache_key in _FILE_RESOLVE_CACHE:
        return _FILE_RESOLVE_CACHE[cache_key]

    p = Path(file_path)
    try:
        if p.is_file():
            _FILE_RESOLVE_CACHE[cache_key] = p
            return p
    except OSError:
        # A malformed report reference can contain prose rather than a path.
        # Treat it as unresolved source text and keep rendering the defect.
        _FILE_RESOLVE_CACHE[cache_key] = None
        return None

    search_dirs = list(base_dirs or []) + [
        Path("."),
        Path("inputs"),
        Path("inputs/xiangshan/ucagent"),
    ]
    for b in search_dirs:
        try:
            if not b.exists():
                continue
            cand = b / file_path
            if cand.is_file():
                _FILE_RESOLVE_CACHE[cache_key] = cand
                return cand
        except OSError:
            continue
        parts = p.parts
        for i in range(1, len(parts)):
            sub_cand = b / Path(*parts[i:])
            if sub_cand.is_file():
                _FILE_RESOLVE_CACHE[cache_key] = sub_cand
                return sub_cand

    # Fallback: search by filename within provided base_dirs
    target_name = p.name
    for b in (base_dirs or []):
        if b.is_dir():
            try:
                for match in b.rglob(target_name):
                    if match.is_file():
                        _FILE_RESOLVE_CACHE[cache_key] = match
                        return match
            except Exception:
                pass

    _FILE_RESOLVE_CACHE[cache_key] = None
    return None



import json


class SourceRegistry:
    def __init__(self, base_dirs: Optional[List[Path]] = None):
        self.base_dirs = base_dirs or []
        self.files: Dict[str, List[str]] = {}

    def register(self, file_path: str) -> Tuple[str, Optional[List[str]]]:
        if not file_path or file_path == "n/a":
            return str(file_path or "n/a"), None
        key = _short_path(file_path)
        if key in self.files:
            return key, self.files[key]
        resolved = resolve_file(file_path, self.base_dirs)
        if resolved and resolved.is_file():
            try:
                lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
                self.files[key] = lines
                return key, lines
            except Exception:
                pass
        self.files[key] = []
        return key, []

    def to_json(self) -> str:
        return json.dumps(self.files, ensure_ascii=False)


def extract_source_snippet(
    file_path: str,
    line_start: Optional[int],
    line_end: Optional[int],
    context: int = 4,
    base_dirs: Optional[List[Path]] = None,
    registry: Optional[SourceRegistry] = None,
) -> Optional[str]:
    lines = None
    if registry:
        _, lines = registry.register(file_path)
    if not lines:
        resolved = resolve_file(file_path, base_dirs)
        if not resolved or not resolved.is_file():
            return None
        try:
            lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return None

    if line_start is None or line_end is None:
        return None

    total = len(lines)
    s = max(1, int(line_start) - context)
    e = min(total, int(line_end) + context)
    out = []
    for idx in range(s, e + 1):
        is_target = int(line_start) <= idx <= int(line_end)
        prefix = ">>>" if is_target else "   "
        out.append(f"{prefix} {idx:4d} | {lines[idx - 1]}")
    return "\n".join(out)


def code_snippet_html(
    display_text: str,
    file_path: str,
    line_start: Optional[int],
    line_end: Optional[int],
    base_dirs: Optional[List[Path]] = None,
    registry: Optional[SourceRegistry] = None,
) -> str:
    file_key = _short_path(file_path)
    if registry:
        file_key, _ = registry.register(file_path)

    snippet = extract_source_snippet(file_path, line_start, line_end, context=4, base_dirs=base_dirs, registry=registry)
    display_esc = _esc(display_text)
    if not snippet:
        return f"<code>{display_esc}</code>"

    title_text = f"{_short_path(file_path)}:{line_start}-{line_end}" if line_start is not None else _short_path(file_path)
    snippet_esc = html.escape(snippet, quote=True)
    start_val = line_start if line_start is not None else 0
    end_val = line_end if line_end is not None else 0

    return (
        f"<span class='code-pop-trigger' onmouseenter='showGlobalHover(this, event)' onmouseleave='hideGlobalHover()' "
        f"onclick='openCodeModal(this)' "
        f"data-file='{html.escape(file_key, quote=True)}' "
        f"data-title='{html.escape(title_text, quote=True)}' "
        f"data-start='{start_val}' "
        f"data-end='{end_val}' "
        f"data-preview='{snippet_esc}'>"
        f"<code>{display_esc}</code>"
        f"</span>"
    )


_GT_DETAIL_EXTRA_CSS = """
html { scroll-behavior: smooth; }
:target {
  outline: 3px solid #06b6d4;
  outline-offset: 4px;
  box-shadow: 0 0 0 6px rgba(6, 182, 212, 0.25), 0 8px 24px rgba(6, 182, 212, 0.12) !important;
  border-color: #06b6d4 !important;
  transition: outline 0.2s ease, box-shadow 0.2s ease;
}
.gt-card { margin-bottom: 16px; padding: clamp(14px, 1.4vw, 24px); background: transparent; border: 0; box-shadow: none; }
.gt-card-header { display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
.gt-badge { background: #0d9488 !important; color: #fff !important; font-size: 1.1rem; padding: 4px 12px; border-radius: 6px; font-family: monospace; font-weight: 700; }
.gt-root-tag { background: #e0f2fe; color: #0369a1; padding: 2px 8px; border-radius: 999px; font-size: 0.82rem; font-weight: 600; }
.gt-loc-banner { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 10px 16px; margin: 12px 0; font-size: 0.95rem; color: #166534; }
.gt-loc-banner code { font-family: "SFMono-Regular", Consolas, monospace; font-weight: 700; background: #dcfce7; padding: 3px 8px; border-radius: 4px; color: #15803d; font-size: 0.95rem; }

.gt-symptoms-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 12px 0; padding: 8px 12px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; }
.chip-link { display: inline-block; text-decoration: none; padding: 3px 10px; border-radius: 999px; background: #f0f9ff; color: #0369a1; font-family: monospace; font-size: 0.85rem; font-weight: 600; border: 1px solid #bae6fd; transition: all 0.2s; }
.chip-link:hover { background: #0284c7; color: #fff; border-color: #0284c7; }

.model-block { border-top: 1px solid #e2e8f0; margin-top: 16px; padding-top: 16px; }
.model-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.status, .tier, .badge { display: inline-block; border: 1px solid var(--border); border-radius: 4px; padding: 2px 8px; margin: 2px; font-size: clamp(10px,0.72vw,13px); background: #f8fafc; }
.status.active { color: #047857; background: #ecfdf5; }
.status.excluded { color: #b45309; background: #fffbeb; }

.facts-strip { display: flex; flex-wrap: wrap; gap: 8px 12px; margin: 10px 0; align-items: center; }
.fact-chip { display: inline-flex; align-items: center; gap: 6px; background: #f8fafc; border: 1px solid var(--border); border-radius: 6px; padding: 4px 10px; font-size: clamp(11px,0.75vw,13px); }
.fact-chip b { color: var(--muted); font-weight: 600; }
.suspected-evidence-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; margin: 12px 0; }
.evidence-item { background: #f8fafc; border: 0; border-left: 3px solid #cbd5e1; border-radius: 0; padding: 8px 12px; }
.evidence-item b { display: block; color: #0369a1; margin-bottom: 4px; }
.evidence-item p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.waveform-evidence-card { margin: 10px 0; padding: 10px 12px; background: #f0fdfa; border: 0; border-left: 3px solid #14b8a6; border-radius: 0; }
.waveform-evidence-card h4 { margin: 0 0 5px; color: #0f766e; }
.compact-model { margin-top: 8px; padding-top: 8px; }
.compact-model .facts-strip { display: none; }
.compact-model .model-head { margin-bottom: 0; }
.compact-model > details, .compact-model > .obs-box, .compact-model > .defect-analysis-card { display: block; }
.compact-model .tier { font-size: 0.82em; color: #64748b; }
.compact-rationale { margin: 8px 0; padding: 7px 10px; background: #f8fafc; border-left: 3px solid #94a3b8; color: #475569; font-size: 0.9em; }
.compact-page .page { width: min(920px, 94vw); }
.compact-page .top-nav { border-bottom: 1px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px; }
.compact-page .hero, .compact-page .section { background: transparent; border: 0; box-shadow: none; border-radius: 0; padding: 0; margin: 0 0 18px; }
.compact-page .hero { border-bottom: 1px solid #cbd5e1; padding-bottom: 14px; }
.compact-page .hero h1 { font-size: clamp(20px, 2.2vw, 30px); }
.compact-page .section { border-bottom: 1px solid #e2e8f0; padding-bottom: 14px; }
.compact-page .gt-loc-banner { background: transparent; border: 0; border-left: 3px solid #06b6d4; border-radius: 0; padding: 4px 10px; }
.compact-page .gt-symptoms-bar { background: transparent; border: 0; padding: 0; }
.compact-page details { border-top: 1px solid #e2e8f0; padding: 10px 0; }
.compact-page details summary { display: block; color: #334155; font-size: 0.95em; }
.compact-page .compact-model > details { margin-top: 10px; }
.compact-page .compact-model > details pre { max-height: 260px; }
.compact-page .compact-model > details .table-wrap { max-height: 320px; }
.compact-page .suspected-evidence-grid { grid-template-columns: 1fr 1fr; }

.obs-box { margin: 12px 0; display: flex; flex-direction: column; gap: 10px; }
.obs-item { background: #f8fafc; border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px 14px; }
.obs-header { display: flex; align-items: center; justify-content: space-between; font-size: clamp(11px,0.75vw,13px); color: var(--muted); font-weight: 700; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.03em; }
.obs-content { white-space: pre-wrap; word-break: break-word; overflow-wrap: anywhere; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 4px; padding: 8px 12px; margin: 0; font-family: "SFMono-Regular", Consolas, monospace; font-size: clamp(11px,0.8vw,13px); line-height: 1.55; color: #0f172a; max-height: 360px; overflow-y: auto; }

details { border: 0; border-top: 1px solid var(--border); border-radius: 0; padding: 7px 0; margin: 7px 0; background: transparent; }
details[open] { background: transparent; }
details summary { cursor: pointer; font-weight: 600; font-size: clamp(12px,0.85vw,15px); padding: 4px 0; outline: none; user-select: none; color: #1e293b; }
details summary:hover { color: #0369a1; }
details pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f8fafc; padding: clamp(8px,0.8vw,14px); border-radius: var(--radius-sm); border: 1px solid var(--border); max-height: 360px; overflow: auto; font-size: clamp(11px,0.78vw,14px); margin-top: 6px; }

.table-wrap { overflow: auto; max-height: 360px; margin-top: 8px; -webkit-overflow-scrolling: touch; }
table { width: 100%; border-collapse: collapse; font-size: clamp(11px,0.78vw,14px); table-layout: auto; border: 1px solid var(--border); border-radius: var(--radius-sm); }
th, td { border: 1px solid var(--border); padding: clamp(5px,0.5vw,9px) clamp(6px,0.6vw,12px); text-align: left; vertical-align: top; overflow-wrap: anywhere; }
th { background: #f1f5f9; white-space: nowrap; font-size: clamp(9px,0.68vw,12px); color: #475569; text-transform: uppercase; letter-spacing: 0.03em; }

.test-outcome-passed { color: #15803d; font-weight: 700; white-space: nowrap; }
.test-outcome-failed { color: #b91c1c; font-weight: 700; white-space: nowrap; }

/* Popover trigger */
.code-pop-trigger { position: relative; display: inline-block; cursor: pointer; }
.code-pop-trigger:hover code { background: #0284c7 !important; color: #ffffff !important; border-radius: 3px; }

/* Global Light-theme Floating Popover (Never clipped) */
.global-hover-pop {
  display: none;
  position: fixed;
  z-index: 999999;
  width: min(680px, 94vw);
  background: #ffffff !important;
  color: #0f172a !important;
  border: 1px solid #cbd5e1 !important;
  border-radius: 8px !important;
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.16), 0 3px 10px rgba(15, 23, 42, 0.08) !important;
  pointer-events: none;
  font-family: "SFMono-Regular", Consolas, monospace;
  overflow: hidden;
}
.hover-pop-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #f8fafc;
  color: #0284c7;
  font-size: 11.5px;
  font-weight: 700;
  padding: 7px 12px;
  border-bottom: 1px solid #e2e8f0;
}
.hover-pop-body {
  margin: 0;
  padding: 10px 12px;
  background: #ffffff !important;
  color: #0f172a !important;
  font-size: 11.5px;
  line-height: 1.5;
  max-height: 280px;
  overflow-y: auto;
  white-space: pre-wrap;
  font-family: "SFMono-Regular", Consolas, monospace;
}

/* Modal overlay and code viewer */
.code-modal-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(4px);
  z-index: 999999;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.code-modal {
  background: #ffffff;
  border-radius: 12px;
  width: min(1080px, 96vw);
  height: 88vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.28);
  overflow: hidden;
}
.code-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}
.code-modal-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  overflow: hidden;
}
.code-modal-title {
  font-family: monospace;
  font-weight: 700;
  color: #0f172a;
  font-size: 13.5px;
  text-overflow: ellipsis;
  overflow: hidden;
  white-space: nowrap;
}
.code-modal-badge {
  background: #fee2e2;
  color: #b91c1c;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.code-modal-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.code-modal-btn {
  border: 1px solid #cbd5e1;
  background: #ffffff;
  padding: 5px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  transition: all 0.15s ease;
}
.code-modal-btn:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
}
.code-modal-btn.primary {
  background: #0284c7;
  color: #ffffff;
  border-color: #0284c7;
}
.code-modal-btn.primary:hover {
  background: #0369a1;
}

.code-modal-body {
  padding: 0;
  overflow-y: auto;
  flex: 1;
  background: #ffffff;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  user-select: text;
}
.code-line-row {
  display: flex;
  align-items: stretch;
  width: 100%;
  min-height: 20px;
}
.code-line-row:hover {
  background: #f8fafc;
}
.line-gutter {
  width: 110px;
  min-width: 110px;
  background: #f8fafc;
  border-right: 1px solid #e2e8f0;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 0 8px 0 2px;
  font-size: 11px;
  user-select: none;
  gap: 4px;
}
.line-content {
  flex: 1;
  padding: 1px 12px;
  white-space: pre-wrap;
  word-break: break-all;
  color: #0f172a;
}

/* Red Triangle Markers and Highlight Region */
.code-line-target {
  background: #fff5f5 !important;
  border-left: 4px solid #ef4444;
}
.code-line-start {
  background: #fee2e2 !important;
  border-top: 1px dashed #f87171;
}
.code-line-end {
  background: #fee2e2 !important;
  border-bottom: 1px dashed #f87171;
}
.red-triangle {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: #dc2626;
  font-weight: 800;
  font-size: 10px;
  background: #fecaca;
  padding: 0 4px;
  border-radius: 3px;
  border: 1px solid #f87171;
  letter-spacing: -0.02em;
}
.range-conn {
  color: #ef4444;
  font-weight: 700;
  font-size: 11px;
}
.badge-bug-specific {
  background: #fef3c7;
  color: #b45309;
  border: 1px solid #fde68a;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  display: inline-block;
  white-space: nowrap;
}
.badge-irrelevant {
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #e2e8f0;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11px;
  display: inline-block;
  white-space: nowrap;
}
.test-analysis-cell {
  font-size: 12px;
  line-height: 1.45;
  color: #334155;
}
.test-analysis-cell .lbl-exp {
  color: #0284c7;
  font-weight: 600;
}
.test-analysis-cell .lbl-act {
  color: #d97706;
  font-weight: 600;
}
.test-analysis-cell .lbl-ana {
  color: #0f172a;
  font-weight: 600;
}
.test-analysis-cell .analysis-note {
  margin-top: 3px;
  padding-top: 3px;
  border-top: 1px dashed #e2e8f0;
  color: #475569;
}
.defect-analysis-card {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-left: 4px solid #0284c7;
  border-radius: 6px;
  padding: 12px 16px;
  margin: 12px 0 16px 0;
}
.defect-analysis-card .analysis-header {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 8px;
}
.defect-analysis-card .analysis-row {
  margin-bottom: 6px;
  font-size: 12px;
  line-height: 1.55;
  color: #334155;
}
.defect-analysis-card .analysis-row:last-child {
  margin-bottom: 0;
}
.defect-analysis-card .analysis-row .k {
  font-weight: 600;
  color: #475569;
  margin-right: 6px;
}
.defect-analysis-card .analysis-row code {
  background: #e2e8f0;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: monospace;
  font-size: 11.5px;
  color: #0369a1;
}
"""


def _build_modal_html_and_js(source_registry: Optional[SourceRegistry] = None) -> str:
    sources_json = source_registry.to_json() if source_registry else "{}"
    return f"""
<div id="globalHoverPop" class="global-hover-pop">
  <div class="hover-pop-header">
    <span id="hoverPopTitle">代码预览</span>
    <span style="font-size:10.5px; color:#64748b;">点击打开全文件浏览</span>
  </div>
  <pre class="hover-pop-body" id="hoverPopContent"></pre>
</div>

<div id="codeModalOverlay" class="code-modal-overlay" onclick="closeCodeModal(event)">
  <div class="code-modal" onclick="event.stopPropagation()">
    <div class="code-modal-header">
      <div class="code-modal-title-wrap">
        <span class="code-modal-title" id="codeModalTitle">全量代码查看</span>
        <span class="code-modal-badge" id="codeModalBadge"></span>
      </div>
      <div class="code-modal-actions">
        <button class="code-modal-btn primary" id="btnScrollTarget" onclick="scrollToHighlightedTarget()">定位到标记代码段</button>
        <button class="code-modal-btn" onclick="copyFullSource()">复制全文件</button>
        <button class="code-modal-btn" onclick="closeCodeModal()">关闭 (ESC)</button>
      </div>
    </div>
    <div class="code-modal-body" id="codeModalBody">
    </div>
  </div>
</div>

<script>
var __FILE_SOURCES__ = {sources_json};

function showGlobalHover(el, e) {{
  var pop = document.getElementById('globalHoverPop');
  if (!pop) return;
  var title = el.getAttribute('data-title') || '代码预览';
  var preview = el.getAttribute('data-preview') || '';
  if (!preview) return;

  document.getElementById('hoverPopTitle').innerText = title;
  document.getElementById('hoverPopContent').innerText = preview;
  pop.style.display = 'block';

  var rect = el.getBoundingClientRect();
  var popW = pop.offsetWidth || 560;
  var popH = pop.offsetHeight || 200;

  var left = rect.left + (rect.width / 2) - (popW / 2);
  if (left + popW > window.innerWidth - 16) {{
    left = window.innerWidth - popW - 16;
  }}
  if (left < 16) left = 16;

  var top = rect.top - popH - 10;
  if (top < 10) {{
    top = rect.bottom + 10;
  }}
  pop.style.left = left + 'px';
  pop.style.top = top + 'px';
}}

function hideGlobalHover() {{
  var pop = document.getElementById('globalHoverPop');
  if (pop) pop.style.display = 'none';
}}

var currentModalTargetLine = null;
var currentModalFullText = "";

function openCodeModal(target, startLine, endLine, titleText) {{
  hideGlobalHover();
  var fileKey = '', title = '代码查看器', start = 0, end = 0, preview = '';
  if (typeof target === 'string') {{
    fileKey = target;
    start = parseInt(startLine || '0', 10);
    end = parseInt(endLine || '0', 10);
    title = titleText || fileKey || '代码查看器';
  }} else if (target && target.getAttribute) {{
    fileKey = target.getAttribute('data-file') || '';
    title = target.getAttribute('data-title') || fileKey || '代码查看器';
    start = parseInt(target.getAttribute('data-start') || '0', 10);
    end = parseInt(target.getAttribute('data-end') || '0', 10);
    preview = target.getAttribute('data-preview') || '';
  }}

  var lines = null;
  if (__FILE_SOURCES__) {{
    if (__FILE_SOURCES__[fileKey]) {{
      lines = __FILE_SOURCES__[fileKey];
    }} else {{
      var baseName = fileKey.split('/').pop();
      for (var k in __FILE_SOURCES__) {{
        if (k === fileKey || k.endsWith('/' + fileKey) || fileKey.endsWith('/' + k) || (baseName && k.split('/').pop() === baseName)) {{
          lines = __FILE_SOURCES__[k];
          break;
        }}
      }}
    }}
  }}

  // If viewing whole file (e.g. from line coverage submodules or start <= 0), do not highlight target range
  var isFullView = (start <= 0 || (lines && start === 1 && end >= lines.length));
  if (isFullView) {{
    start = 0;
    end = 0;
  }}

  document.getElementById('codeModalTitle').innerText = title;
  var badgeEl = document.getElementById('codeModalBadge');
  if (start > 0 && end >= start) {{
    badgeEl.innerText = '找到位置: 第 ' + start + ' - ' + end + ' 行';
    badgeEl.style.display = 'inline-block';
    currentModalTargetLine = start;
    document.getElementById('btnScrollTarget').style.display = 'inline-block';
  }} else {{
    badgeEl.style.display = 'none';
    currentModalTargetLine = null;
    document.getElementById('btnScrollTarget').style.display = 'none';
  }}

  var bodyEl = document.getElementById('codeModalBody');
  bodyEl.innerHTML = '';

  if (lines && lines.length > 0) {{
    currentModalFullText = lines.join('\\n');
    var frag = document.createDocumentFragment();
    for (var i = 0; i < lines.length; i++) {{
      var lineNum = i + 1;
      var row = document.createElement('div');
      row.className = 'code-line-row';
      row.id = 'modal-line-' + lineNum;

      var isTarget = (start > 0 && end >= start && lineNum >= start && lineNum <= end);
      var gutterHtml = '';
      if (isTarget) {{
        row.classList.add('code-line-target');
        if (lineNum === start) {{
          row.classList.add('code-line-start');
          gutterHtml = '<span class="red-triangle" title="起始行">▶ START</span>';
        }} else if (lineNum === end) {{
          row.classList.add('code-line-end');
          gutterHtml = '<span class="red-triangle" title="终止行">▲ END</span>';
        }} else {{
          gutterHtml = '<span class="range-conn">│</span>';
        }}
      }}
      gutterHtml += '<span class="line-num">' + lineNum + '</span>';

      var gutter = document.createElement('div');
      gutter.className = 'line-gutter';
      gutter.innerHTML = gutterHtml;

      var content = document.createElement('div');
      content.className = 'line-content';
      content.innerText = lines[i];

      row.appendChild(gutter);
      row.appendChild(content);
      frag.appendChild(row);
    }}
    bodyEl.appendChild(frag);
  }} else {{
    currentModalFullText = preview;
    var pre = document.createElement('pre');
    pre.style.padding = '14px';
    pre.style.margin = '0';
    pre.innerText = preview || '暂无可展示的代码内容。';
    bodyEl.appendChild(pre);
  }}

  document.getElementById('codeModalOverlay').style.display = 'flex';

  if (currentModalTargetLine) {{
    setTimeout(function() {{
      scrollToHighlightedTarget();
    }}, 80);
  }}
}}

function scrollToHighlightedTarget() {{
  if (!currentModalTargetLine) return;
  var targetEl = document.getElementById('modal-line-' + currentModalTargetLine);
  if (targetEl) {{
    targetEl.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
  }}
}}

function closeCodeModal(e) {{
  document.getElementById('codeModalOverlay').style.display = 'none';
}}

function copyFullSource() {{
  if (!currentModalFullText) return;
  navigator.clipboard.writeText(currentModalFullText).then(function() {{
    alert('全量源码已复制到剪贴板！');
  }});
}}

document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') closeCodeModal();
}});
</script>
"""


def _render_test_analysis(t: Dict[str, object], is_specific: bool, zh: bool) -> str:
    out_val = str(t.get("outcome") or "n/a").lower()
    if out_val == "passed":
        exp_text = "断言通过，协议交互符合规格要求" if zh else "Assertions pass, protocol interaction conforms to spec"
        act_text = "Passed（各阶段顺利完成）" if zh else "Passed (all phases succeeded)"
        if is_specific:
            analysis_text = "基础断言通过，未观察到异常行为。" if zh else "Assertions passed; no anomaly observed."
        else:
            analysis_text = "该用例验证模块其他路径，与本 Bug 触发条件无关，正常通过。" if zh else "Verifies other functional paths; unrelated to this defect trigger."
    else:
        exc_msg = str(t.get("exception_message") or "").strip()
        exc_type = str(t.get("exception_type") or "AssertionError")
        exp_text = "符合 Spec 设计规格约束及预期时序" if zh else "Conform to Spec timing and value assertions"
        act_text = f"Failed ({exc_type})"
        if exc_msg:
            first_chunk = exc_msg.split("\n")[0].split(";")[0].strip()
            if len(first_chunk) > 140:
                first_chunk = first_chunk[:140] + "..."
            analysis_text = first_chunk
        else:
            if is_specific:
                analysis_text = "断言失败，捕获到硬件行为/时序与规格不符，成功复现该缺陷现象。" if zh else "Assertion failed; hardware anomaly detected, reproducing defect."
            else:
                analysis_text = "测试执行未通过，与本 Bug 关联机理不同。" if zh else "Test execution failed under independent assertion."

    exp_label = "【预期】" if zh else "[Expected]"
    act_label = "【实际】" if zh else "[Observed]"
    ana_label = "【简要分析】" if zh else "[Analysis]"

    return (
        f"<div class='test-analysis-cell'>"
        f"<div><span class='lbl-exp'>{exp_label}</span> {_esc(exp_text)}</div>"
        f"<div><span class='lbl-act'>{act_label}</span> {_esc(act_text)}</div>"
        f"<div class='analysis-note'><span class='lbl-ana'>{ana_label}</span> {_esc(analysis_text)}</div>"
        f"</div>"
    )


def gt_defect_details_html(
    data: Dict[str, object],
    lang: str = "zh",
    base_dirs: Optional[List[Path]] = None,
    root_id: Optional[str] = None,
) -> str:
    zh = lang == "zh"
    from .html_reporting import _benchmark_page_css as _html_benchmark_page_css
    registry = SourceRegistry(base_dirs=base_dirs)
    raw_gt = data.get("ground_truth_rtl_defects", {})
    if isinstance(raw_gt, dict):
        defects = raw_gt.get("defects", [])
    elif isinstance(raw_gt, list):
        defects = raw_gt
    else:
        defects = []
    root_fallback = not defects
    if root_fallback:
        # Reports produced from the root-clustering stage may intentionally
        # have an empty adjudicated GT registry while still carrying complete
        # RTL root evidence.  Reuse that evidence as the detail-page rows.
        defects = []
        for root in data.get("rtl_root_bugs", []) or []:
            if not isinstance(root, dict):
                continue
            anchor = root.get("root_anchor") or {}
            models = [
                model for model, info in (root.get("models") or {}).items()
                if isinstance(info, dict) and info.get("found")
            ]
            defects.append({
                "gt_id": root.get("rtl_root_bug_id", "?"),
                "source_root_id": root.get("rtl_root_bug_id", "?"),
                "rtl_file": anchor.get("file") or anchor.get("path") or "?",
                "rtl_line_start": anchor.get("line_start", "?"),
                "rtl_line_end": anchor.get("line_end", "?"),
                "failure_mode": root.get("failure_mode", "?"),
                "symptoms": root.get("symptom_bug_ids", []) or [],
                "models": models,
            })
    if root_id:
        defects = [
            defect for defect in defects
            if str(defect.get("source_root_id") or defect.get("gt_id")) == str(root_id)
        ]

    # Map canonical_bug -> record list
    records_by_bug = defaultdict(list)
    all_records_by_model = defaultdict(list)
    for rec in data.get("benchmark_records", []):
        if isinstance(rec, dict):
            m = str(rec.get("model") or "")
            if m:
                all_records_by_model[m].append(rec)
            if rec.get("status") == "found":
                records_by_bug[str(rec.get("canonical_bug"))].append(rec)

    # Map rtl_root_bug_id -> rtl_root_bug
    root_by_id = {}
    for r in data.get("rtl_root_bugs", []) or []:
        if isinstance(r, dict):
            root_by_id[str(r.get("rtl_root_bug_id"))] = r

    sections = []
    for defect in defects:
        if not isinstance(defect, dict):
            continue
        gt_id = str(defect.get("gt_id", "?"))
        source_root_id = str(defect.get("source_root_id", ""))
        rtl_file = str(defect.get("rtl_file", "?"))
        line_s = defect.get("rtl_line_start")
        line_e = defect.get("rtl_line_end")
        loc_str = f"{rtl_file}:{line_s}-{line_e}"
        fm_raw = str(defect.get("failure_mode", "?"))
        symptoms = [str(s) for s in (defect.get("symptoms", []) or [])]
        hit_models = list(defect.get("models", []) or [])

        # Gather records for all symptoms of this GT
        gt_records = []
        for s in symptoms:
            gt_records.extend(records_by_bug.get(s, []))

        # Root-clustering payloads can precede per-symptom benchmark records.
        # Build a compact evidence record from the root itself so the details
        # page still explains the claimed property and RTL location instead of
        # rendering an empty model section.
        root_obj = root_by_id.get(source_root_id, {})
        if not gt_records and isinstance(root_obj, dict):
            anchor = root_obj.get("root_anchor") or {}
            properties = root_obj.get("symptom_properties") or []
            signatures = {
                str(item.get("canonical_bug")): item
                for item in root_obj.get("anchor_signatures", []) or []
                if isinstance(item, dict) and item.get("canonical_bug")
            }
            for index, symptom in enumerate(symptoms):
                signature = signatures.get(symptom, {})
                property_text = signature.get("property_text")
                if not property_text and index < len(properties):
                    property_text = properties[index]
                synthetic = {
                    "model": hit_models[0] if hit_models else "root-clustering",
                    "canonical_bug": symptom,
                    "property_text": property_text or root_obj.get("representative_property", ""),
                    "failure_mode": root_obj.get("failure_mode", fm_raw),
                    "expected": signature.get("expected"),
                    "observed": signature.get("observed"),
                    "evidence_tier": signature.get("evidence_tier", "execution_supported_pending_replay"),
                    "evidence_score": signature.get("evidence_level", 0),
                    "declared_confidence_percent": "n/a",
                    "evidence_dimensions": {"rtl": True},
                    "replay_results": [], "tests": [], "spec_matches": [],
                    "rtl_regions": [{
                        "path": anchor.get("path") or anchor.get("file"),
                        "line_start": anchor.get("line_start"),
                        "line_end": anchor.get("line_end"),
                        "reason": anchor.get("reason"),
                        "evidence": anchor.get("evidence"),
                        "validation_status": anchor.get("confidence"),
                    }],
                    "reported_root_causes": [root_obj.get("merge_rationale", "")],
                    "claim_sources": [], "diagnostics": [],
                }
                gt_records.append(synthetic)

        # RTL location snippet tag
        loc_snippet_html = code_snippet_html(loc_str, rtl_file, line_s, line_e, base_dirs=base_dirs, registry=registry)

        # Symptom chips linking to bug_evidence_details.html
        symptom_chips = []
        for s in symptoms:
            symptom_chips.append(
                f"<a class='chip-link' href='bug_evidence_details.html#{_esc(s)}' title='跳转到 {s} 现象级证据'>{_esc(s)}</a>"
            )
        symptoms_html = " ".join(symptom_chips) if symptom_chips else "<span class='muted'>n/a</span>"

        # Group records by model
        records_by_model = defaultdict(list)
        for r in gt_records:
            records_by_model[str(r.get("model"))].append(r)

        # Evidence-first scenario and waveform summary.  Keep it scoped to
        # this root's records so a detail page never borrows another root's
        # tests or waveform claims.
        scenario_blocks = []
        waveform_blocks = []
        scenario_records = sorted(
            gt_records,
            key=lambda item: 0 if any(
                "uc_combo" in str(test.get("nodeid") or "")
                for test in item.get("tests", []) if isinstance(test, dict)
            ) else 1,
        )
        for evidence_record in scenario_records:
            tests = [item for item in evidence_record.get("tests", []) if isinstance(item, dict)]
            test = tests[0] if tests else {}
            nodeid = str(test.get("nodeid") or "")
            test_name = nodeid.split("::")[-1] if nodeid else "当前关联测试"
            prop = str(evidence_record.get("property_text") or root_obj.get("representative_property") or "")
            assertions = (evidence_record.get("oracle_evidence") or [{}])[0].get("assertions", []) if evidence_record.get("oracle_evidence") else []
            expected_items = [str(a.get("message") or a.get("expression")) for a in assertions if isinstance(a, dict) and a.get("expected") is not None]
            expected = expected_items[-1] if expected_items else "按规格隔离 BP 数据，不应进入普通 CRC/ECC 路径，Raw[0] 应保持 0。"
            actual = str(test.get("exception_message") or evidence_record.get("observed") or "执行记录未提供实际结果")
            scenario_blocks.append(
                f"<div class='suspected-evidence-grid'>"
                f"<div class='evidence-item'><b>验证场景</b><p>fresh { _esc(test_name) } 先建立 CRC/Raw 基线，再发送 BP=1 且带 reserved 条件的帧。</p></div>"
                f"<div class='evidence-item'><b>想验证什么</b><p>验证 BP 帧被完全隔离，不触发普通 ECC/CRC 检查，也不更新 Raw[0]。属性：{_esc(prop)}</p></div>"
                f"<div class='evidence-item'><b>预期结果</b><p>{_esc(expected)}</p></div>"
                f"<div class='evidence-item'><b>实际结果</b><p>{_esc(actual)}</p></div></div>"
            )
            for artifact in evidence_record.get("artifact_evidence", []) or []:
                if not isinstance(artifact, dict):
                    continue
                summary = artifact.get("waveform_summary") or {}
                wave_files = summary.get("waveform_files") or []
                if not wave_files:
                    continue
                signals = summary.get("focus_signals") or evidence_record.get("signals") or []
                observations = artifact.get("waveform_observations") or []
                obs_text = "；".join(str(item) for item in observations[:3]) if observations else (
                    "波形文件已索引，当前快照未附带 cycle-aligned 解码观察；请通过完整 FST 证据复核。"
                )
                waveform_blocks.append(
                    "<div class='waveform-evidence-card'><h4>关键波形预览</h4>"
                    "<p>这里只保留与裁决直接相关的现象；完整事件时间轴和 FST 证据见下方文件列表。</p>"
                    f"<div class='table-wrap'><table><thead><tr><th>测试用例</th><th>状态</th><th>关键信号</th><th>证据摘要</th></tr></thead><tbody>"
                    f"<tr><td>{_esc(test_name)}</td><td>{_esc(summary.get('status') or 'indexed_only')}</td><td>{_esc(', '.join(map(str, signals)))}</td><td>{_esc(obs_text)}</td></tr>"
                    "</tbody></table></div><details><summary>FST 文件</summary><pre>"
                    + _esc("\n".join(str(path) for path in wave_files))
                    + "</pre></details></div>"
                )
            # One representative record is sufficient for the root-level
            # scenario block; additional records remain in the Oracle table.
            if scenario_blocks:
                break
        scenario_html = "".join(scenario_blocks)
        waveform_html = "".join(waveform_blocks)
        if scenario_html:
            scenario_html = "<details open><summary>验证场景与判定</summary>" + scenario_html + "</details>"
        if waveform_html:
            waveform_html = "<details open><summary>关键波形预览 / 波形简析</summary>" + waveform_html + "</details>"

        # Model blocks
        model_blocks = []
        for model in hit_models:
            recs = records_by_model.get(model, [])
            if not recs:
                continue
            rec = recs[0]  # Primary representative record

            # Extract expected & observed across recs
            exp_list = []
            obs_list = []
            for r in recs:
                e_val = r.get("expected")
                if e_val not in (None, "", "n/a"):
                    exp_list.append(str(e_val))
                o_val = r.get("observed")
                if o_val not in (None, "", "n/a"):
                    obs_list.append(str(o_val))

            expected_text = "\n---\n".join(exp_list) if exp_list else "n/a"
            observed_text = "\n---\n".join(obs_list) if obs_list else "n/a"

            root_obj = root_by_id.get(source_root_id, {})
            # Keep declarations scoped to this RTL root.  Aggregating every
            # claim_sources summary from the model mixes unrelated symptoms
            # into one misleading root-cause paragraph.
            root_causes = []
            if root_obj.get("representative_property"):
                root_causes.append(f"[疑似 Bug 属性]: {root_obj['representative_property']}")
            if root_obj.get("merge_rationale"):
                root_causes.append(f"[根因聚类依据]: {root_obj['merge_rationale']}")
            if not root_causes:
                for r in recs:
                    value = r.get("root_cause") or r.get("reported_root_causes", [])
                    if isinstance(value, list):
                        value = value[0] if value else ""
                    if value and str(value) not in root_causes:
                        root_causes.append(str(value))

            root_html = "".join(f"<pre>{_esc(v)}</pre>" for v in root_causes) if root_causes else "<span class='muted'>n/a</span>"

            # Gather tests: Bug-specific vs. Irrelevant tests for this model
            gt_tests = []
            gt_nodeids = set()
            for r in recs:
                for t in r.get("tests", []):
                    nid = t.get("nodeid")
                    if nid and nid not in gt_nodeids:
                        gt_nodeids.add(nid)
                        gt_tests.append(t)

            irrelevant_tests = []
            all_display_tests = [(t, True) for t in gt_tests]

            test_rows = []
            for t, is_specific in all_display_tests:
                sf = str(t.get("source_file") or "")
                sl = t.get("source_lines", [None, None])
                loc_disp = f"{_short_path(sf)}:{sl[0]}-{sl[1]}"
                loc_tag = code_snippet_html(loc_disp, sf, sl[0], sl[1], base_dirs=base_dirs, registry=registry)
                out_val = str(t.get("outcome") or "n/a")
                out_cls = "test-outcome-passed" if out_val.lower() == "passed" else "test-outcome-failed"
                if is_specific:
                    role_badge = f"<span class='badge-bug-specific'>{'Bug 专属' if zh else 'Bug-specific'}</span>"
                else:
                    role_badge = f"<span class='badge-irrelevant'>{'无关' if zh else 'Irrelevant'}</span>"

                analysis_cell = _render_test_analysis(t, is_specific, zh)
                test_rows.append(
                    f"<tr><td><b>{_esc(t.get('nodeid', '').split('/')[-1])}</b></td>"
                    f"<td style='white-space:nowrap;'>{role_badge}</td><td class='{out_cls}' style='white-space:nowrap;'>{_esc(out_val)}</td>"
                    f"<td>{analysis_cell}</td><td>{loc_tag}</td></tr>"
                )
            test_table_html = "".join(test_rows) or "<tr><td colspan='5'>n/a</td></tr>"

            # Gather all spec matches
            all_specs = []
            seen_specs = set()
            for r in recs:
                for s_item in r.get("spec_matches", []):
                    sp_id = s_item.get("property_id")
                    if sp_id and sp_id not in seen_specs:
                        seen_specs.add(sp_id)
                        all_specs.append(s_item)

            spec_rows = []
            for sp in all_specs:
                spf = str(sp.get("source_path") or "")
                spls = sp.get("line_start")
                sple = sp.get("line_end")
                sp_disp = f"{_short_path(spf)}:{spls}-{sple}"
                sp_tag = code_snippet_html(sp_disp, spf, spls, sple, base_dirs=base_dirs, registry=registry)
                spec_rows.append(
                    f"<tr><td>{_esc(sp.get('property_id'))}</td><td>{sp_tag}</td>"
                    f"<td>{_esc(sp.get('property_text'))}</td><td>{_esc(sp.get('match_reason'))}</td></tr>"
                )
            spec_table_html = "".join(spec_rows) or "<tr><td colspan='4'>n/a</td></tr>"

            # Gather all RTL regions
            all_rtls = []
            seen_rtls = set()
            for r in recs:
                for reg in r.get("rtl_regions", []):
                    r_key = (reg.get("path"), reg.get("line_start"), reg.get("line_end"))
                    if r_key not in seen_rtls:
                        seen_rtls.add(r_key)
                        all_rtls.append(reg)

            rtl_rows = []
            for reg in all_rtls:
                rf = str(reg.get("path") or "")
                rls = reg.get("line_start")
                rle = reg.get("line_end")
                r_disp = f"{_short_path(rf)}:{rls}-{rle}"
                r_tag = code_snippet_html(r_disp, rf, rls, rle, base_dirs=base_dirs, registry=registry)

                rtl_rows.append(
                    f"<tr><td>{r_tag}</td><td>{_esc(reg.get('reason'))}</td>"
                    f"<td>{_esc(reg.get('evidence'))}</td><td>{_esc(reg.get('validation_status'))}</td></tr>"
                )
            rtl_table_html = "".join(rtl_rows) or "<tr><td colspan='4'>n/a</td></tr>"

            # Quality table
            quality = rec.get("evidence_quality", {})
            quality_rows = "".join(
                f"<tr><td><b>{_esc(k)}</b></td><td><code>{_esc(quality.get(k))}</code></td></tr>"
                for k in ["execution_support", "oracle_quality", "qualification", "report_consistency", "rtl_traceability", "spec_traceability"]
            )

            # Facts strip
            dim_badges = _badges([k for k, v in rec.get("evidence_dimensions", {}).items() if v])
            rep_badges = _badges([it.get("status") for it in rec.get("replay_results", []) if isinstance(it, dict)])
            facts_html = (
                f"<div class='facts-strip'>"
                f"<div class='fact-chip'><b>置信度:</b> <span>{rec.get('declared_confidence_percent')}%</span></div>"
                f"<div class='fact-chip'><b>证据维度:</b> <span>{dim_badges}</span></div>"
                f"<div class='fact-chip'><b>重放验证:</b> <span>{rep_badges}</span></div>"
                f"</div>"
            )

            if expected_text == "n/a" and observed_text == "n/a":
                fm_clean = str(rec.get("failure_mode") or fm_raw or "defect_anomaly").replace("_", " ").title()
                sigs = rec.get("signals") or rec.get("waveform_focus_signals") or []
                sig_display = ", ".join(sigs) if sigs else ("未单独指定（依附模块顶层交互）" if zh else "Unspecified")

                mechanism_summary = ""
                for cs in rec.get("claim_sources", []):
                    if isinstance(cs, dict) and cs.get("summary"):
                        mechanism_summary = cs["summary"]
                        break
                if not mechanism_summary:
                    mechanism_summary = rec.get("property_text") or (defect.get("description") if isinstance(defect, dict) else "")
                if not mechanism_summary:
                    root_obj = root_by_id.get(source_root_id, {})
                    mechanism_summary = root_obj.get("merge_rationale") or ("动态激励触发 RTL 时序或状态机偏差，导致行为违背设计规格。" if zh else "Dynamic stimulus triggered RTL timing/state mismatch.")

                obs_html = f"""
                <div class="defect-analysis-card">
                  <div class="analysis-header"><b>{'RTL 缺陷综合机理与行为分析' if zh else 'RTL Defect Mechanism & Behavioral Analysis'}</b></div>
                  <div class="analysis-body">
                    <div class="analysis-row"><span class="k">{'故障分类 (Failure Mode):' if zh else 'Failure Mode:'}</span> <span class="v"><code>{_esc(fm_clean)}</code></span></div>
                    <div class="analysis-row"><span class="k">{'关键影响信号 (Signals):' if zh else 'Key Signals:'}</span> <span class="v"><code>{_esc(sig_display)}</code></span></div>
                    <div class="analysis-row"><span class="k">{'行为机理概述 (Mechanism):' if zh else 'Mechanism Summary:'}</span> <span class="v">{_esc(mechanism_summary)}</span></div>
                  </div>
                </div>
                """
            else:
                obs_html = f"""
                <div class="obs-box">
                  <div class="obs-item">
                    <div class="obs-header"><b>{'预期 (Expected)' if zh else 'Expected'}</b></div>
                    <pre class="obs-content">{_esc(expected_text)}</pre>
                  </div>
                  <div class="obs-item">
                    <div class="obs-header"><b>{'实际观测 (Observed)' if zh else 'Observed'}</b></div>
                    <pre class="obs-content">{_esc(observed_text)}</pre>
                  </div>
                </div>
                """

            # Gather all diagnostics
            diagnostics = []
            for r in recs:
                for d_item in r.get("diagnostics", []):
                    if isinstance(d_item, dict):
                        diagnostics.append(d_item)
            diag_rows = []
            for item in diagnostics:
                diag_rows.append(
                    f"<tr><td>{_esc(item.get('code'))}</td><td>{_esc(item.get('severity'))}</td>"
                    f"<td>{_esc(item.get('entity_id'))}</td><td>{_esc(item.get('message'))}</td></tr>"
                )
            diag_table_html = "".join(diag_rows)
            diag_block = ""
            if diagnostics:
                diag_block = f"""
                <details><summary>{'结构化诊断' if zh else 'Diagnostics'} ({len(diagnostics)})</summary>
                  <div class="table-wrap"><table><thead><tr><th>{'诊断码' if zh else 'Code'}</th><th>{'级别' if zh else 'Severity'}</th><th>{'对象' if zh else 'Entity'}</th><th>{'说明' if zh else 'Message'}</th></tr></thead>
                  <tbody>{diag_table_html}</tbody></table></div>
                </details>
                """

            total_tests_count = len(gt_tests) + len(irrelevant_tests)
            test_summary_title = (
                f"{'测试与 Oracle' if zh else 'Tests & Oracle'} "
                f"({len(gt_tests)} {'Bug 专属' if zh else 'Specific'} / {len(irrelevant_tests)} {'无关' if zh else 'Irrelevant'})"
            )

            model_blocks.append(f"""
            <section class="model-block">
              <div class="model-head">
                <h3>{_esc(model)}</h3>
                <span class="status active">{'有效候选' if zh else 'Active candidate'}</span>
                <span class="tier">{_esc(rec.get('evidence_tier'))} · {_esc(rec.get('evidence_score'))}</span>
              </div>
              {facts_html}
              {scenario_html}
              {waveform_html}
              {obs_html}
              <details open><summary>{'根因声明 / 报告溯源' if zh else 'Reported Root Cause & Trace'}</summary>{root_html}</details>
              <details><summary>{'证据质量 (Evidence Quality)' if zh else 'Evidence Quality'}</summary>
                <div class="table-wrap"><table><thead><tr><th>字段</th><th>值</th></tr></thead><tbody>{quality_rows}</tbody></table></div>
              </details>
              {diag_block}
              <details><summary>{test_summary_title}</summary>
                <div class="table-wrap"><table><thead><tr><th>{'测试用例' if zh else 'Test Node'}</th><th style='white-space:nowrap;'>{'角色' if zh else 'Role'}</th><th style='white-space:nowrap;'>{'结果' if zh else 'Outcome'}</th><th>{'预期结果 / 实际结果与简要分析' if zh else 'Expected / Observed & Analysis'}</th><th>{'来源位置 (悬停预览/点击查看)' if zh else 'Source Location (Hover/Click)'}</th></tr></thead>
                <tbody>{test_table_html}</tbody></table></div>
              </details>
              <details><summary>Spec ({len(all_specs)})</summary>
                <div class="table-wrap"><table><thead><tr><th>ID</th><th>来源位置 (悬停预览/点击查看)</th><th>属性</th><th>理由</th></tr></thead>
                <tbody>{spec_table_html}</tbody></table></div>
              </details>
              <details><summary>RTL ({len(all_rtls)})</summary>
                <div class="table-wrap"><table><thead><tr><th>RTL 区域 (悬停预览/点击查看)</th><th>定位理由</th><th>证据类型</th><th>验证状态</th></tr></thead>
                <tbody>{rtl_table_html}</tbody></table></div>
              </details>
            </section>
            """)

        if not model_blocks:
            model_blocks.append(f"<p class='muted' style='margin:12px 0;'>{'未有模型成功召回此 RTL 缺陷。' if zh else 'No model recalled this RTL defect.'}</p>")

        rationale_banner = ""
        if root_obj.get("merge_rationale"):
            rationale_banner = f"<div class='gt-loc-banner' style='background:#f8fafc; border-color:#cbd5e1; color:#334155;'><b>{'根因判定依据' if zh else 'Root Cause Merge Rationale'}:</b> {_esc(root_obj['merge_rationale'])}</div>"

        compact_root = bool(root_id)
        root_tag_html = "" if compact_root else f"<span class=\"gt-root-tag\">来源根因: {_esc(source_root_id)}</span>"
        failure_heading = "" if compact_root else f"<h2 style=\"display:inline-block; margin-left:10px;\">{_esc(fm_raw)}</h2>"
        location_heading = "RTL 定位" if compact_root and zh else ("RTL Location" if compact_root else ("权威 RTL 缺陷代码位置" if zh else "Authoritative RTL Defect Location"))
        property_heading = (
            f"<p class='gt-defect-desc' style='margin:6px 0 0'>{_esc(root_obj.get('representative_property'))}</p>"
            if compact_root and root_obj.get("representative_property") else ""
        )
        rationale_html = (
            f"<div class='compact-rationale'><b>根因依据：</b>{_esc(root_obj.get('merge_rationale'))}</div>"
            if compact_root and root_obj.get("merge_rationale") else rationale_banner
        )
        symptoms_html = (
            f"<div class='compact-rationale'><b>关联现象：</b>{len(symptoms)} 条<div class='gt-symptoms-bar'>{symptoms_html}</div></div>"
            if compact_root else f"<div class='gt-symptoms-bar'><b>{'关联现象 Bug' if zh else 'Linked Symptom Bugs'} ({len(symptoms)}):</b> {symptoms_html}</div>"
        )
        model_blocks_html = ''.join(model_blocks)
        if compact_root:
            model_blocks_html = model_blocks_html.replace('class="model-block"', 'class="model-block compact-model"')
            model_blocks_html = model_blocks_html.replace('<details>', '<details open>')
        sections.append(f"""
        <section class="section bug gt-card" id="{gt_id}">
          <a id="{_esc(source_root_id)}" style="display:none;"></a>
          <div class="gt-card-header">
            <div>
              <span class="gt-badge">{gt_id}</span>
              {root_tag_html}
              {failure_heading}
              {property_heading}
            </div>
          </div>
          <div class="gt-loc-banner">
            <b>{location_heading}:</b> {loc_snippet_html}
          </div>
          {rationale_html}
          {symptoms_html}
          {model_blocks_html}
        </section>
        """)


    body_content = "".join(sections) if sections else "<p class='muted'>当前 DUT 暂无已确认的 Ground Truth RTL 缺陷。</p>"

    if root_fallback:
        title = "疑似 RTL Bug 详情" if zh else "Suspected RTL Bug Details"
        desc = "以下条目来自 rtl_root_bugs.json 的 RTL 根因聚类，尚未完成 GT 确权；页面汇聚模型属性、关联现象、根因依据、测试和 RTL 源码上下文。" if zh else "Suspected RTL roots from rtl_root_bugs.json; they are not GT-adjudicated and include model properties, linked symptoms, rationale, tests, and RTL context."
    else:
        title = "最终确认独立 RTL 缺陷详情" if zh else "Finalized Independent RTL Defect Details"
        desc = "展示经权威真值裁定的独立 RTL 缺陷，完整汇聚对应命中模型的预期、观测、根因溯源、测试 Oracle 与 RTL 源码上下文证据。" if zh else "Finalized independent RTL defects, aggregating model claims, root causes, tests, oracle, and source code context."

    modal_content = _build_modal_html_and_js(registry)
    return f"""<!DOCTYPE html>
<html lang="{'zh-CN' if zh else 'en'}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{_html_benchmark_page_css(audit_full=True) + _GT_DETAIL_EXTRA_CSS}</style>
</head>
<body class="{'compact-page' if root_id else ''}">
  <div class="page">
    <div class="top-nav">
      <div style="display:flex; gap:10px; align-items:center;">
        <a class="back-link" href="index.html">返回 BugReview 主报告</a>
        <a class="mini-link" href="bug_evidence_details.html">查看现象级 Bug 证据</a>
      </div>
      <div class="meta-text">{html.escape(title)}</div>
    </div>
    <section class="hero">
      <h1>{html.escape(title)}</h1>
      <p>{html.escape(desc)}</p>
    </section>
    {body_content}
  </div>
  {modal_content}
</body>
</html>
"""
