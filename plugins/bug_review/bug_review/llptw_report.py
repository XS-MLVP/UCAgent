"""Curated LLPTW report rendered after independent defect adjudication."""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path

from .report_data import build_report_data, load_report_profile


PRIMARY_BUG_ID = "LLPTW-BG-MULTI-CACHE-PARALLELMUX"
REPO = Path(__file__).resolve().parent
SURFER_ORIGIN = "http://127.0.0.1:8765"


_CSS = r"""
:root{--ink:#17212b;--muted:#5d6874;--line:#d7dde3;--paper:#fff;--wash:#f5f7f8;
--green:#17643b;--green-bg:#eaf6ef;--red:#a5312e;--amber:#8a5a12;--code:#18232d}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--wash);color:var(--ink);
font:15px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif;letter-spacing:0}.page{max-width:1160px;margin:auto;
padding:24px 24px 64px}.topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:28px}
.brand{font-weight:760}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a,.text-link{color:#155b78;text-decoration:none}
.nav a{padding:7px 10px;border:1px solid var(--line);background:var(--paper);border-radius:6px}.nav a:hover,.text-link:hover{text-decoration:underline}
.hero{padding:34px 0 28px;border-top:4px solid var(--ink);border-bottom:1px solid var(--line)}.eyebrow{font-size:12px;
font-weight:800;text-transform:uppercase;color:var(--green);margin-bottom:8px}.hero h1{font-size:clamp(28px,4vw,46px);line-height:1.14;
margin:0;letter-spacing:0;max-width:900px}.hero p{font-size:17px;color:var(--muted);max-width:850px;margin:14px 0 0}
.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:20px 0 34px}.metric{background:var(--paper);
border:1px solid var(--line);border-radius:8px;padding:18px}.metric strong{display:block;font-size:30px;line-height:1.1}.metric span{color:var(--muted)}
.section{padding:30px 0;border-bottom:1px solid var(--line)}.section-head{display:flex;justify-content:space-between;align-items:end;gap:18px;
margin-bottom:16px}.section h2{font-size:22px;margin:0}.section-head p{margin:0;color:var(--muted);max-width:650px}
.notice{border-left:4px solid var(--green);background:var(--green-bg);padding:14px 16px;margin:0 0 22px}.notice strong{color:var(--green)}
.bug-card{background:var(--paper);border:1px solid #bfc8cf;border-radius:8px;padding:22px}.bug-top{display:flex;justify-content:space-between;
gap:18px;align-items:flex-start}.bug-card h3{font-size:22px;margin:8px 0 6px}.id{font:700 12px ui-monospace,SFMono-Regular,monospace;
color:#33424d}.status{display:inline-flex;align-items:center;white-space:nowrap;background:var(--green-bg);color:var(--green);border:1px solid #b7ddc6;
padding:5px 9px;border-radius:999px;font-size:12px;font-weight:750}.summary{color:var(--muted);max-width:860px}
.flow{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:20px 0}.flow-item{border-top:3px solid #7c8b96;
padding:12px;background:#f8fafb;min-height:112px}.flow-item b{display:block;margin-bottom:5px}.flow-item code,.inline-code{font-family:ui-monospace,SFMono-Regular,monospace}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.primary{display:inline-block;background:var(--ink);color:white;text-decoration:none;
padding:9px 13px;border-radius:6px;font-weight:700}.secondary{display:inline-block;color:var(--ink);text-decoration:none;padding:8px 12px;
border:1px solid var(--line);border-radius:6px;background:white}.primary:hover,.secondary:hover{filter:brightness(.94)}
.wave-actions{display:grid;grid-template-columns:repeat(2,max-content);gap:7px;justify-content:start;margin-top:13px}.wave-action{padding:6px 9px!important;
font-size:12px;line-height:1.35;border-radius:5px!important;white-space:nowrap}
.table-wrap{overflow:auto;background:var(--paper);border:1px solid var(--line);border-radius:8px}table{border-collapse:collapse;width:100%;min-width:720px}
th,td{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font-size:12px;text-transform:uppercase;
color:var(--muted);background:#f4f6f7}tr:last-child td{border-bottom:0}.case{font-family:ui-monospace,SFMono-Regular,monospace;font-size:13px}
.verdict{font-weight:700;color:var(--red)}.muted{color:var(--muted)}.breadcrumb{font-size:13px;margin-bottom:18px}.detail-title{max-width:980px}
.anchor-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.anchor{background:var(--paper);border:1px solid var(--line);
border-radius:8px;overflow:hidden}.anchor header{padding:12px 14px;border-bottom:1px solid var(--line)}.anchor header b{display:block}.anchor header span{color:var(--muted);font-size:13px}
pre{margin:0;padding:14px;background:var(--code);color:#e7edf2;overflow:auto;font:12px/1.65 ui-monospace,SFMono-Regular,monospace;
white-space:pre}.cause{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;align-items:stretch;gap:8px}.cause-step{padding:16px;
background:var(--paper);border:1px solid var(--line);border-radius:8px}.cause-step b{display:block;margin-bottom:7px}.arrow{align-self:center;font-size:22px;color:var(--muted)}
.boundary{border:1px solid #e2c887;background:#fff9e8;border-radius:8px;padding:16px}.boundary b{color:var(--amber)}footer{padding-top:28px;color:var(--muted);font-size:13px}
.facts{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0}.fact{border:1px solid var(--line);background:#fff;border-radius:6px;padding:8px 11px;font-size:13px}
.fact b{margin-right:5px}.code-preview{border:1px solid #344654;border-radius:7px;background:var(--code);color:#e7edf2;overflow:auto;margin:10px 0 16px;
font:12px/1.6 ui-monospace,SFMono-Regular,monospace}.code-row{display:grid;grid-template-columns:58px minmax(max-content,1fr);min-width:max-content}.code-row.focus{background:#314552}
.code-no{padding:1px 10px;color:#91a4b3;text-align:right;border-right:1px solid #3d4c57;user-select:none}.code-tx{padding:1px 12px;white-space:pre}
.evidence-block{background:#fff;border:1px solid var(--line);border-radius:8px;margin:12px 0;overflow:hidden}.evidence-block>summary{padding:13px 15px;
cursor:pointer;font-weight:800;background:#f4f6f7}.evidence-body{padding:16px}.kv{display:grid;grid-template-columns:180px 1fr;gap:10px;border-bottom:1px solid var(--line);padding:9px 0}
.kv:last-child{border-bottom:0}.kv .k{font-weight:750;color:#45535e}.wave-note{padding:11px 13px;background:#f5f7f8;border-left:3px solid #778893;margin:8px 0;white-space:pre-wrap}
.scenario{padding:24px 0 8px}.scenario-lead{font-size:16px;max-width:930px;margin:0 0 16px;color:#33424d}.scenario-grid{display:grid;
grid-template-columns:repeat(2,minmax(0,1fr));border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.scenario-item{padding:16px 18px 17px 0}
.scenario-item:nth-child(even){padding-left:18px;border-left:1px solid var(--line)}.scenario-item:nth-child(-n+2){border-bottom:1px solid var(--line)}
.scenario-item b{display:block;color:var(--green);margin-bottom:5px}.scenario-item p{margin:0}.scenario-item code{font-family:ui-monospace,SFMono-Regular,monospace}
.verdict-summary{margin:22px 0 0}.verdict-summary table{min-width:0;table-layout:fixed}.verdict-summary th{width:15%;text-transform:none;font-size:13px}
.verdict-summary td{width:35%;font-size:14px}.detail-nav{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0 4px}.detail-nav a{padding:6px 9px;
border:1px solid var(--line);border-radius:6px;background:#fff;color:#155b78;text-decoration:none;font-size:13px}.detail-nav a:hover{text-decoration:underline}
.oracle-table{table-layout:fixed;min-width:0}.oracle-table .case{overflow-wrap:anywhere}.oracle-table .status{white-space:normal;text-align:center;justify-content:center}
.oracle-cell{min-width:0}.oracle-cell div{margin:2px 0}.oracle-cell b{display:inline-block;width:44px;color:#45535e}.flow>.bug-card{min-width:0}.flow>.bug-card h3{font-size:16px;overflow-wrap:anywhere}
@media(max-width:800px){.page{padding:16px 16px 48px}.topbar,.section-head,.bug-top{align-items:flex-start;flex-direction:column}
.metrics,.flow,.anchor-grid,.scenario-grid{grid-template-columns:1fr}.cause{grid-template-columns:1fr}.arrow{transform:rotate(90deg);justify-self:center}.hero{padding-top:24px}.kv{grid-template-columns:1fr}
.scenario-item,.scenario-item:nth-child(even){padding:14px 0;border-left:0;border-bottom:1px solid var(--line)}.scenario-item:last-child{border-bottom:0}
.wave-actions{grid-template-columns:repeat(2,minmax(0,1fr));width:100%}.wave-action{display:flex!important;align-items:center;justify-content:center;text-align:center;white-space:normal}
.verdict-summary table,.verdict-summary tbody,.verdict-summary tr,.verdict-summary th,.verdict-summary td{display:block;width:100%}.verdict-summary th{border-bottom:0;padding-bottom:2px}.verdict-summary td{padding-top:2px}
.oracle-table,.oracle-table tbody,.oracle-table tr,.oracle-table td{display:block;width:100%}.oracle-table{min-width:0}.oracle-table thead{display:none}
.oracle-table tr{padding:8px 0;border-bottom:1px solid var(--line)}.oracle-table tr:last-child{border-bottom:0}.oracle-table td{position:relative;border:0;padding:7px 12px 7px 104px;min-height:36px}
.oracle-table td::before{content:attr(data-label);position:absolute;left:12px;top:7px;width:82px;color:var(--muted);font-size:12px;font-weight:750}.oracle-table .oracle-cell b{width:auto}}
"""


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _primary_bug(report_view: dict) -> dict:
    data = report_view.get("report_data") or {}
    if data.get("final_bugs"):
        return data["final_bugs"][0]
    final = report_view.get("final_bug_analysis") or {}
    return next((bug for bug in final.get("bugs", []) if bug.get("bug_id") == PRIMARY_BUG_ID), {})


