"""Observation-contract gates and instrumentation validation."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from ucagent.checkers.base import Checker
import ucagent.util.functions as uc_functions
from ..contracts import (
    load_fenced_yaml,
    load_yaml,
    resolve_workspace_path,
)

from .common import (
    _DEFAULT_FUNCTIONAL_CK_EXCLUDE_PREFIXES,
    _PYTHON_IDENTIFIER_RE,
    _checkpoint_prefixes,
    _exception_contract_diagnostic,
    _functional_checkpoints,
)
from .coverage_model import (
    _coverage_public_attributes,
)


_OBSERVATION_SOURCES = {
    "public_input",
    "public_output",
    "transaction_identity",
    "cycle_state",
    "derived_public_value",
}


_OBSERVATION_CAPTURES = {
    "api_validation",
    "after_refresh",
    "after_step",
    "transaction_accept",
    "transaction_observation",
    "response",
}


_OBSERVATION_CYCLE_ATTRIBUTE = "cycle"




def _load_observation_contract(
    workspace: Path,
    contract_file: str,
    doc_file: str,
    ignored_prefixes: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Load one complete backend-neutral observation contract for all functional CKs."""

    payload = load_yaml(resolve_workspace_path(workspace, contract_file, must_exist=True))
    contract = payload.get("observation_contract") if isinstance(payload, dict) else None
    if not isinstance(contract, dict):
        raise ValueError("observation_contract must be a mapping")
    if contract.get("schema_version") != "1.0":
        raise ValueError("observation_contract.schema_version must be 1.0")
    events = contract.get("events")
    checkpoints = contract.get("checkpoints")
    if not isinstance(events, list) or not isinstance(checkpoints, list):
        raise ValueError("observation_contract events and checkpoints must be lists")

    event_map: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"observation_contract.events[{index}] must be a mapping")
        name = event.get("name")
        capture = event.get("capture")
        fields = event.get("fields")
        if not isinstance(name, str) or not _PYTHON_IDENTIFIER_RE.fullmatch(name):
            raise ValueError(f"observation_contract.events[{index}].name is invalid")
        if name in event_map:
            raise ValueError(f"duplicate observation event: {name}")
        if capture not in _OBSERVATION_CAPTURES:
            raise ValueError(
                f"observation event {name}.capture must be one of "
                f"{sorted(_OBSERVATION_CAPTURES)}"
            )
        if not isinstance(fields, list) or not fields:
            raise ValueError(f"observation event {name}.fields must be a non-empty list")
        field_names: set[str] = set()
        for field_index, field in enumerate(fields):
            if not isinstance(field, dict):
                raise ValueError(
                    f"observation event {name}.fields[{field_index}] must be a mapping"
                )
            field_name = field.get("name")
            source = field.get("source")
            source_refs = field.get("source_refs")
            description = field.get("description")
            if (
                not isinstance(field_name, str)
                or not _PYTHON_IDENTIFIER_RE.fullmatch(field_name)
            ):
                raise ValueError(
                    f"observation event {name}.fields[{field_index}].name is invalid"
                )
            if field_name in field_names:
                raise ValueError(f"observation event {name} repeats field {field_name}")
            if source not in _OBSERVATION_SOURCES:
                raise ValueError(
                    f"observation event {name}.{field_name}.source must be one of "
                    f"{sorted(_OBSERVATION_SOURCES)}"
                )
            if (
                not isinstance(source_refs, list)
                or not source_refs
                or any(
                    not isinstance(value, str)
                    or not _PYTHON_IDENTIFIER_RE.fullmatch(value)
                    for value in source_refs
                )
                or len(set(source_refs)) != len(source_refs)
            ):
                raise ValueError(
                    f"observation event {name}.{field_name}.source_refs must contain "
                    "unique public identifiers"
                )
            if not isinstance(description, str) or not description.strip():
                raise ValueError(
                    f"observation event {name}.{field_name}.description must be non-empty"
                )
            field_names.add(field_name)
        event_map[name] = {**event, "field_names": field_names}

    documented = _functional_checkpoints(
        uc_functions.get_unity_chip_doc_marks(
            str(resolve_workspace_path(workspace, doc_file, must_exist=True)), "CK", 1
        ),
        ignored_prefixes,
    )
    if not documented:
        raise ValueError("the design contract contains no functional CK paths")
    checkpoint_map: dict[str, dict[str, Any]] = {}
    for index, checkpoint in enumerate(checkpoints):
        if not isinstance(checkpoint, dict):
            raise ValueError(
                f"observation_contract.checkpoints[{index}] must be a mapping"
            )
        checkpoint_id = checkpoint.get("id")
        observation = checkpoint.get("observation")
        event_name = checkpoint.get("event")
        fields = checkpoint.get("fields")
        predicate_intent = checkpoint.get("predicate_intent")
        if not isinstance(checkpoint_id, str) or checkpoint_id not in documented:
            raise ValueError(
                f"observation_contract.checkpoints[{index}].id is not a functional CK path"
            )
        if checkpoint_id in checkpoint_map:
            raise ValueError(f"duplicate observation checkpoint: {checkpoint_id}")
        if observation not in {"pins", "event"}:
            raise ValueError(
                f"observation checkpoint {checkpoint_id}.observation must be pins or event"
            )
        if (
            not isinstance(fields, list)
            or not fields
            or any(
                not isinstance(field, str)
                or not _PYTHON_IDENTIFIER_RE.fullmatch(field)
                for field in fields
            )
            or len(set(fields)) != len(fields)
        ):
            raise ValueError(
                f"observation checkpoint {checkpoint_id}.fields must contain unique identifiers"
            )
        if not isinstance(predicate_intent, str) or not predicate_intent.strip():
            raise ValueError(
                f"observation checkpoint {checkpoint_id}.predicate_intent must be non-empty"
            )
        if observation == "pins":
            if event_name is not None:
                raise ValueError(
                    f"pin observation checkpoint {checkpoint_id}.event must be null"
                )
        else:
            if not isinstance(event_name, str) or event_name not in event_map:
                raise ValueError(
                    f"event observation checkpoint {checkpoint_id} references an unknown event"
                )
            unknown_fields = sorted(set(fields) - event_map[event_name]["field_names"])
            if unknown_fields:
                raise ValueError(
                    f"observation checkpoint {checkpoint_id} references undeclared event "
                    f"fields: {unknown_fields}"
                )
        checkpoint_map[checkpoint_id] = checkpoint
    missing = sorted(set(documented) - set(checkpoint_map))
    extra = sorted(set(checkpoint_map) - set(documented))
    if missing or extra:
        raise ValueError(
            "observation checkpoint set differs from the functional contract: "
            f"missing={missing[:20]}, extra={extra[:20]}"
        )
    return contract, event_map, checkpoints




