"""Download complete upstream documentation snapshots for offline Bug Review."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

SOURCES = [
    {'id': 'riscv', 'family': 'riscv', 'title': 'RISC-V Instruction Set Manual',
     'repository': 'https://github.com/riscv/riscv-isa-manual.git', 'branch': 'main',
     'paths': None, 'submodules': True,
     'entry_points': ['src/riscv-spec.adoc', 'src/priv/supervisor.adoc', 'src/priv/hypervisor.adoc', 'src/priv/machine.adoc'],
     'applicability': 'Latest main includes ratified chapters and drafts. Use chapter status/version and the DUT supported extensions; a draft is not automatically adopted.'},
    {'id': 'xiangshan-kunminghu-v2r2a', 'family': 'xiangshan', 'title': 'XiangShan Design Documentation (kunminghu-v2r2a)',
     'repository': 'https://github.com/OpenXiangShan/XiangShan-Design-Doc.git', 'branch': 'kunminghu-v2r2a',
     'paths': ['docs', 'LICENSE', 'README.md', 'README.zh.md', 'mkdocs.yml', 'mkdocs-zh.yml', 'mkdocs-en.yml'],
     'entry_points': ['docs/zh', 'docs/zh/memblock/MMU/L1TLB.md', 'docs/zh/memblock/MMU/Repeater.md'],
     'applicability': 'Complete documentation tree, both languages and figures. Apply only to matching design generation, ports and parameters.'},
    {'id': 'xiangshan-kunminghu-v3', 'family': 'xiangshan', 'title': 'XiangShan Design Documentation (kunminghu-v3)',
     'repository': 'https://github.com/OpenXiangShan/XiangShan-Design-Doc.git', 'branch': 'kunminghu-v3',
     'paths': ['docs', 'LICENSE', 'README.md', 'README.zh.md', 'mkdocs.yml', 'mkdocs-zh.yml', 'mkdocs-en.yml'],
     'entry_points': ['docs/zh', 'docs/zh/memblock/MMU/L1TLB.md'],
     'applicability': 'Complete documentation tree, both languages and figures. Do not combine its nonblocking interfaces with another generation blocking interface.'},
    {'id': 'xiangshan-verification', 'family': 'xiangshan', 'title': 'UnityChipForXiangShan Verification Documentation',
     'repository': 'https://github.com/XS-MLVP/UnityChipForXiangShan.git', 'branch': 'main',
     'paths': ['documents', 'LICENSE', 'README.en.md', 'README.zh.md'], 'license_path': 'documents/LICENSE',
     'entry_points': ['documents/content', 'documents/content/zh-cn/docs/98_ut/01_frontend/02_itlb/02_func.md'],
     'applicability': 'Complete verification documentation tree and assets, including blocking ITLB behavior. Check target generation and reconcile with matching design documentation.'},
    {'id': 'chisel', 'family': 'chisel', 'title': 'Chisel Documentation',
     'repository': 'https://github.com/chipsalliance/chisel.git', 'branch': 'main',
     'paths': ['docs', 'docs-target', 'website', 'LICENSE', 'README.md'],
     'entry_points': ['docs', 'website'],
     'applicability': 'Complete documentation/website source trees, including figures and examples. Match the DUT Chisel version and actual DecoupledIO/IrrevocableIO interface type.'},
]


def download(destination, cache=None):
    """Fetch current branch tips and publish complete, attributed local source trees."""
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bug-review-standards-') as temporary:
        temporary = Path(temporary)
        output = temporary / 'references'; output.mkdir()
        retrieved = datetime.now(timezone.utc).isoformat()
        catalog = {'schema': 'bug_review_standards.v1', 'retrieved_at': retrieved, 'sources': []}
        for source in SOURCES:
            checkout = (Path(cache) if cache else temporary / 'checkouts') / source['id']
            checkout.parent.mkdir(parents=True, exist_ok=True)
            if not checkout.exists():
                subprocess.run(['git', 'clone', '--depth', '1', '--branch', source['branch'], source['repository'], str(checkout)], check=True)
            else:
                origin = subprocess.check_output(['git', '-C', str(checkout), 'remote', 'get-url', 'origin'], text=True).strip()
                if origin != source['repository']:
                    raise ValueError(f'checkout origin does not match source: {checkout}')
                subprocess.run(['git', '-C', str(checkout), 'fetch', '--depth', '1', 'origin', source['branch']], check=True)
                subprocess.run(['git', '-C', str(checkout), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
            if source.get('submodules'):
                subprocess.run(['git', '-C', str(checkout), 'submodule', 'update', '--init', '--recursive', '--depth', '1'], check=True)
            dirty = subprocess.check_output(['git', '-C', str(checkout), 'status', '--porcelain', '--untracked-files=all'], text=True).strip()
            if dirty:
                raise ValueError(f'dedicated documentation cache contains local changes; use a new clean cache: {checkout}')
            revision = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
            commit_time = subprocess.check_output(['git', '-C', str(checkout), 'log', '-1', '--format=%cI'], text=True).strip()
            target = output / source['id']; target.mkdir()
            selected = source['paths'] or [p.name for p in checkout.iterdir() if p.name != '.git']
            for name in selected:
                path = checkout / name
                if not path.exists():
                    raise ValueError(f'upstream documentation path missing: {source["id"]}/{name}')
                if path.is_dir():
                    shutil.copytree(path, target / name, ignore=shutil.ignore_patterns('.git', '__pycache__'))
                else:
                    shutil.copy2(path, target / name)
            for entry in source['entry_points']:
                if not (target / entry).exists():
                    raise ValueError(f'upstream entry point missing: {source["id"]}/{entry}')
            submodules = subprocess.check_output(['git', '-C', str(checkout), 'submodule', 'status', '--recursive'], text=True).splitlines() if source.get('submodules') else []
            catalog['sources'].append({key: value for key, value in source.items() if key not in {'paths', 'submodules'}} | {
                'revision': revision, 'commit_time': commit_time, 'retrieved_at': retrieved,
                'snapshot': source['id'], 'license': source['id'] + '/' + source.get('license_path', 'LICENSE'),
                'entry_points': [source['id'] + '/' + entry for entry in source['entry_points']],
                'file_count': sum(p.is_file() for p in target.rglob('*')),
                'submodule_revisions': submodules, 'content': 'Unmodified upstream documentation sources and assets; Git metadata excluded.'})
        (output / 'catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # Fetch every source before replacing the current library. Failed downloads
        # do not leave a partial normative library in a future review workspace.
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(output, destination)
    return catalog


def main():
    """Explicitly refresh snapshots; review startup and Check stay offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'src/bug_review/references')
    parser.add_argument('--cache', type=Path, help='Optional dedicated Git checkout cache; fetches latest branch tips on each refresh.')
    args = parser.parse_args()
    catalog = download(args.output, args.cache)
    print(json.dumps({'sources': [(s['id'], s['revision'], s['file_count']) for s in catalog['sources']], 'output': str(args.output)}))


if __name__ == '__main__':
    main()
