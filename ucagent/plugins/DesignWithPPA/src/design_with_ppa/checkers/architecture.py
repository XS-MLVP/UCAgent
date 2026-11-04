"""Frozen architecture machine-contract gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from ucagent.checkers.base import Checker
from ..contracts import (
    load_fenced_yaml,
    resolve_workspace_path,
)
from ..rtl import (
    resolve_rtl_config,
)

from .common import (
    _VERILOG_IDENTIFIER_RE,
    _exception_contract_diagnostic,
    _validated_input_identity,
)




class DesignArchitectureChecker(Checker):
    """Validate the canonical machine-readable interface and RTL design constraints."""

    def __init__(
        self,
        architecture_file: str,
        cfg: Any,
        input_manifest_file: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Store the architecture artifact path for live checks."""

        super().__init__()
        del kwargs
        self.cfg = cfg
        self.rtl_config, _ = resolve_rtl_config(cfg)
        self.architecture_file = architecture_file
        self.input_manifest_file = input_manifest_file

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Require a complete port, timing, reset, CDC, and synthesis architecture contract."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        try:
            input_identity = (
                _validated_input_identity(workspace, self.input_manifest_file)
                if self.input_manifest_file is not None
                else None
            )
            path = resolve_workspace_path(
                workspace, self.architecture_file, must_exist=True
            )
            architecture = load_fenced_yaml(path, "architecture")
            if architecture.get("schema_version") != "1.0":
                raise ValueError("architecture.schema_version must be 1.0")
            top = architecture.get("top_module")
            if not isinstance(top, str) or not _VERILOG_IDENTIFIER_RE.fullmatch(top):
                raise ValueError(
                    "architecture.top_module must be a portable RTL identifier"
                )
            parameters = architecture.get("parameters")
            if not isinstance(parameters, list):
                raise ValueError("architecture.parameters must be a list")
            seen_parameters = set()
            for index, parameter in enumerate(parameters):
                if not isinstance(parameter, dict):
                    raise ValueError(
                        f"architecture.parameters[{index}] must be a mapping"
                    )
                name = parameter.get("name")
                if not isinstance(name, str) or not _VERILOG_IDENTIFIER_RE.fullmatch(
                    name
                ):
                    raise ValueError(
                        f"architecture.parameters[{index}].name is invalid"
                    )
                if name in seen_parameters:
                    raise ValueError(f"duplicate architecture parameter: {name}")
                seen_parameters.add(name)
                if not isinstance(parameter.get("type"), str) or not parameter[
                    "type"
                ].strip():
                    raise ValueError(
                        f"architecture.parameters[{index}].type must be non-empty"
                    )
                if "default" not in parameter:
                    raise ValueError(
                        f"architecture.parameters[{index}].default is required"
                    )
                if parameter.get("valid_range") in (None, "", [], {}):
                    raise ValueError(
                        f"architecture.parameters[{index}].valid_range is required"
                    )
            ports = architecture.get("ports")
            if not isinstance(ports, list) or not ports:
                raise ValueError("architecture.ports must be a non-empty list")
            seen_ports = set()
            input_ports = set()
            for index, port in enumerate(ports):
                if not isinstance(port, dict):
                    raise ValueError(f"architecture.ports[{index}] must be a mapping")
                name = port.get("name")
                if not isinstance(name, str) or not _VERILOG_IDENTIFIER_RE.fullmatch(name):
                    raise ValueError(f"architecture.ports[{index}].name is invalid")
                if name in seen_ports:
                    raise ValueError(f"duplicate architecture port: {name}")
                seen_ports.add(name)
                if port.get("direction") not in {"input", "output", "inout"}:
                    raise ValueError(f"architecture.ports[{index}].direction is invalid")
                if port["direction"] == "input":
                    input_ports.add(name)
                width = port.get("width")
                if (
                    isinstance(width, bool)
                    or not isinstance(width, (int, str))
                    or (isinstance(width, int) and width < 1)
                    or (isinstance(width, str) and not width.strip())
                ):
                    raise ValueError(f"architecture.ports[{index}].width is invalid")
                if type(port.get("signed")) is not bool:
                    raise ValueError(f"architecture.ports[{index}].signed must be boolean")
                if not isinstance(port.get("role"), str) or not port["role"].strip():
                    raise ValueError(
                        f"architecture.ports[{index}].role must be non-empty"
                    )
            intent = architecture.get("design_intent")
            if intent not in {"combinational", "sequential", "mixed"}:
                raise ValueError("architecture.design_intent must be combinational, sequential, or mixed")
            clock_reset = architecture.get("clock_reset")
            if not isinstance(clock_reset, dict):
                raise ValueError("architecture.clock_reset must be a mapping")
            clocks = clock_reset.get("clocks")
            resets = clock_reset.get("resets")
            rationale = clock_reset.get("rationale")
            if not isinstance(clocks, list) or not isinstance(resets, list):
                raise ValueError(
                    "architecture.clock_reset.clocks and resets must be lists"
                )
            if not isinstance(rationale, str) or not rationale.strip():
                raise ValueError(
                    "architecture.clock_reset.rationale must be non-empty"
                )
            clock_names = set()
            for index, clock in enumerate(clocks):
                if not isinstance(clock, dict):
                    raise ValueError(
                        f"architecture.clock_reset.clocks[{index}] must be a mapping"
                    )
                name = clock.get("name")
                if name not in input_ports:
                    raise ValueError(
                        f"architecture.clock_reset.clocks[{index}].name must name an input port"
                    )
                if name in clock_names:
                    raise ValueError(f"duplicate architecture clock: {name}")
                clock_names.add(name)
                if clock.get("edge") not in {"posedge", "negedge"}:
                    raise ValueError(
                        f"architecture.clock_reset.clocks[{index}].edge is invalid"
                    )
            if intent == "combinational" and clocks:
                raise ValueError("a combinational architecture must not declare clocks")
            if intent in {"sequential", "mixed"} and not clocks:
                raise ValueError(
                    "a sequential or mixed architecture must declare at least one clock"
                )
            reset_names = set()
            for index, reset in enumerate(resets):
                if not isinstance(reset, dict):
                    raise ValueError(
                        f"architecture.clock_reset.resets[{index}] must be a mapping"
                    )
                name = reset.get("name")
                if name not in input_ports:
                    raise ValueError(
                        f"architecture.clock_reset.resets[{index}].name must name an input port"
                    )
                if name in reset_names:
                    raise ValueError(f"duplicate architecture reset: {name}")
                reset_names.add(name)
                if reset.get("active_level") not in {"high", "low"}:
                    raise ValueError(
                        f"architecture.clock_reset.resets[{index}].active_level is invalid"
                    )
                synchrony = reset.get("synchrony")
                if synchrony not in {"synchronous", "asynchronous"}:
                    raise ValueError(
                        f"architecture.clock_reset.resets[{index}].synchrony is invalid"
                    )
                if reset.get("clock") not in clock_names:
                    raise ValueError(
                        f"architecture.clock_reset.resets[{index}].clock must name a declared clock"
                    )
                if synchrony == "synchronous" and reset.get("sample_edge") not in {
                    "posedge",
                    "negedge",
                }:
                    raise ValueError(
                        f"architecture.clock_reset.resets[{index}].sample_edge "
                        "must be posedge or negedge for a synchronous reset"
                    )
                if synchrony == "asynchronous":
                    if reset.get("assertion_edge") not in {"posedge", "negedge"}:
                        raise ValueError(
                            f"architecture.clock_reset.resets[{index}].assertion_edge "
                            "must be posedge or negedge for an asynchronous reset"
                        )
                    if not isinstance(reset.get("deassertion"), str) or not reset[
                        "deassertion"
                    ].strip():
                        raise ValueError(
                            f"architecture.clock_reset.resets[{index}].deassertion must be non-empty"
                        )
            timing = architecture.get("timing")
            if not isinstance(timing, dict):
                raise ValueError("architecture.timing must be a mapping")
            for field in (
                "transaction_accept",
                "response",
                "handshake",
                "backpressure",
            ):
                if not isinstance(timing.get(field), str) or not timing[field].strip():
                    raise ValueError(f"architecture.timing.{field} must be non-empty")
            latency = timing.get("latency_cycles")
            if (
                isinstance(latency, bool)
                or not isinstance(latency, (int, str))
                or (isinstance(latency, int) and latency < 0)
                or (isinstance(latency, str) and not latency.strip())
            ):
                raise ValueError("architecture.timing.latency_cycles is invalid")
            illegal_inputs = architecture.get("illegal_inputs")
            if (
                not isinstance(illegal_inputs, dict)
                or not isinstance(illegal_inputs.get("policy"), str)
                or not illegal_inputs["policy"].strip()
            ):
                raise ValueError("architecture.illegal_inputs.policy must be non-empty")
            cdc = architecture.get("multi_clock_cdc")
            if not isinstance(cdc, dict):
                raise ValueError("architecture.multi_clock_cdc must be a mapping")
            domains = cdc.get("clock_domains")
            if isinstance(domains, bool) or not isinstance(domains, int) or domains < 0:
                raise ValueError(
                    "architecture.multi_clock_cdc.clock_domains must be a non-negative integer"
                )
            if not isinstance(cdc.get("policy"), str) or not cdc["policy"].strip():
                raise ValueError("architecture.multi_clock_cdc.policy must be non-empty")
            if intent == "combinational" and domains != 0:
                raise ValueError(
                    "a combinational architecture must declare zero clock domains"
                )
            if intent in {"sequential", "mixed"} and domains != len(clock_names):
                raise ValueError(
                    "architecture clock_domains must equal the declared clock count"
                )
            synthesis = architecture.get("synthesis_constraints")
            if not isinstance(synthesis, dict):
                raise ValueError("architecture.synthesis_constraints must be a mapping")
            for field in (
                "no_latch",
                "no_unknown_outputs",
                "no_initial_delay",
                "synthesizable_only",
            ):
                if synthesis.get(field) is not True:
                    raise ValueError(
                        f"architecture.synthesis_constraints.{field} must be true"
                    )
            forbidden = synthesis.get("forbidden_constructs")
            required_forbidden = {"delay", "force", "release", "simulation-system-task"}
            if (
                not isinstance(forbidden, list)
                or any(not isinstance(value, str) for value in forbidden)
                or not required_forbidden.issubset(forbidden)
            ):
                raise ValueError(
                    "architecture.synthesis_constraints.forbidden_constructs is incomplete"
                )
            acceptance = architecture.get("acceptance_criteria")
            if (
                not isinstance(acceptance, list)
                or not acceptance
                or any(
                    not isinstance(value, str) or not value.strip()
                    for value in acceptance
                )
            ):
                raise ValueError(
                    "architecture.acceptance_criteria must contain measurable strings"
                )
        except (OSError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="design_architecture_invalid",
                error="The architecture document does not satisfy the machine-readable design contract.",
                exc=exc,
                artifact=self.architecture_file,
                guide="Guide_Doc/design_input_and_architecture.md",
                expected=(
                    "Exactly one architecture YAML block with schema 1.0, a complete "
                    "top/parameter/port interface, consistent clock/reset/timing/CDC "
                    "semantics, synthesis constraints, and measurable acceptance criteria."
                ),
            )
        return True, {
            "message": "Design architecture contract is complete.",
            "top_module": top,
            "design_input_sha256": (
                input_identity["source_set_sha256"]
                if input_identity is not None
                else None
            ),
        }