def _validate_observation_source_refs(
    workspace: Path,
    architecture_file: str,
    event_map: dict[str, dict[str, Any]],
    public_attributes: set[str] | None = None,
) -> None:
    """Bind every event field source to declared public pins or cycle state."""

    architecture = load_fenced_yaml(
        resolve_workspace_path(workspace, architecture_file, must_exist=True),
        "architecture",
    )
    port_directions = {
        row.get("name"): row.get("direction")
        for row in architecture.get("ports", [])
        if isinstance(row, dict)
        and isinstance(row.get("name"), str)
        and row.get("direction") in {"input", "output", "inout"}
    }
    if not port_directions:
        raise ValueError("architecture contains no public ports for observation sources")
    for event_name, event in event_map.items():
        for field in event["fields"]:
            field_name = field["name"]
            source = field["source"]
            source_refs = field["source_refs"]
            if source in {"public_input", "transaction_identity"}:
                invalid = [
                    value
                    for value in source_refs
                    if port_directions.get(value) != "input"
                ]
            elif source == "public_output":
                invalid = [
                    value
                    for value in source_refs
                    if port_directions.get(value) not in {"output", "inout"}
                ]
            elif source == "derived_public_value":
                invalid = [
                    value for value in source_refs if value not in port_directions
                ]
            else:
                invalid = (
                    []
                    if source_refs == [_OBSERVATION_CYCLE_ATTRIBUTE]
                    and (
                        public_attributes is None
                        or _OBSERVATION_CYCLE_ATTRIBUTE in public_attributes
                    )
                    else list(source_refs)
                )
            if invalid:
                raise ValueError(
                    f"observation event {event_name}.{field_name}.source_refs do not "
                    f"match {source}: {invalid[:10]}"
                )