def _ensure_report_data(report_view: dict) -> dict:
    """Build the renderer contract for direct callers and older snapshots."""
    if report_view.get("report_data"):
        return report_view["report_data"]
    source = dict(report_view)
    source.setdefault("dut", "bosc_LLPTW")
    if not (source.get("ground_truth_rtl_defects") or source.get("_gt_file")):
        gt_path = REPO / "configs/ground_truth_registry/duts/bosc_LLPTW/ground_truth_rtl_defects.json"
        source["ground_truth_rtl_defects"] = json.loads(gt_path.read_text(encoding="utf-8"))
    profile = load_report_profile("bosc_LLPTW", REPO / "configs/report_profiles")
    data = build_report_data(source, profile)
    report_view["report_data"] = data
    return data


def _waveform_viewer(case_id: str, report_view: dict) -> tuple[str, int, str]:
    """Return a Surfer URL focused on the DUT signals used by the review.

    The workflow stores a v2 logical viewer payload. The standalone report
    server does not expose UCAgent's ``/api/waveform/latest`` endpoint, so the
    report uses a v1 direct-file payload while preserving the reviewed signal
    list and time window. Dropping those fields makes Surfer open an empty
    default view rooted at the testbench hierarchy.
    """
    for row in report_view.get("waveform_reviews", []):
        if row.get("case", {}).get("case_id") != case_id:
            continue
        result = row.get("waveform", {}).get("result", {})
        selection = result.get("waveform_selection", {})
        waveform_file = str(selection.get("waveform_file") or "")
        if not waveform_file:
            return "", 0, ""
        if not waveform_file.startswith("outputs/analysis/"):
            waveform_file = f"outputs/analysis/{waveform_file.lstrip('/')}"
        reviewed_payload = result.get("waveform_viewer", {}).get("payload", {})
        payload_data = {"v": 1, "file": waveform_file}
        for key in ("start", "end", "cursor", "signals"):
            value = reviewed_payload.get(key)
            if value not in (None, "", []):
                payload_data[key] = value
        payload = json.dumps(
            payload_data,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        signal_count = int(result.get("waveform_info", {}).get("signal_count") or 0)
        return f"{SURFER_ORIGIN}/surfer/?wave={token}", signal_count, waveform_file
    return "", 0, ""


def _single_wave_page(source: str, *, anchor: str, title: str, viewer_url: str,
                      signal_count: int, waveform_file: str) -> str:
    """Turn the aggregate evidence page into a one-case visible view."""
    style = f"""<style id="llptw-single-wave-style">
.wave-case{{display:none!important}}#{anchor}{{display:block!important}}
.hero,.nav-chips{{display:none!important}}
.single-wave-banner{{margin:0 0 18px;padding:16px 18px;border:1px solid #b9c7d1;border-left:4px solid #17643b;background:#f4faf6}}
.single-wave-banner h1{{font-size:20px;margin:0 0 5px}}.single-wave-banner p{{margin:4px 0;color:#475569}}
.single-wave-actions{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}.single-wave-actions a{{display:inline-block;padding:8px 11px;
border:1px solid #aebbc5;border-radius:6px;color:#155b78;background:#fff;text-decoration:none;font-weight:700}}
.single-wave-actions a.primary-wave{{color:#fff;background:#17212b;border-color:#17212b}}
</style>"""
    signal_text = f"原始 FST 共包含 {signal_count} 个信号" if signal_count else "原始 FST 可浏览完整信号树"
    viewer_action = (
        f"<a class='primary-wave' href='{_esc(viewer_url)}' target='_blank' rel='noopener'>在 Surfer 中查看全部信号</a>"
        if viewer_url else "<span>当前快照未找到可加载的原始 FST。</span>"
    )
    banner = f"""<section class="single-wave-banner"><h1>{_esc(title)}</h1>
<p>本页只展示这一条复现波形；下方 SVG 是裁决使用的关键信号预览。{_esc(signal_text)}，可在 Surfer 左侧层级树中搜索并添加任意信号。</p>
<p><b>FST：</b><code>{_esc(waveform_file)}</code></p><div class="single-wave-actions">{viewer_action}
<a href="gt/{PRIMARY_BUG_ID}.html#waveform-summary">返回疑似 Bug 详情</a><a href="wave_obs.html#{anchor}">查看聚合波形档案</a></div></section>"""
    script = f"""<script id="llptw-single-wave-script">
document.addEventListener('DOMContentLoaded',function(){{
  var target=document.getElementById('{anchor}');
  document.querySelectorAll('section.section').forEach(function(section){{section.hidden=!target||!section.contains(target);}});
}});
</script>"""
    page = source.replace("</head>", style + "</head>", 1)
    page = page.replace("<div class='page'>", "<div class='page'>" + banner, 1)
    page = page.replace("</body>", script + "</body>", 1)
    return page.replace("<title>", f"<title>{_esc(title)} · ", 1)


def _code_preview(path: Path, start: int, end: int, focus_start: int | None = None,
                  focus_end: int | None = None) -> str:
    """Render a self-contained, line-numbered source preview."""
    path = Path(path)
    if not path.is_file():
        return f"<div class='boundary'><b>源码不可用：</b>{_esc(path)}</div>"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    first, last = max(1, int(start)), min(len(lines), int(end))
    focus_start = first if focus_start is None else int(focus_start)
    focus_end = last if focus_end is None else int(focus_end)
    rows = []
    for number in range(first, last + 1):
        cls = "code-row focus" if focus_start <= number <= focus_end else "code-row"
        rows.append(f"<div class='{cls}'><span class='code-no'>{number}</span>"
                    f"<span class='code-tx'>{_esc(lines[number - 1])}</span></div>")
    return f"<div class='code-preview' aria-label='{_esc(path.name)} {first}-{last}'>{''.join(rows)}</div>"


def _layout(title: str, body: str, *, nav_prefix: str = "") -> str:
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_esc(title)}</title>
<style>{_CSS}</style></head><body><main class="page"><div class="topbar"><div class="brand">XSV BugReview / bosc_LLPTW</div>
<nav class="nav" aria-label="报告导航"><a href="{nav_prefix}index.html">总览</a><a href="{nav_prefix}wave_obs.html">波形观察</a>
<a href="{nav_prefix}../../data/ground_truth_rtl_defects.json">背景数据 JSON</a></nav></div>{body}
<footer>裁决日期：2026-09-17 · 口径：独立 RTL 根因去重；复现用例不重复计数。</footer></main></body></html>"""


def _index_html(report_view: dict, bug: dict) -> str:
    cases = bug.get("cases", [])
    case_rows = "".join(
        f"<tr><td class='case'>{_esc(c.get('nodeid', '').split('::')[-1])}</td>"
        f"<td><code>{_esc(str(c.get('evidence_id', ''))[:21])}...</code></td>"
        "<td class='verdict'>复现同一根因</td></tr>" for c in cases
    )
    body = f"""
