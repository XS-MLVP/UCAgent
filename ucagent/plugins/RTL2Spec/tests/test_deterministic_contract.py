"""Exercise objective artifact gates and permissive boundaries with real signed inputs."""

import json
import re

import pytest

from conftest import RTL, complete_review, draft
from rtl2spec.contracts import contract_rows
from rtl2spec.documents import artifact_paths, update_metadata
from rtl2spec.generic_evidence import generate_generic
from rtl2spec.review import finalize
from rtl2spec.validation import validate


@pytest.fixture
def current(tmp_path):
    """Create a valid document with actual captured RTL, then keep edits isolated."""
    source = tmp_path / 'inputs/Sbuffer'
    source.mkdir(parents=True)
    (source / 'top.sv').write_text(RTL)
    generate_generic(tmp_path, 'Sbuffer', 'Generic')
    draft(tmp_path)
    update_metadata(tmp_path, 'Sbuffer', 'Generic', generic=True)
    result = validate(tmp_path, 'Sbuffer', 'Generic', 'draft', generic=True)
    assert result['ok'], result
    return tmp_path


def set_cell(text, table, column, value, index=0):
    """Mutate one canonical cell without relying on unrelated prose or row formatting."""
    row = contract_rows(text)[table][index]
    lines = text.splitlines()
    cells = lines[row['line']-1].split('|')
    cells[column+1] = ' ' + value + ' '
    lines[row['line']-1] = '|'.join(cells)
    return '\n'.join(lines) + '\n'


@pytest.mark.parametrize('workflow', ['xiangshan', 'generic'])
@pytest.mark.parametrize('scaffold_state', ['missing', 'reformatted', 'different_facts'])
def test_port_scaffold_is_only_a_drafting_aid(request, workflow, scaffold_state):
    """A correct Appendix A can be reviewed and accepted without an exact helper file."""
    root = request.getfixturevalue('artifacts' if workflow == 'xiangshan' else 'current')
    generic = workflow == 'generic'
    config = 'Generic' if generic else 'DefaultConfig'
    scaffold = root / 'outputs/evidence/ports.md'
    if scaffold_state == 'missing':
        scaffold.unlink()
    elif scaffold_state == 'reformatted':
        scaffold.write_text(scaffold.read_text() + '\nExtra drafting notes.\n')
    else:
        scaffold.write_text('\n# Drafting notes\n\nExample port: fake_input, I/999.\n')
    complete_review(root, 'Sbuffer', config, generic=generic)
    result = validate(root, 'Sbuffer', config, 'review', generic=generic)
    assert result['ok'], result
    result = finalize(root, 'Sbuffer', config, generic=generic)
    assert result['ok'], result
    assert validate(root, 'Sbuffer', config, 'final', generic=generic)['ok']
    assert scaffold.exists() is (scaffold_state != 'missing')


@pytest.mark.parametrize('workflow', ['xiangshan', 'generic'])
def test_editing_scaffold_cannot_authorize_wrong_appendix_facts(request, workflow):
    """Appendix facts are checked against actual RTL regardless of helper-file content."""
    root = request.getfixturevalue('artifacts' if workflow == 'xiangshan' else 'current')
    generic = workflow == 'generic'
    config = 'Generic' if generic else 'DefaultConfig'
    design, _ = artifact_paths(root, 'Sbuffer')
    text = set_cell(design.read_text(), 'ports', 4, 'I/999')
    design.write_text(text)
    (root / 'outputs/evidence/ports.md').write_text(text)
    complete_review(root, 'Sbuffer', config, generic=generic)
    result = finalize(root, 'Sbuffer', config, generic=generic)
    assert not result['ok'], result
    assert 'direction/width' in result['error'], result


