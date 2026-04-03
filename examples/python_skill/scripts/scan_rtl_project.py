#!/usr/bin/env python3
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


RTL_SUFFIXES = {'.v', '.sv'}
SCALA_SUFFIXES = {'.scala', '.sc'}
INSTANCE_KEYWORDS = {
    'if', 'for', 'while', 'case', 'assign', 'always', 'always_ff', 'always_comb',
    'always_latch', 'wire', 'logic', 'reg', 'input', 'output', 'inout', 'module',
    'endmodule', 'parameter', 'localparam', 'typedef', 'generate', 'genvar', 'else', 'end', 'begin',
}
INSTANCE_BLACKLIST_PREFIXES = ('end',)
MODULE_BLOCK_RE = re.compile(r'\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\b(.*?)\bendmodule\b', re.S)
INSTANCE_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_$]*)\s*(?:#\s*\([^;]*?\))?\s+([A-Za-z_][A-Za-z0-9_$]*)\s*\(', re.M)
PORT_LINE_RE = re.compile(r'^\s*(input|output|inout)\b(.*?);', re.M)
HEADER_PORT_RE = re.compile(r'^\s*(input|output|inout)\b(.*?)(?:,|$)', re.M)
CHISEL_CLASS_RE = re.compile(r'\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b.*?\bextends\s+([A-Za-z_][A-Za-z0-9_]*)', re.S)
IO_HINT_RE = re.compile(r'\bIO\s*\(')
CLOCK_HINT_RE = re.compile(r'\b(?:clock|clk)\b', re.I)
RESET_HINT_RE = re.compile(r'\b(?:reset|rst)(?:_n|n)?\b', re.I)
LINE_COMMENT_RE = re.compile(r'//.*?$', re.M)
BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.S)
TASK_BLOCK_RE = re.compile(r'\b(?:task|function)\b.*?\b(?:endtask|endfunction)\b', re.S | re.I)
INITIAL_HINT_RE = re.compile(r'\binitial\b', re.I)
SYSTEM_TASK_HINT_RE = re.compile(r'\$(?:display|monitor|finish(?:_and_return)?|stop|dumpfile|dumpvars|fatal|error|warning)\b', re.I)
TESTBENCH_NAME_RE = re.compile(r'(?:^tb$|^tb_|_tb$|^testbench$|^testbench_|_testbench$)', re.I)
TESTBENCH_PORT_RE = re.compile(r'(?:^drive_|^expected_|^stimulus_|^check_|^assert_)', re.I)
WRAPPER_NAME_RE = re.compile(r'(?:top|wrapper)$', re.I)
DUT_INSTANCE_NAMES = {'dut', 'uut', 'u_dut', 'i_dut'}


def strip_comments(text: str) -> str:
    text = BLOCK_COMMENT_RE.sub('', text)
    return LINE_COMMENT_RE.sub('', text)


def discover_files(project_root: Path):
    rtl_files = []
    scala_files = []
    for path in sorted(project_root.rglob('*')):
        if not path.is_file():
            continue
        if path.suffix in RTL_SUFFIXES:
            rtl_files.append(path)
        elif path.suffix in SCALA_SUFFIXES:
            scala_files.append(path)
    return rtl_files, scala_files


def normalize_signal_names(tail: str):
    ports = []
    clean = re.sub(r'\[[^\]]+\]', ' ', tail)
    clean = re.sub(r'\b(?:wire|logic|reg|signed|unsigned|var)\b', ' ', clean)
    for part in clean.split(','):
        token = part.strip()
        if not token:
            continue
        pieces = token.split()
        if not pieces:
            continue
        name = pieces[-1]
        if re.match(r'^[A-Za-z_][A-Za-z0-9_$]*$', name):
            ports.append(name)
    return ports


def parse_port_names(body: str):
    ports = []
    header, separator, remainder = body.partition(');')

    for _, tail in HEADER_PORT_RE.findall(header):
        ports.extend(normalize_signal_names(tail))
    if ports:
        return sorted(dict.fromkeys(ports))

    safe_remainder = TASK_BLOCK_RE.sub('', remainder if separator else body)
    for _, tail in PORT_LINE_RE.findall(safe_remainder):
        ports.extend(normalize_signal_names(tail))
    return sorted(dict.fromkeys(ports))


def summarize_testbench_hints(module_name: str, file_path: Path, ports, instances, body: str):
    hints = []
    if TESTBENCH_NAME_RE.search(module_name) or TESTBENCH_NAME_RE.search(file_path.stem):
        hints.append('name looks like a testbench')
    if INITIAL_HINT_RE.search(body):
        hints.append('contains an initial block')
    if SYSTEM_TASK_HINT_RE.search(body):
        hints.append('uses simulation-only system tasks')
    if any(instance['instance'].lower() in DUT_INSTANCE_NAMES for instance in instances):
        hints.append('instantiates a DUT/UUT-style instance name')
    if any(TESTBENCH_PORT_RE.search(port) for port in ports):
        hints.append('ports look like drive/expected testbench signals')
    return hints