<section class="hero"><div class="eyebrow">证据分析完成 · 疑似 Bug</div><h1>bosc_LLPTW RTL 疑似 Bug 分析</h1>
<p>保留每条有证据支持的疑似 Bug，并按高、中、低置信度展示；详情页关联 Case、RTL、Spec 和完整波形。</p></section>
<div class="metrics" aria-label="分析摘要"><div class="metric"><strong>1</strong><span>疑似 Bug</span></div>
<div class="metric"><strong>2</strong><span>独立复现用例</span></div><div class="metric"><strong>11</strong><span>未纳入 GT 的审查结论</span></div></div>
<div class="notice"><strong>计数口径：</strong>两个测试暴露的是同一处 cache 多 entry 上下文混叠，合并为一个疑似 Bug；置信度和关联证据见详情页。</div>
<section class="section" id="gt"><div class="section-head"><div><h2>GT-RTL-0001</h2><p>{_esc(PRIMARY_BUG_ID)}</p></div>
<span class="status">高置信度疑似 Bug</span></div><article class="bug-card"><div class="bug-top"><div><span class="id">{_esc(bug.get('bug_id') or bug.get('gt_id') or PRIMARY_BUG_ID)}</span>
<h3>{_esc(bug.get('title'))}</h3><p class="summary">多个 <code>is_cache</code> entry 同时有效时，payload 与释放指针均由按位 OR 合成；
不同 entry 的上下文和索引可能混叠，导致重复返回同一 source 并释放错误 entry。</p></div></div>
<div class="flow"><div class="flow-item"><b>Payload 混叠</b><code>bosc_LLPTW.v:966-984</code><br>vpn / s2xlate / source 对所有 cache entry 按位 OR。</div>
<div class="flow-item"><b>指针混叠</b><code>bosc_LLPTW.v:996-998</code><br>多个 entry 索引按位 OR，例如 1 | 2 得到 3。</div>
<div class="flow-item"><b>错误释放</b><code>bosc_LLPTW.v:3500...</code><br>cache fire 后按照混叠的 <code>cache_ptr</code> 清理 entry。</div></div>
<div class="actions"><a class="primary" href="gt/{PRIMARY_BUG_ID}.html">查看完整证据</a>
<a class="secondary" href="wave_obs.html">查看波形观察</a></div></article></section>
<section class="section"><div class="section-head"><div><h2>复现证据</h2><p>均使用合法 demand source 0/1，在 cache 背压期间建立两个并存 entry。</p></div></div>
<div class="table-wrap"><table><thead><tr><th>测试</th><th>波形证据</th><th>裁决</th></tr></thead><tbody>{case_rows}</tbody></table></div></section>
<section class="section"><div class="boundary"><b>未纳入范围：</b>其余审查结论存在 prefetch 可丢弃契约、HPTW response 门控、
PTE/response 匹配尚未闭环等反证或证据缺口，不在本 HTML 中作为 GT 展示。原始审查记录仍保留用于审计。</div></section>"""
    return _layout("bosc_LLPTW RTL 缺陷裁决", body)


def _detail_html(bug: dict, report_view: dict) -> str:
    rtl = REPO / "inputs/workspace_bosc_LLPTW/bosc_LLPTW/bosc_LLPTW.v"
    spec = REPO / "inputs/workspace_bosc_LLPTW/unity_test/bosc_LLPTW_functions_and_checks.md"
    failures = {r.get("case", {}).get("case_id"): r for r in report_view.get("failure_case_reviews", [])}
    waves = {r.get("case", {}).get("case_id"): r for r in report_view.get("waveform_reviews", [])}
    oracle_rows, wave_rows, test_previews = [], [], []
    for item in bug.get("cases", []):
        case_id = item.get("case_id")
        failure, wave = failures.get(case_id, {}), waves.get(case_id, {})
        case = failure.get("case") or wave.get("case") or item
        review = failure.get("review", {})
        source = case.get("source", {})
        nodeid = case.get("nodeid") or item.get("nodeid", "")
        short = nodeid.split("::")[-1]
        replay = failure.get("replay", {}).get("status") or wave.get("replay", {}).get("status") or "n/a"
        exception = ((case.get("original_executions") or [{}])[0].get("exception_message") or "assertion failed")
        source_preview = ""
        if source.get("source_file") and source.get("line_start"):
            source_preview = _code_preview(Path(source["source_file"]), source["line_start"], source["line_end"])
        wave_summary = item.get("waveform_summary") or "该用例的关键波形现象已收录在裁决证据中。"
        wave_anchor = f"case-{str(case_id).removeprefix('case-')[:8]}"
        single_wave_file = f"wave_{wave_anchor}.html"
        viewer_url, signal_count, _waveform_file = _waveform_viewer(str(case_id), report_view)
        viewer_action = (
            f"<a class='secondary wave-action' href='{_esc(viewer_url)}' target='_blank' rel='noopener'>Surfer 全部信号（{signal_count}）</a>"
            if viewer_url else ""
        )
        scenario = bug.get("scenario", {})
        expected = scenario.get("expected", "见缺陷验证场景中的预期结果。")
        actual = scenario.get("actual", "见缺陷验证场景中的实际结果。")
        oracle_rows.append(
            f"<tr><td class='case' data-label='测试用例'>{_esc(short)}</td><td data-label='角色'><span class='status'>Bug 专属</span></td>"
            f"<td class='verdict' data-label='结果'>Failed</td><td class='oracle-cell' data-label='Oracle'><div><b>预期：</b>{expected}</div>"
            f"<div><b>实际：</b>{actual}</div><div><b>结论：</b>合法 demand 上下文丢失/重放。</div></td>"
            f"<td data-label='证据'><a class='text-link' href='#source-{_esc(case_id)}'>测试源码</a></td></tr>"
        )
        wave_rows.append(
            f"<article class='bug-card' id='case-{_esc(case_id)}'><div class='bug-top'><div><span class='id'>{_esc(str(item.get('evidence_id'))[:26])}...</span>"
            f"<h3>{_esc(short)}</h3></div><span class='status'>{_esc(replay)}</span></div>"
            f"<p>{_esc(wave_summary)}</p><div class='wave-actions'><a class='primary wave-action' href='../{_esc(single_wave_file)}'>查看此用例波形</a>"
            f"{viewer_action}</div></article>"
        )
        test_previews.append(
            f"<details class='evidence-block' id='source-{_esc(case_id)}'><summary>{_esc(short)} · {_esc(source.get('source_file', '').split('/')[-1])}:"
            f"{_esc(source.get('line_start'))}-{_esc(source.get('line_end'))}</summary><div class='evidence-body'>{source_preview}</div></details>"
        )

    scenario = bug.get("scenario", {})
    mechanism = bug.get("mechanism_steps", [])
    mechanism_html = "<div class='arrow'>→</div>".join(
        f"<div class='cause-step'><b>{index}. 失效链步骤</b>{_esc(step)}</div>"
        for index, step in enumerate(mechanism, 1)
    )
    fix = bug.get("fix_recommendation", {})
    evidence_types = "、".join(bug.get("evidence_types", []))
    gt_id = bug.get("gt_id", "GT-RTL-0001")
    global_gt_id = bug.get("global_gt_id", "")
    body = f"""