@pytest.mark.parametrize('table,column,value,rule', [
    ('plan',6,'','TABLE_FIELDS'),
    ('plan',0,'P9','PLAN_FIELDS'),
    ('ports',7,'TODO','PLACEHOLDER'),
    ('ports',1,'undefined.bus','INTERFACE_UNDEFINED'),
    ('ports',5,'Elided','PORT_STATE'),
    ('ports',3,'outputs/evidence/Sbuffer.sv:99999','PORT_LOCATION'),
    ('ports',3,'outputs/evidence/Sbuffer.sv:8','PORT_LOCATION'),
    ('evidence',2,'outputs/evidence/Sbuffer.sv:99999','SOURCE_LOCATION'),
    ('evidence',2,'outputs/evidence/Sbuffer.sv:8-2','SOURCE_LOCATION'),
    ('evidence',2,'inputs/Sbuffer/unregistered.sv:1','SOURCE_LOCATION'),
    ('evidence',2,'no location','EVIDENCE_LOCATION'),
    ('plan',8,'COV-NORMAL / CASE-MISSING','ID_UNDEFINED'),
    ('ck_trace',1,'FC-RECOVERY','CK_TRACE'),
    ('ck_trace',5,'CASE-BOUNDARY','CK_TRACE'),
    ('ck_trace',6,'COV-BOUNDARY','CK_TRACE'),
    ('fc_trace',1,'FG-RECOVERY','FC_TRACE'),
    ('fc_trace',4,'2','FC_TRACE_ROWS'),
    ('coverage',8,'Covered','STATUS_VALUE'),
    ('properties',4,'Proved','STATUS_VALUE'),
    ('properties',5,'Closed','SIGNOFF_EVIDENCE'),
    ('properties',1,'Proof','PROPERTY_TYPE'),
    ('properties',4,'Implemented','PROPERTY_TRACE'),
    ('signoff',1,'Pass','SIGNOFF_EVIDENCE'),
])
def test_machine_fields_reject_invalid_values(current, table, column, value, rule):
    """Each failure reports the precise artifact, line and repairable contract rule."""
    design, _ = artifact_paths(current, 'Sbuffer')
    index = 2 if table == 'signoff' else 0
    design.write_text(set_cell(design.read_text(), table, column, value, index))
    result = validate(current, 'Sbuffer', 'Generic', 'draft', generic=True)
    assert not result['ok'], result
    assert any(e.get('rule') == rule for e in result['observed']), result
    assert result['artifact'] and result['next_action']
    assert all(e.get('line', 1) >= 1 for e in result['observed'])


@pytest.mark.parametrize('mutation,rule', [
    ('missing_behavior_fields','BEHAVIOR_FIELD'), ('bare_inapplicability','BEHAVIOR_FIELD'),
    ('placeholder','PLACEHOLDER'), ('renamed_header','TABLE_HEADER'),
    ('duplicate_evidence','ID_DUPLICATE'), ('duplicate_coverage','ID_DUPLICATE'),
    ('missing_open','ID_UNDEFINED'), ('fake_definition_in_note','ID_UNDEFINED'),
    ('extra_cell','TABLE_FIELDS'), ('empty_cell','TABLE_FIELDS'),
    ('duplicate_logical','INTERFACE_DUPLICATE'), ('report_claim','SIGNOFF_EVIDENCE'),
    ('report_mismatch','REPORT_STATUS'),
])
def test_structural_defects_cannot_be_signed(current, mutation, rule):
    """A freshly prepared semantic review cannot launder deterministic document defects."""
    design, report = artifact_paths(current, 'Sbuffer')
    text = design.read_text()
    original = text
    if mutation == 'missing_behavior_fields':
        text = re.sub(r'(### P-FORWARD[^\n]*\n).*?(?=\n## 验证策略)', r'\1\n', text, flags=re.S)
    elif mutation == 'bare_inapplicability':
        text = re.sub(r'\*\*处理过程\*\*[^\n]+', '**处理过程**：N/A', text)
    elif mutation == 'placeholder':
        text = re.sub(r'\*\*处理过程\*\*[^\n]+', '**处理过程**：[输入有效条件、资源条件、控制条件和前置状态。]', text)
    elif mutation == 'renamed_header':
        text = text.replace('| 优先级 | FC | CK | Style |', '| Other | FC | CK | Style |')
    elif mutation.startswith('duplicate_'):
        key = {'duplicate_evidence':'evidence', 'duplicate_coverage':'coverage', 'duplicate_logical':'interfaces'}[mutation]
        row = contract_rows(text)[key][0]
        lines = text.splitlines()
        lines.insert(row['line'], lines[row['line']-1])
        text = '\n'.join(lines)+'\n'
    elif mutation == 'missing_open':
        row = contract_rows(text)['open'][0]
        lines = text.splitlines()
        del lines[row['line']-1]
        text = '\n'.join(lines)+'\n'
    elif mutation == 'fake_definition_in_note':
        text += '\n- CK-NOTE: mentions cannot define checks outside Testplan.\n'
    elif mutation in {'extra_cell','empty_cell'}:
        row = contract_rows(text)['plan'][0]
        lines = text.splitlines()
        lines[row['line']-1] += ' extra |' if mutation == 'extra_cell' else ''
        text = '\n'.join(lines)+'\n' if mutation == 'extra_cell' else set_cell(text,'plan',7,'')
    elif mutation == 'report_claim':
        report.write_text(report.read_text()+'\n| Item | Status | Evidence |\n| --- | --- | --- |\n| Formal / assertion | Pass | An authored claim |\n')
    elif mutation == 'report_mismatch':
        report.write_text(report.read_text()+'\n| Item | Status | Evidence |\n| --- | --- | --- |\n| Testplan | Pass | An authored claim |\n')
    assert text != original or mutation.startswith('report_')
    design.write_text(text)
    complete_review(current, 'Sbuffer', 'Generic', generic=True)
    result = finalize(current, 'Sbuffer', 'Generic', generic=True)
    assert not result['ok'], result
    assert any(e.get('rule') == rule for e in result['observed']), result
    assert not (current / 'outputs/validation.json').exists()