class DesignObservationContractChecker(Checker):
    """Require one explicit backend-neutral observation plan for every functional CK."""

    def __init__(
        self,
        contract_file: str,
        doc_file: str,
        architecture_file: str,
        ignore_ck_prefix: str | list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Store observation and functional-contract paths without scanning the workspace."""

        super().__init__()
        del kwargs
        self.contract_file = contract_file
        self.doc_file = doc_file
        self.architecture_file = architecture_file
        self.ignore_ck_prefix = _checkpoint_prefixes(
            _DEFAULT_FUNCTIONAL_CK_EXCLUDE_PREFIXES
            if ignore_ck_prefix is None
            else ignore_ck_prefix
        )

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Validate the complete event/field-to-CK observation mapping."""

        del is_complete, kwargs
        try:
            contract, events, checkpoints = _load_observation_contract(
                Path(self.workspace).resolve(),
                self.contract_file,
                self.doc_file,
                self.ignore_ck_prefix,
            )
            _validate_observation_source_refs(
                Path(self.workspace).resolve(),
                self.architecture_file,
                events,
            )
        except (OSError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="design_observation_contract_invalid",
                error="The backend-neutral observation contract is incomplete or inconsistent.",
                exc=exc,
                artifact=self.contract_file,
                guide="Guide_Doc/design_observation_contract.md",
                expected=(
                    "Schema 1.0 declares each public observation event once and maps "
                    "every functional CK to valid public pins or declared event fields."
                ),
            )
        return True, {
            "message": "The backend-neutral functional observation contract is complete.",
            "event_count": len(events),
            "checkpoint_count": len(checkpoints),
            "schema_version": contract["schema_version"],
        }




class DesignObservationInstrumentationChecker(Checker):
    """Prove that shared adapter/API source exposes every contracted observation field."""

    def __init__(
        self,
        contract_file: str,
        doc_file: str,
        architecture_file: str,
        adapter_file: str,
        api_file: str,
        ignore_ck_prefix: str | list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Store source paths and CK scope without importing workspace-authored code."""

        super().__init__()
        del kwargs
        self.contract_file = contract_file
        self.doc_file = doc_file
        self.architecture_file = architecture_file
        self.adapter_file = adapter_file
        self.api_file = api_file
        self.ignore_ck_prefix = _checkpoint_prefixes(
            _DEFAULT_FUNCTIONAL_CK_EXCLUDE_PREFIXES
            if ignore_ck_prefix is None
            else ignore_ck_prefix
        )

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Validate public pin observations and statically trace event fields to shared code."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        try:
            _contract, event_map, checkpoints = _load_observation_contract(
                workspace,
                self.contract_file,
                self.doc_file,
                self.ignore_ck_prefix,
            )
            public_attributes = _coverage_public_attributes(
                workspace, self.architecture_file, self.adapter_file
            )
            event_literals: set[str] = set()
            emitted_event_fields: dict[str, set[str]] = {}
            accepted_identity_fields: set[str] = set()
            for source_file in (self.adapter_file, self.api_file):
                source = resolve_workspace_path(workspace, source_file, must_exist=True)
                tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    called = (
                        node.func.attr
                        if isinstance(node.func, ast.Attribute)
                        else node.func.id
                        if isinstance(node.func, ast.Name)
                        else None
                    )
                    fixed_event = {
                        "_record_transaction_accepted": "transaction_accepted",
                        "_record_transaction_observation": "transaction_observation",
                        "_record_response_observed": "response_observed",
                    }.get(called)
                    if fixed_event is not None:
                        event_literals.add(fixed_event)
                        explicit_fields = {
                            keyword.arg
                            for keyword in node.keywords
                            if keyword.arg is not None
                        }
                        emitted_event_fields.setdefault(fixed_event, set()).update(
                            explicit_fields
                        )
                        if fixed_event == "transaction_accepted":
                            accepted_identity_fields.update(explicit_fields)
                            emitted_event_fields[fixed_event].update(
                                {"transaction_id", "accepted_at"}
                            )
                        elif fixed_event == "transaction_observation":
                            emitted_event_fields[fixed_event].update(
                                {"transaction_id", "accepted_at", "observed_at", "phase"}
                            )
                        else:
                            emitted_event_fields[fixed_event].update(
                                {"transaction_id", "accepted_at", "response_at"}
                            )
                    elif (
                        called == "_record_event"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                    ):
                        event_name = node.args[0].value
                        event_literals.add(event_name)
                        emitted_event_fields.setdefault(event_name, set()).update(
                            keyword.arg
                            for keyword in node.keywords
                            if keyword.arg is not None
                        )

            # Later transaction helpers merge the immutable identity captured by
            # _record_transaction_accepted and reject callers that repeat it.
            for inherited_event in ("transaction_observation", "response_observed"):
                if inherited_event in event_literals:
                    emitted_event_fields.setdefault(inherited_event, set()).update(
                        accepted_identity_fields
                    )

            _validate_observation_source_refs(
                workspace,
                self.architecture_file,
                event_map,
                public_attributes,
            )

            missing_pin_fields: dict[str, list[str]] = {}
            missing_events: list[str] = []
            missing_event_fields: dict[str, list[str]] = {}
            for checkpoint in checkpoints:
                if checkpoint["observation"] == "pins":
                    missing = sorted(set(checkpoint["fields"]) - public_attributes)
                    if missing:
                        missing_pin_fields[checkpoint["id"]] = missing
                    continue
                event_name = checkpoint["event"]
                if event_name not in event_literals:
                    missing_events.append(event_name)
                missing = sorted(
                    set(checkpoint["fields"])
                    - emitted_event_fields.get(event_name, set())
                )
                if missing:
                    missing_event_fields[checkpoint["id"]] = missing
            if missing_pin_fields or missing_events or missing_event_fields:
                raise ValueError(
                    "shared observation instrumentation is incomplete: "
                    f"missing_pin_fields={dict(list(missing_pin_fields.items())[:10])}, "
                    f"missing_events={sorted(set(missing_events))[:10]}, "
                    f"missing_event_fields={dict(list(missing_event_fields.items())[:10])}"
                )
            unused_events = sorted(set(event_map) - event_literals)
            if unused_events:
                raise ValueError(
                    f"contracted observation events are not emitted by shared code: {unused_events[:10]}"
                )
        except (OSError, SyntaxError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="design_observation_instrumentation_invalid",
                error="The shared adapter/API does not emit every contracted public observation.",
                exc=exc,
                artifact=self.adapter_file,
                guide="Guide_Doc/design_observation_contract.md",
                expected=(
                    f"{self.adapter_file} and {self.api_file} expose every contracted pin "
                    "and emit each declared event with all required public fields."
                ),
            )
        return True, {
            "message": "Shared adapter/API observation instrumentation matches the CK contract.",
            "event_count": len(event_map),
            "checkpoint_count": len(checkpoints),
        }