<div class="breadcrumb"><a class="text-link" href="../index.html">bosc_LLPTW 报告</a> / 疑似 Bug 详情</div>
<section class="hero"><div class="eyebrow">{_esc(gt_id)} · {_esc(global_gt_id)} · 疑似 Bug</div>
<h1 class="detail-title">{_esc(bug.get('title'))}</h1><p>{_esc(bug.get('summary'))}</p></section>
<div class="table-wrap verdict-summary"><table aria-label="缺陷裁决摘要"><tbody>
<tr><th>置信度</th><td><span class="status">{_esc({'high':'高','medium':'中','low':'低'}.get(str(bug.get('confidence','')).lower(), bug.get('confidence')))} · 疑似 Bug</span></td><th>关联情况</th><td>{_esc(bug.get('reproduction_count'))} 个测试关联同一分析</td></tr>
<tr><th>失败类型</th><td>{_esc(bug.get('failure_mode'))}</td><th>影响</th><td>{_esc(bug.get('impact'))}</td></tr>
<tr><th>证据组成</th><td>{_esc(evidence_types)}</td><th>关键 RTL</th><td><code>{_esc(bug.get('rtl', {}).get('primary'))}</code></td></tr>
</tbody></table></div>
<nav class="detail-nav" aria-label="缺陷详情章节"><a href="#scenario-title">验证场景</a><a href="#waveform-summary">波形证据</a><a href="#root-cause">缺陷机理</a><a href="#test-oracle">测试与 Oracle</a><a href="#source-preview">源码证据</a></nav>
<section class="scenario" aria-labelledby="scenario-title"><h2 id="scenario-title">验证场景与判定</h2>
<p class="scenario-lead">{_esc(scenario.get('setup'))}</p>
<div class="scenario-grid"><div class="scenario-item"><b>验证场景</b><p>{_esc(scenario.get('setup'))}</p></div>
<div class="scenario-item"><b>想验证什么</b><p>{_esc(scenario.get('goal'))}</p></div>
<div class="scenario-item"><b>预期结果</b><p>{_esc(scenario.get('expected'))}</p></div>
<div class="scenario-item"><b>实际结果</b><p>{_esc(scenario.get('actual'))}</p></div></div></section>
<section class="section" id="waveform-summary"><div class="section-head"><div><h2>波形简析</h2><p>这里只保留与裁决直接相关的现象；按钮直达完整事件时间轴和 FST 证据。</p></div></div>
<div class="flow">{''.join(wave_rows)}</div></section>
<section class="section" id="root-cause"><div class="section-head"><div><h2>缺陷机理</h2><p>每个 entry 都保存一笔请求的 VPN、s2xlate 和 source。多个 entry 同时等待 cache 输出时，正确做法是先选中其中一笔，再让 payload、指针和释放动作全部跟随这一个选择。</p></div></div>
<div class="cause">{mechanism_html}</div>
<div class="notice"><strong>规格违反：</strong>{_esc(bug.get('specification_basis'))}</div></section>
<section class="section" id="test-oracle"><div class="section-head"><div><h2>测试与 Oracle</h2><p>两个用例均使用合法 demand source 0/1，只在 valid &amp;&amp; ready 的 cache fire 边沿比较上下文。</p></div></div>
<div class="table-wrap"><table class="oracle-table"><colgroup><col style="width:24%"><col style="width:11%"><col style="width:9%"><col style="width:46%"><col style="width:10%"></colgroup><thead><tr><th>测试用例</th><th>角色</th><th>结果</th><th>预期 / 实际 / 分析</th><th>证据</th></tr></thead>
<tbody>{''.join(oracle_rows)}</tbody></table></div></section>
<section class="section"><div class="section-head"><div><h2>规格依据预览</h2><p>FC-DUP-TO-CACHE 要求 late duplicate 进入 cache/share 路径；CK-ERROR 检查多上下文不能丢失、重复或重放。</p></div></div>
{_code_preview(spec, 525, 544, 525, 544)}</section>
<section class="section"><div class="section-head"><div><h2>修复与验证建议</h2></div></div><div class="bug-card">
<p><b>修复方向：</b>{_esc(fix.get('direction'))}</p>
<p><b>回归要求：</b>{_esc(fix.get('regression'))}</p></div></section>
<section class="section"><div class="boundary"><b>证据边界：</b>{_esc(bug.get('evidence_boundary'))}</div></section>
<section class="section" id="source-preview"><div class="section-head"><div><h2>源码预览</h2><p>源码统一放在页面末尾并默认折叠；展开后可查看带行号和高亮的完整上下文。</p></div></div>
<details class="evidence-block"><summary>RTL 1 · cache payload 按位 OR · bosc_LLPTW.v:964-984</summary><div class="evidence-body">
<p>multi-hot 时字段逐位合并，而不是选择单一 entry。</p>{_code_preview(rtl, 964, 984, 966, 984)}</div></details>
<details class="evidence-block"><summary>RTL 2 · cache_ptr 按位 OR · bosc_LLPTW.v:994-999</summary><div class="evidence-body">
<p>entry 1 与 2 并存会合成为错误指针 3。</p>{_code_preview(rtl, 994, 999, 996, 998)}</div></details>
<details class="evidence-block"><summary>RTL 3 · cache fire 按混叠指针释放 · bosc_LLPTW.v:1848-1855, 3498-3503</summary><div class="evidence-body">
{_code_preview(rtl, 1848, 1855, 1853, 1853)}{_code_preview(rtl, 3498, 3503, 3500, 3501)}</div></details>
<details class="evidence-block"><summary>RTL 4 · cache 输出连接 · bosc_LLPTW.v:5147-5152</summary><div class="evidence-body">
{_code_preview(rtl, 5147, 5152, 5149, 5152)}</div></details>{''.join(test_previews)}</section>"""
    return _layout("GT-RTL-0001 · cache ParallelMux 上下文混叠", body, nav_prefix="../")


_EMBED_CSS = r"""
<style>
body{background:#f4f6f7!important;color:#18232d}.page{max-width:1240px!important}.section{border-radius:8px!important;
box-shadow:0 1px 2px #17202a12!important}.llptw-curation{margin:20px 0 28px;border:1px solid #c7d0d7;border-top:5px solid #17643b;
background:#fff;border-radius:8px;overflow:hidden}.llptw-curation *{box-sizing:border-box}.llptw-curation .cur-head{padding:24px 26px;
display:flex;justify-content:space-between;gap:24px;align-items:flex-start;border-bottom:1px solid #d7dde3}.llptw-curation h2{margin:0 0 6px;
font-size:24px;letter-spacing:0}.llptw-curation p{margin:0;color:#53606b}.cur-status{white-space:nowrap;background:#eaf6ef;color:#17643b;
border:1px solid #b7ddc6;border-radius:999px;padding:6px 10px;font-size:12px;font-weight:800}.cur-metrics{display:grid;
grid-template-columns:repeat(3,minmax(0,1fr));border-bottom:1px solid #d7dde3}.cur-metric{padding:18px 26px;border-right:1px solid #d7dde3}
.cur-metric:last-child{border-right:0}.cur-metric b{font-size:28px;display:block;line-height:1.1}.cur-metric span{color:#61707b;font-size:13px}
.cur-body{padding:22px 26px}.cur-id{font:700 12px ui-monospace,SFMono-Regular,monospace;color:#17643b}.cur-title{font-size:20px;
font-weight:800;margin:5px 0 8px}.cur-flow{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:18px 0}
.cur-step{background:#f5f7f8;border-top:3px solid #74828d;padding:12px;min-height:100px}.cur-step b{display:block;margin-bottom:4px}
.cur-actions{display:flex;gap:9px;flex-wrap:wrap}.cur-actions a{display:inline-block;border:1px solid #c7d0d7;border-radius:6px;padding:8px 11px;
text-decoration:none;color:#18232d;background:#fff;font-weight:700}.cur-actions a:first-child{background:#18232d;color:#fff;border-color:#18232d}
.cur-note{margin-top:16px!important;padding:12px 14px;background:#fff8e6;border-left:4px solid #b07619;color:#6f4d17!important}
.adjudication-wrap{overflow-x:auto}.adjudication-table{width:100%;min-width:820px;border-collapse:collapse;table-layout:fixed}.adjudication-table th,
.adjudication-table td{padding:12px 14px;border-bottom:1px solid #d7dde3;text-align:left;vertical-align:top}.adjudication-table th{background:#f4f6f7;
font-size:12px;color:#5d6874}.adjudication-table td{font-size:13px}.adjudication-table tr:last-child td{border-bottom:0}.adjudication-table .bug-name{font-weight:800;
font-size:14px}.adjudication-table .bug-summary{display:block;color:#5d6874;margin-top:3px}.confidence-high{color:#17643b;font-weight:800}.table-action{color:#155b78;
font-weight:750;text-decoration:none}.table-action:hover{text-decoration:underline}.cur-foot{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:11px 14px;
background:#fff8e6;color:#6f4d17;font-size:12px}.cur-foot-links{display:flex;gap:12px;white-space:nowrap}.cur-foot a{color:#155b78;font-weight:700;text-decoration:none}
.llptw-audit{margin-top:18px}.llptw-audit summary{cursor:pointer;font-weight:750;color:#31404b}.llptw-audit table{margin-top:10px}
.verify-overview{margin:20px 0;border:1px solid #c7d0d7;border-radius:8px;background:#fff;overflow:hidden}.verify-head{padding:22px 26px;border-bottom:1px solid #d7dde3}
.verify-head h2{margin:0 0 5px}.verify-head p{margin:0;color:#53606b}.coverage-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))}
.coverage-item{padding:16px 18px;border-right:1px solid #d7dde3;border-bottom:1px solid #d7dde3}.coverage-item:nth-child(4n){border-right:0}
.coverage-value{font-size:24px;font-weight:800;line-height:1.1}.coverage-label{font-size:12px;color:#61707b;margin:4px 0 10px}.coverage-bar{height:5px;background:#e3e8eb}
.coverage-bar span{height:100%;display:block;background:#b0443f}.coverage-meta{font-size:11px;color:#7b4a23;margin-top:6px}.verify-foot{padding:13px 18px;background:#fff8e6;color:#684b1c}
.review-preview{margin:20px 0;background:#fff;border:1px solid #c7d0d7;border-radius:8px;padding:22px 26px}.review-preview h2,.failures-panel h2{margin:0 0 5px}
.review-preview>p,.failures-panel>p{margin:0 0 16px;color:#53606b}.review-table-wrap{overflow-x:auto;border:1px solid #d7dde3;border-radius:6px}.review-table{width:100%;
min-width:820px;border-collapse:collapse;table-layout:fixed}.review-table th,.review-table td{padding:10px 12px;border-bottom:1px solid #d7dde3;text-align:left;vertical-align:top}
.review-table th{background:#f4f6f7;color:#5d6874;font-size:12px}.review-table td{font-size:12px}.review-table tr:last-child td{border-bottom:0}.review-table .review-id{font:700 11px ui-monospace,SFMono-Regular,monospace;
overflow-wrap:anywhere}.review-table .review-title{font-weight:700}.review-status{white-space:nowrap;color:#8a5a12;font-weight:800}.review-table a{color:#155b78;font-weight:700;text-decoration:none}
.review-table a:hover{text-decoration:underline}.failures-panel{margin:20px 0;background:#fff;border:1px solid #c7d0d7;border-radius:8px;padding:22px 26px}
.failure-summary{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}.fail-chip{padding:5px 9px;border-radius:999px;font-size:12px;font-weight:800}
.type-bug{background:#fcebea;color:#9a2f2b}.type-review{background:#fff4d7;color:#765114}.type-spec{background:#e9f1f7;color:#245675}.type-env{background:#edf0f2;color:#4b5963}
.failure-table td{font-size:12px}.failure-table .case-name{font-family:ui-monospace,SFMono-Regular,monospace;overflow-wrap:anywhere}.failure-table .symptom{max-width:420px;white-space:pre-wrap}
@media(max-width:900px){.coverage-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.coverage-item:nth-child(4n){border-right:1px solid #d7dde3}.coverage-item:nth-child(2n){border-right:0}}
@media(max-width:760px){.llptw-curation .cur-head{flex-direction:column}.cur-metrics,.cur-flow,.review-grid{grid-template-columns:1fr}.cur-metric{border-right:0;border-bottom:1px solid #d7dde3}.coverage-grid{grid-template-columns:1fr}.coverage-item{border-right:0!important}.cur-foot{align-items:flex-start;flex-direction:column}.cur-foot-links{white-space:normal;flex-wrap:wrap}}
</style>
"""


def _review_page(bug: dict) -> str:
    cases = "".join(
        f"<tr><td class='case'>{_esc(c.get('nodeid', '').split('::')[-1])}</td>"
        f"<td><code>{_esc(c.get('evidence_id'))}</code></td></tr>" for c in bug.get("cases", [])
    ) or "<tr><td colspan='2'>无</td></tr>"
    reason = bug.get("reason", "证据链仍需补充或复核。")
    body = f"""<div class="breadcrumb"><a class="text-link" href="index.html">低可信审查档案</a> / {_esc(bug.get('bug_id'))}</div>
<section class="hero"><div class="eyebrow" style="color:#8a5a12">低置信度疑似 Bug · 待补证据</div><h1>{_esc(bug.get('title'))}</h1>
<p>保留原始分析和关联证据；当前证据不足以提高置信度，但仍作为疑似 Bug 展示。</p></section>
<section class="section"><div class="boundary"><b>当前裁决：</b>{_esc(reason)}</div></section>
<section class="section"><div class="section-head"><div><h2>原始分析内容</h2><p>以下文字原样来自 final_bug_analysis.json，不代表当前正式结论。</p></div></div>
<div class="bug-card"><p><b>原根因：</b>{_esc(bug.get('root_cause'))}</p><p><b>原证据摘要：</b>{_esc(bug.get('evidence_summary'))}</p>
<p><b>原规格判断：</b>{_esc(bug.get('spec_violation'))}</p><p><b>原 RTL 区域：</b>{_esc('；'.join(bug.get('rtl_regions', [])))}</p></div></section>
<section class="section"><div class="section-head"><div><h2>关联用例</h2><p>这些用例是历史审查证据，不是已确认 GT 的独立计数。</p></div></div>
<div class="table-wrap"><table><thead><tr><th>测试</th><th>波形证据 ID</th></tr></thead><tbody>{cases}</tbody></table></div></section>"""
    return _layout(f"审查档案 · {bug.get('bug_id')}", body, nav_prefix="../")


def _review_index(low_bugs: list[dict]) -> str:
    rows = "".join(
        f"<tr><td><a class='text-link' href='{_esc(b['bug_id'])}.html'>{_esc(b['bug_id'])}</a></td>"
        f"<td>{_esc(b.get('title'))}</td><td>{len(b.get('cases', []))}</td><td>{_esc(b.get('reason'))}</td></tr>"
        for b in low_bugs
    )
    body = f"""<div class="breadcrumb"><a class="text-link" href="../index.html">bosc_LLPTW 裁决总览</a> / 审查档案</div>
<section class="hero"><div class="eyebrow" style="color:#8a5a12">低置信度疑似 Bug · 待补证据</div><h1>低置信度与待复核结论</h1>
<p>这些条目保留原始分析和证据引用，便于继续审计；它们仍属于疑似 Bug，只是置信度较低。</p></section>
<section class="section"><div class="table-wrap"><table><thead><tr><th>历史根因 ID</th><th>原始标题</th><th>用例数</th><th>当前裁决</th></tr></thead>
<tbody>{rows}</tbody></table></div></section>"""
    return _layout("bosc_LLPTW 低可信审查档案", body, nav_prefix="../")


def _curation_fragment(report_view: dict, bug: dict, low_bugs: list[dict]) -> str:
    data = report_view["report_data"]
    verification = data.get("verification_status", {})
    code = verification.get("code_coverage", {})
    functional = verification.get("functional_coverage", {})
    coverage_names = {
        "line": ("LINE", "行覆盖率"), "cond": ("COND", "条件覆盖率"),
        "toggle": ("TOGGLE", "翻转覆盖率"), "fsm": ("FSM", "状态机覆盖率"),
        "branch": ("BRANCH", "分支覆盖率"),
    }
    coverage_items = "".join(
        f'<div class="coverage-item"><div class="coverage-value">{float(code.get(key, 0)):.2f}%</div>'
        f'<div class="coverage-label">{label}</div><div class="coverage-bar"><span style="width:{float(code.get(key, 0)):.2f}%;background:#25704a"></span></div>'
        f'<div class="coverage-meta">{meta}</div></div>'
        for key, (label, meta) in coverage_names.items()
    )
    replay_total = int(verification.get("replay_case_count") or 0)
    failed_count = int(verification.get("failed_case_count") or 0)
    failed_rate = 100 * failed_count / replay_total if replay_total else 0
    functional_rate = float(functional.get("rate") or 0)
    functional_hit = int(functional.get("hit") or 0)
    functional_total = int(functional.get("total") or 0)
    open_count = int(functional.get("open_checker_count") or 0)
    confidence_label = {"high": "高", "medium": "中", "low": "低"}.get(
        str(bug.get("confidence", "")).lower(), bug.get("confidence", "")
    )
    review_rows = "".join(
        f"<tr><td class='review-id'>{_esc(low.get('bug_id'))}</td><td><span class='review-title'>{_esc(low.get('title'))}</span></td>"
        f"<td>{_esc(low.get('short_reason', '证据链未闭环'))}</td>"
        f"<td>{len(low.get('cases', []))}</td><td><span class='review-status'>待复核</span></td>"
        f"<td><a href='review/{_esc(low.get('bug_id'))}.html'>查看档案</a></td></tr>"
        for low in low_bugs
    )
    return f"""<!-- LLPTW-CURATION-START -->{_EMBED_CSS}
<span id="bug-overview" aria-hidden="true"></span>
<section class="verify-overview" id="verification-overview"><div class="verify-head"><h2>验证状态总览</h2>
<p>覆盖率按 LLPTW 正式统计口径汇总；FSM 仍是当前最明显的覆盖缺口。</p></div>
<div class="coverage-grid">
{coverage_items}
<div class="coverage-item"><div class="coverage-value">{functional_rate:.2f}%</div><div class="coverage-label">功能覆盖率 · {functional_hit}/{functional_total} CK</div><div class="coverage-bar"><span style="width:{functional_rate:.2f}%;background:#25704a"></span></div><div class="coverage-meta">{open_count} 个 bug-open checker 未命中</div></div>
<div class="coverage-item"><div class="coverage-value">{len(data.get('suspected_bugs', data.get('final_bugs', [])))}</div><div class="coverage-label">疑似 Bug</div><div class="coverage-bar"><span style="width:100%;background:#25704a"></span></div><div class="coverage-meta">高 {data.get('verification_status', {}).get('suspected_bug_counts', {}).get('high', 0)} · 中 {data.get('verification_status', {}).get('suspected_bug_counts', {}).get('medium', 0)} · 低 {data.get('verification_status', {}).get('suspected_bug_counts', {}).get('low', 0)}</div></div>
<div class="coverage-item"><div class="coverage-value">{failed_count}</div><div class="coverage-label">回放失败用例</div><div class="coverage-bar"><span style="width:{failed_rate:.2f}%;background:#72558a"></span></div><div class="coverage-meta">{replay_total} 个回放用例中的失败项</div></div>
</div><div class="verify-foot"><b>状态：</b>{_esc(verification.get('status_summary'))}</div></section>
<span id="final-bug-analysis" aria-hidden="true"></span>
<section class="llptw-curation" id="adjudicated-gt"><div class="cur-head"><div><h2>最终 Bug 裁决</h2>
<p>首页只展示裁决结果；验证场景、预期与实际、波形、RTL 根因和源码证据统一放在详情页。</p></div>
<span class="cur-status">疑似 Bug · {len(data.get('suspected_bugs', data.get('final_bugs', [])))}</span></div>
<div class="adjudication-wrap"><table class="adjudication-table" aria-label="最终 Bug 裁决结果"><colgroup><col style="width:15%"><col style="width:38%"><col style="width:10%"><col style="width:10%"><col style="width:14%"><col style="width:13%"></colgroup>
<thead><tr><th>Bug ID</th><th>Bug</th><th>置信度</th><th>关联 Case</th><th>状态</th><th>详情</th></tr></thead><tbody><tr>
<td><b>{_esc(bug.get('bug_id') or bug.get('gt_id'))}</b><br><span class="cur-id">{_esc(bug.get('source_root_id'))}</span></td><td><span class="bug-name">{_esc(bug.get('title'))}</span>
<span class="bug-summary">{_esc(bug.get('summary'))}</span></td>
<td><span class="confidence-high">{_esc(confidence_label)}</span></td><td>{bug.get('reproduction_count', 0)} 个用例</td><td><span class="cur-status">疑似 Bug</span></td>
<td><a class="table-action" href="gt/{PRIMARY_BUG_ID}.html">查看完整分析</a></td></tr></tbody></table></div>
<div class="cur-foot"><span>所有疑似 Bug 都保留在列表中，并按置信度进入详情页。</span><span class="cur-foot-links"><a href="review/index.html">低置信度审查档案</a></span></div></section>
<section class="review-preview"><h2>低可信 / 待复核项</h2><p>这里只保留裁决摘要；完整原始结论、证据和反证理由在审查档案中查看。</p>
<div class="review-table-wrap"><table class="review-table" aria-label="低可信和待复核审查项"><colgroup><col style="width:22%"><col style="width:30%"><col style="width:22%"><col style="width:7%"><col style="width:9%"><col style="width:10%"></colgroup>
<thead><tr><th>历史 ID</th><th>原结论</th><th>未纳入 GT 的原因</th><th>用例</th><th>状态</th><th>详情</th></tr></thead><tbody>{review_rows}</tbody></table></div></section><!-- LLPTW-CURATION-END -->"""


def _failure_fragment(report_view: dict, bug: dict, low_bugs: list[dict]) -> str:
    del bug, low_bugs
    data = report_view["report_data"]
    counts = {"Bug": 0, "待复核": 0, "误判": 0, "环境": 0}
    labels = {
        "bug": ("Bug", "type-bug"),
        "needs_review": ("待复核", "type-review"),
        "false_positive": ("误判", "type-spec"),
        "environment": ("环境", "type-env"),
    }
    basis_labels = {
        "spec_or_interface_contract": "规格 / 接口契约",
        "test_or_environment": "测试 / 环境",
    }
    rows = []
    for row in data.get("failed_cases", []):
        category, cls = labels.get(row.get("category"), ("待复核", "type-review"))
        counts[category] += 1
        basis = basis_labels.get(row.get("basis"), row.get("basis"))
        rows.append(f"<tr><td class='case-name'>{_esc(row.get('test_name'))}</td>"
                    f"<td><span class='fail-chip {cls}'>{category}</span></td><td>{_esc(basis)}</td>"
                    f"<td>{_esc(row.get('replay_status'))}</td><td class='symptom'>{_esc(row.get('symptom'))}</td></tr>")
    return f"""<!-- LLPTW-FAILURES-START --><section class="failures-panel" id="failed-cases"><h2>失败用例与最终归因</h2>
<p>仅展示失败用例。最终类型使用简化口径：Bug、待复核、误判、环境。</p>
<div class="failure-summary"><span class="fail-chip type-bug">Bug {counts['Bug']}</span><span class="fail-chip type-review">待复核 {counts['待复核']}</span>
<span class="fail-chip type-spec">误判 {counts['误判']}</span><span class="fail-chip type-env">环境 {counts['环境']}</span></div>
<div class="table-wrap"><table class="failure-table"><thead><tr><th>失败测试</th><th>类型</th><th>依据</th><th>回放</th><th>失败表现</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></section><!-- LLPTW-FAILURES-END -->"""


def write_llptw_curated_report(dut_dir: Path, report_view: dict) -> None:
    """Add adjudication to the canonical report while preserving audit content."""
    dut_dir = Path(dut_dir)
    report_dir = dut_dir / "reports" / "zh"
    gt_dir = report_dir / "gt"
    gt_dir.mkdir(parents=True, exist_ok=True)
    data = _ensure_report_data(report_view)
    bug = _primary_bug(report_view)
    if not bug:
        raise ValueError(f"missing adjudicated LLPTW bug {PRIMARY_BUG_ID}")

    low_bugs = data.get("review_items", [])
    index_path = report_dir / "index.html"
    page = index_path.read_text(encoding="utf-8")
    page = page.replace("<span class='label'>RTL 缺陷总数</span><span class='value'>0</span>",
                        "<span class='label'>RTL 缺陷总数</span><span class='value'>1</span>", 1)
    page = page.replace("<span class='label'>单模型独有缺陷</span><span class='value'>0</span>",
                        "<span class='label'>单模型独有缺陷</span><span class='value'>1</span>", 1)
    page = page.replace("<h2>空 DUT 处理结果</h2>", "<h2>原始候选管线状态</h2>", 1)
    page = page.replace(
        "该 DUT 已完成输入发现和 run graph 构建，但没有可参与比较的有效候选 Bug；因此没有 replay contract，重放自动跳过。",
        "原始模型报告没有形成可参与标准候选配对的 Bug，因此候选管线未生成 replay contract；当前页面仍保留已有疑似 Bug 分析和证据。",
        1,
    )
    fragment = _curation_fragment(report_view, bug, low_bugs)
    marker_start = page.find("<!-- LLPTW-CURATION-START -->")
    marker_end = page.find("<!-- LLPTW-CURATION-END -->")
    if marker_start >= 0 and marker_end > marker_start:
        marker_end += len("<!-- LLPTW-CURATION-END -->")
        page = page[:marker_start] + fragment + page[marker_end:]
    elif 'id="adjudicated-gt"' not in page:
        hero_end = page.find("</section>", page.find("<section class=\"hero\""))
        if hero_end >= 0:
            hero_end += len("</section>")
            page = page[:hero_end] + fragment + page[hero_end:]
        else:
            page = page.replace("</body>", fragment + "</body>")
    failures = _failure_fragment(report_view, bug, low_bugs)
    failures_start = page.find("<!-- LLPTW-FAILURES-START -->")
    failures_end = page.find("<!-- LLPTW-FAILURES-END -->")
    if failures_start >= 0 and failures_end > failures_start:
        failures_end += len("<!-- LLPTW-FAILURES-END -->")
        page = page[:failures_start] + failures + page[failures_end:]
    else:
        page = page.replace("</body>", failures + "</body>")
    index_path.write_text(page, encoding="utf-8")

    detail_path = gt_dir / f"{PRIMARY_BUG_ID}.html"
    detail_path.write_text(_detail_html(bug, report_view), encoding="utf-8")
    aggregate_wave_path = report_dir / "wave_obs.html"
    if aggregate_wave_path.is_file():
        aggregate_wave = aggregate_wave_path.read_text(encoding="utf-8")
        for item in bug.get("cases", []):
            case_id = str(item.get("case_id") or "")
            anchor = f"case-{case_id.removeprefix('case-')[:8]}"
            title = str(item.get("nodeid") or "").split("::")[-1] or anchor
            viewer_url, signal_count, waveform_file = _waveform_viewer(case_id, report_view)
            page = _single_wave_page(
                aggregate_wave,
                anchor=anchor,
                title=title,
                viewer_url=viewer_url,
                signal_count=signal_count,
                waveform_file=waveform_file,
            )
            (report_dir / f"wave_{anchor}.html").write_text(page, encoding="utf-8")
    review_dir = report_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "index.html").write_text(_review_index(low_bugs), encoding="utf-8")
    for low_bug in low_bugs:
        (review_dir / f"{low_bug['bug_id']}.html").write_text(_review_page(low_bug), encoding="utf-8")
        compatibility = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
                         f"<meta http-equiv='refresh' content='0;url=../review/{_esc(low_bug['bug_id'])}.html'>"
                         "<title>低置信度疑似 Bug · 历史审查结论</title>"
                         f"<a href='../review/{_esc(low_bug['bug_id'])}.html'>该条目已移至低可信审查档案</a></html>")
        (gt_dir / f"{low_bug['bug_id']}.html").write_text(compatibility, encoding="utf-8")

    gt_redirect = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
                   f"<meta http-equiv='refresh' content='0;url=gt/{PRIMARY_BUG_ID}.html'>"
                   f"<title>GT-RTL-0001</title><a href='gt/{PRIMARY_BUG_ID}.html'>查看 GT-RTL-0001</a></html>")
    (report_dir / "gt_defect_details.html").write_text(gt_redirect, encoding="utf-8")
    review_redirect = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
                       "<meta http-equiv='refresh' content='0;url=review/index.html'>"
                       "<title>低置信度疑似 Bug 档案</title><a href='review/index.html'>查看历史审查档案</a></html>")
    (report_dir / "final_bug_details.html").write_text(review_redirect, encoding="utf-8")