def test_reasoned_inapplicability_and_empty_open_table_are_valid(current):
    """Do not invent open problems or disallow prose explanations for absent features."""
    design, _ = artifact_paths(current, 'Sbuffer')
    text = re.sub(r'\*\*配置裁剪\*\*[^\n]+', '**配置裁剪**：不适用：该模块没有参数或条件编译分支。', design.read_text())
    lines = [line for line in text.splitlines() if not line.startswith('| `OPEN-FORMAL-01` |')]
    text = '\n'.join(lines).replace('OPEN-FORMAL-01','未运行，无本次待关闭问题')
    design.write_text(text)
    result = validate(current, 'Sbuffer', 'Generic', 'draft', generic=True)
    assert result['ok'], result


def test_shared_logical_mapping_and_extra_prose_tables_are_valid(current):
    """Port grouping is many-to-one and unrelated prose tables remain extensible."""
    design, _ = artifact_paths(current, 'Sbuffer')
    text = set_cell(design.read_text(), 'ports', 1, 'control.reset', 0)
    text += '\n| Note | Value |\n| --- | --- |\n| HDL expression | `data[7:0]` and `a \\| b` |\n'
    design.write_text(text)
    result = validate(current, 'Sbuffer', 'Generic', 'draft', generic=True)
    assert result['ok'], result


def test_many_to_many_checks_and_source_range_formats_are_valid(current):
    """Allow shared checks, scenarios and coverage without requiring one-to-one mappings."""
    design, _ = artifact_paths(current, 'Sbuffer')
    text = design.read_text().replace('## 验证策略与 Testplan', '''### P-SECOND：共同转发约束

**激励条件**：已知输入稳定。

**处理过程**：沿用组合转发路径。

**输出与状态结果**：输出与输入一致。

**时延与顺序**：组合传播稳定后采样。

**边界与恢复**：无状态，无恢复事务。

**配置裁剪**：不适用：没有运行时配置。

**证据**：E-RTL-01。

## 验证策略与 Testplan''')
    text = set_cell(text, 'plan', 4, 'P-FORWARD, P-SECOND', 1)
    text = set_cell(text, 'fc_trace', 3, 'P-FORWARD, P-SECOND', 1)
    text = set_cell(text, 'plan', 8, 'COV-NORMAL, COV-BOUNDARY / CASE-NORMAL, CASE-BOUNDARY', 1)
    text = set_cell(text, 'ck_trace', 5, 'CASE-NORMAL, CASE-BOUNDARY', 1)
    text = set_cell(text, 'ck_trace', 6, 'COV-NORMAL, COV-BOUNDARY', 1)
    text = set_cell(text, 'ports', 3, '[declaration](evidence/Sbuffer.sv#L3-L4)', 0)
    text = set_cell(text, 'evidence', 2, '`outputs/evidence/Sbuffer.sv:2-8`')
    design.write_text(text)
    result = validate(current, 'Sbuffer', 'Generic', 'draft', generic=True)
    assert result['ok'], result