def parse_verilog_file(path: Path):
    text = path.read_text(encoding='utf-8', errors='ignore')
    stripped = strip_comments(text)
    modules = []
    for module_name, body in MODULE_BLOCK_RE.findall(stripped):
        ports = parse_port_names(body)
        instances = []
        for child_module, instance_name in INSTANCE_RE.findall(body):
            if child_module in INSTANCE_KEYWORDS or child_module.startswith(INSTANCE_BLACKLIST_PREFIXES):
                continue
            if child_module == module_name:
                continue
            instances.append({'module': child_module, 'instance': instance_name})

        testbench_hints = summarize_testbench_hints(module_name, path, ports, instances, body)
        testbench_score = 0
        if 'name looks like a testbench' in testbench_hints:
            testbench_score += 2
        if 'contains an initial block' in testbench_hints and 'uses simulation-only system tasks' in testbench_hints:
            testbench_score += 2
        if 'instantiates a DUT/UUT-style instance name' in testbench_hints:
            testbench_score += 1
        if 'ports look like drive/expected testbench signals' in testbench_hints:
            testbench_score += 1

        modules.append({
            'name': module_name,
            'file': str(path),
            'ports': ports,
            'port_count': len(ports),
            'instances': instances,
            'has_clock_hint': any(CLOCK_HINT_RE.search(name) for name in ports),
            'has_reset_hint': any(RESET_HINT_RE.search(name) for name in ports),
            'is_wrapper_like': bool(WRAPPER_NAME_RE.search(module_name)),
            'is_testbench': testbench_score >= 2,
            'testbench_hints': testbench_hints,
            'has_initial_hint': bool(INITIAL_HINT_RE.search(body)),
            'has_system_task_hint': bool(SYSTEM_TASK_HINT_RE.search(body)),
        })
    return modules


def parse_scala_file(path: Path):
    text = path.read_text(encoding='utf-8', errors='ignore')
    stripped = strip_comments(text)
    classes = []
    for class_name, base_name in CHISEL_CLASS_RE.findall(stripped):
        if 'module' not in base_name.lower() and 'blackbox' not in base_name.lower():
            continue
        classes.append({
            'name': class_name,
            'base': base_name,
            'file': str(path),
            'has_io_hint': bool(IO_HINT_RE.search(stripped)),
            'has_clock_hint': bool(CLOCK_HINT_RE.search(stripped)),
            'has_reset_hint': bool(RESET_HINT_RE.search(stripped)),
        })
    return classes


def rank_top_candidates(modules, scala_classes):
    instantiated_by = defaultdict(set)
    for module in modules:
        for instance in module['instances']:
            instantiated_by[instance['module']].add(module['name'])

    scala_names = {item['name'] for item in scala_classes}
    candidates = []
    for module in modules:
        name = module['name']
        parents = sorted(instantiated_by.get(name, set()))
        score = 0
        reasons = []
        if not parents:
            score += 100
            reasons.append('module is not instantiated by any other discovered RTL module')
        if module.get('is_wrapper_like'):
            score += 30
            reasons.append('module name suggests a wrapper/top-level role')
        if Path(module['file']).stem == name:
            score += 15
            reasons.append('file stem matches module name')
        if module['port_count']:
            score += min(module['port_count'], 12)
            reasons.append(f"module exposes {module['port_count']} declared ports")
        if module['has_clock_hint']:
            score += 8
            reasons.append('ports include a clock-like signal')
        if module['has_reset_hint']:
            score += 6
            reasons.append('ports include a reset-like signal')
        if name in scala_names or any(Path(item['file']).stem == name for item in scala_classes):
            score += 20
            reasons.append('matching Chisel/Scala module-like class or file was found')
        if module.get('is_testbench'):
            score -= 140
            hint_text = '; '.join(module.get('testbench_hints') or []) or 'testbench-style heuristics matched'
            reasons.append(f'module looks like a simulation testbench ({hint_text})')

        candidates.append({
            'name': name,
            'file': module['file'],
            'score': score,
            'instantiated_by': parents,
            'reasoning': reasons or ['candidate kept as part of discovered module set'],
            'port_count': module['port_count'],
            'has_clock_hint': module['has_clock_hint'],
            'has_reset_hint': module['has_reset_hint'],
            'is_testbench': module.get('is_testbench', False),
            'testbench_hints': module.get('testbench_hints', []),
            'is_wrapper_like': module.get('is_wrapper_like', False),
        })

    if not candidates:
        return []

    return sorted(
        candidates,
        key=lambda item: (
            item['is_testbench'],
            -item['score'],
            len(item['instantiated_by']),
            item['name'],
        ),
    )


def build_summary(project_root: Path):
    rtl_files, scala_files = discover_files(project_root)
    modules = []
    for path in rtl_files:
        modules.extend(parse_verilog_file(path))

    scala_classes = []
    for path in scala_files:
        scala_classes.extend(parse_scala_file(path))

    top_candidates = rank_top_candidates(modules, scala_classes)
    recommended_top = top_candidates[0]['name'] if top_candidates else None

    instance_edges = []
    for module in modules:
        for instance in module['instances']:
            instance_edges.append({
                'parent_module': module['name'],
                'child_module': instance['module'],
                'instance_name': instance['instance'],
            })

    return {
        'project_root': str(project_root),
        'rtl_files': [str(path) for path in rtl_files],
        'scala_files': [str(path) for path in scala_files],
        'rtl_file_count': len(rtl_files),
        'scala_file_count': len(scala_files),
        'module_count': len(modules),
        'scala_module_like_count': len(scala_classes),
        'recommended_top_candidate': recommended_top,
        'default_top_candidate': recommended_top,
        'confirmed_top_candidate': None,
        'selection_required': bool(top_candidates),
        'top_candidates': top_candidates,
        'modules': modules,
        'instance_edges': instance_edges,
        'scala_module_hints': scala_classes,
        'analysis_notes': [
            'Top candidates are ranked heuristically from discovered Verilog/SystemVerilog structure plus Chisel intent hints.',
            'Simulation-only testbench patterns are down-ranked but still reported as candidates for review.',
            'Human confirmation is still required before any candidate becomes the execution truth.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description='Scan a mixed RTL project and emit structural evidence plus ranked top-level candidates.'
    )
    parser.add_argument('project_root', help='RTL project root to scan.')
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    if not project_root.exists():
        raise SystemExit(f'FAIL rtl scan: project root does not exist: {project_root}')

    summary = build_summary(project_root)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
