"""Read-only prerequisite checks shared by issue admission and operator recovery."""

from pydantic import Field
from .contracts import StrictModel


class Requirement(StrictModel):
    """One concrete prerequisite; no arbitrary commands or agent-authored check results."""

    kind: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=2000)


class RequirementChecks:
    """Extensible trusted checks; unknown prerequisites remain explicitly unverified."""

    def __init__(self):
        """Install bounded file and actual-tool checks without provider-specific rules."""
        self.checks = {}
        self.register("file_exists", lambda service, record, value: service.path(value).is_file())
        self.register("file_writable", self._writable)
        self.register("tool_available", lambda service, record, value: value in record.available_tools)
        self.register("capability_available", lambda service, record, value: bool(record.capabilities.get(value)))

    def register(self, kind, check):
        """Register a trusted read-only check without replacing another check's semantics."""
        if not kind or kind in self.checks or not callable(check):
            raise ValueError("Requirement checks need a unique name and callable")
        self.checks[kind] = check

    @staticmethod
    def _writable(service, record, value):
        """Check configured write authority, not a speculative operating-system failure."""
        service.path(value, writing=True)
        return not record.split or value in record.spec.outputs

    def evaluate(self, service, record, conditions):
        """Return bounded runtime observations, never interpreting model-authored error text."""
        rows = []
        for raw in conditions:
            condition = Requirement.model_validate(raw)
            check = self.checks.get(condition.kind)
            result = None
            if check is not None:
                try:
                    result = check(service, record, condition.value)
                    if type(result) is not bool:
                        result = None
                except (OSError, ValueError, PermissionError):
                    result = False
            rows.append({**condition.model_dump(), "satisfied": result, "source": "runtime"})
        return rows