def test_review_requires_current_behavior_plan_links(current):
    """An existing but unrelated coverage ID cannot satisfy the selected behavior plan."""
    complete_review(current, 'Sbuffer', 'Generic', generic=True)
    path = current/'outputs/semantic_review.json'
    value = json.loads(path.read_text())
    value['behaviors'][0]['checks']['verification_plan']['coverage_ids'] = ['COV-RECOVERY']
    path.write_text(json.dumps(value))
    result = validate(current, 'Sbuffer', 'Generic', 'review', generic=True)
    assert not result['ok'] and 'selected Testplan' in result['error'], result


def test_review_pass_and_closed_document_issue_do_not_claim_execution(current):
    """Names containing formal/coverage do not turn document reviews into tool execution."""
    design, report = artifact_paths(current, 'Sbuffer')
    text = design.read_text()
    row = contract_rows(text)['open'][0]
    lines = text.splitlines()
    lines.insert(row['line'], '| OPEN-FORMAL-TEXT | Corrected the written assumption | Documentation | Reviewed against current source | Closed |')
    design.write_text('\n'.join(lines)+'\n')
    report.write_text(report.read_text()+'\n| Item | Status | Evidence |\n| --- | --- | --- |\n| Formal plan review | Pass | Reviewed text, no proof execution |\n')
    result = validate(current, 'Sbuffer', 'Generic', 'draft', generic=True)
    assert result['ok'], result


def test_multiple_fc_owners_are_valid_when_all_tables_agree(current):
    """One CK and scenario may cover multiple functional groups without a one-owner rule."""
    design, _ = artifact_paths(current, 'Sbuffer')
    text = set_cell(design.read_text(), 'plan', 1, 'FC-INPUT-CONTRACT, FC-BEHAVIOR', 1)
    text = set_cell(text, 'ck_trace', 1, 'FC-INPUT-CONTRACT, FC-BEHAVIOR', 1)
    text = set_cell(text, 'fc_trace', 4, '1-2', 0)
    text = text.replace('`FC-BEHAVIOR`, `CK-EVENT-RESULT` |', '`FC-INPUT-CONTRACT`, `FC-BEHAVIOR`, `CK-API-INPUT`, `CK-EVENT-RESULT` |')
    design.write_text(text)
    assert validate(current, 'Sbuffer', 'Generic', 'draft', generic=True)['ok']


def test_equivalent_original_and_preprocessed_port_locations(current):
    """Both source-map origins and captured preprocessing views can locate the same port."""
    design, _ = artifact_paths(current, 'Sbuffer')
    for value in ['`inputs/Sbuffer/top.sv:3`', '`outputs/evidence/Sbuffer.preprocessed.sv:3`',
                  '`inputs/Sbuffer/top.sv:3` / `outputs/evidence/Sbuffer.sv:3`']:
        design.write_text(set_cell(design.read_text(), 'ports', 3, value, 0))
        result = validate(current, 'Sbuffer', 'Generic', 'draft', generic=True)
        assert result['ok'], result


def test_absent_verification_modes_allow_explained_not_applicable(current):
    """Inapplicable modes need no fake execution receipts or manufactured results."""
    design, _ = artifact_paths(current, 'Sbuffer')
    text = set_cell(design.read_text(), 'signoff', 1, 'NotApplicable', 2)
    text = set_cell(text, 'signoff', 2, 'Only documentation is in scope; no formal harness is requested', 2)
    design.write_text(text)
    assert validate(current, 'Sbuffer', 'Generic', 'draft', generic=True)['ok']


def test_empty_parameter_state_and_optional_scenario_tables(current):
    """No fictitious parameter, FSM or extra scenario is needed for a simple module."""
    design, _ = artifact_paths(current, 'Sbuffer')
    text = design.read_text()
    for table in ['parameters','states']:
        for row in reversed(contract_rows(text)[table]):
            lines = text.splitlines()
            del lines[row['line']-1]
            text = '\n'.join(lines)+'\n'
    text = text.split('### CASE-EXTRA', 1)[0]
    design.write_text(text)
    update_metadata(current, 'Sbuffer', 'Generic', generic=True)
    result = validate(current, 'Sbuffer', 'Generic', 'draft', generic=True)
    assert result['ok'], result


def test_non_ansi_declaration_locations_and_inactive_branches(tmp_path):
    """Accept classic body declarations but never use an inactive branch as a port origin."""
    from rtl2spec.documents import port_locations
    from rtl2spec.generic_evidence import validate_generic_evidence

    source = tmp_path/'inputs/Block'
    source.mkdir(parents=True)
    (source/'top.v').write_text('module Block(a);\n`ifdef OTHER\ninput [3:0] a;\n`else\ninput [7:0] a;\n`endif\nendmodule\n')
    generate_generic(tmp_path,'Block','Generic')
    _, ports = validate_generic_evidence(tmp_path,'Block','Generic')
    locations = port_locations(tmp_path,'Block',ports,generic=True)['a']
    assert ('inputs/Block/top.v',1) in locations
    assert ('inputs/Block/top.v',5) in locations
    assert ('outputs/evidence/Block.sv',5) in locations
    assert ('inputs/Block/top.v',3) not in locations
    assert ('outputs/evidence/Block.sv',3) not in locations


@pytest.mark.parametrize('value', ['N/A.', '不适用。', '无。', '—'])
def test_punctuation_is_not_an_inapplicability_reason(current, value):
    """A sentence terminator cannot turn a bare missing-content label into an explanation."""
    design, _ = artifact_paths(current, 'Sbuffer')
    text = re.sub(r'\*\*配置裁剪\*\*[^\n]+', '**配置裁剪**：'+value, design.read_text())
    design.write_text(text)
    result = validate(current,'Sbuffer','Generic','draft',generic=True)
    assert not result['ok'] and any(e.get('rule') == 'BEHAVIOR_FIELD' for e in result['observed'])


def test_missing_signoff_activity_and_wrong_document_state_fail(current):
    """Required status items cannot be hidden by deleting the row or contradicting control."""
    design, _ = artifact_paths(current, 'Sbuffer')
    original = design.read_text()
    row = contract_rows(original)['signoff'][2]
    lines = original.splitlines()
    del lines[row['line']-1]
    design.write_text('\n'.join(lines)+'\n')
    result = validate(current,'Sbuffer','Generic','draft',generic=True)
    assert not result['ok'] and any(e.get('rule') == 'SIGNOFF_FIELDS' for e in result['observed'])
    design.write_text(original.replace('| 文档状态 | Draft |','| 文档状态 | Frozen |'))
    result = validate(current,'Sbuffer','Generic','draft',generic=True)
    assert not result['ok'] and any(e.get('rule') == 'DOCUMENT_STATE' for e in result['observed'])


def test_closed_open_item_cannot_back_an_open_review(current):
    """Review records must refer to a currently unresolved entry in the canonical table."""
    design, _ = artifact_paths(current,'Sbuffer')
    design.write_text(set_cell(design.read_text(),'open',4,'Closed'))
    complete_review(current,'Sbuffer','Generic',generic=True)
    path=current/'outputs/semantic_review.json'
    value=json.loads(path.read_text())
    value['behaviors'][0]['checks']['assumptions'].update(status='open',open_id='OPEN-FORMAL-01')
    path.write_text(json.dumps(value))
    result=validate(current,'Sbuffer','Generic','review',generic=True)
    assert not result['ok'] and 'Open/Deferred' in result['error']


@pytest.mark.parametrize('defect,rule', [('behavior_id','ID_FORMAT'),('change_id','ID_DUPLICATE')])
def test_malformed_identity_has_a_bounded_diagnostic(current, defect, rule):
    """Invalid behavior IDs and repeated change IDs produce contract errors, not parser crashes."""
    design, _ = artifact_paths(current,'Sbuffer')
    text=design.read_text()
    if defect == 'behavior_id':
        text=text.replace('### P-FORWARD','### P-invalid')
    else:
        row=contract_rows(text)['changes'][0]
        lines=text.splitlines()
        lines.insert(row['line'],lines[row['line']-1])
        text='\n'.join(lines)+'\n'
    design.write_text(text)
    result=validate(current,'Sbuffer','Generic','draft',generic=True)
    assert not result['ok'] and any(e.get('rule')==rule for e in result['observed']), result
    assert len(result['observed'])<=12
