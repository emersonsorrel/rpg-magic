"""Issue codes and the report object every validation pass returns.

Codes are stable strings, not prose. Tests assert on codes; the repair round-trip
(M3) feeds the messages back to the model. Nothing should ever match on message text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class Code:
    # structural
    SCHEMA = "schema"
    LAYER_SIZE_MISMATCH = "layer_size_mismatch"
    TILE_OUT_OF_RANGE = "tile_out_of_range"
    UNKNOWN_TILESET = "unknown_tileset"

    # command vocabulary
    UNKNOWN_OP = "unknown_op"
    MISSING_PARAM = "missing_param"
    UNKNOWN_PARAM = "unknown_param"
    NESTING_TOO_DEEP = "nesting_too_deep"
    TEXT_TOO_LONG = "text_too_long"
    EMPTY_TEXT = "empty_text"

    # referential integrity
    UNKNOWN_ITEM = "unknown_item"
    UNKNOWN_FLAG = "unknown_flag"
    UNKNOWN_ENCOUNTER = "unknown_encounter"
    UNKNOWN_ENTITY = "unknown_entity"
    UNKNOWN_ZONE = "unknown_zone"
    WARP_TARGET_UNDECLARED = "warp_target_undeclared"

    # placement
    DUPLICATE_ENTITY_ID = "duplicate_entity_id"
    ENTITY_OUT_OF_BOUNDS = "entity_out_of_bounds"
    ENTITY_ON_BLOCKED_TILE = "entity_on_blocked_tile"
    ENTITY_UNREACHABLE = "entity_unreachable"
    WARP_OUT_OF_BOUNDS = "warp_out_of_bounds"
    WARP_ON_BLOCKED_TILE = "warp_on_blocked_tile"
    WARP_UNREACHABLE = "warp_unreachable"
    NO_ENTRY_POINT = "no_entry_point"

    # obligations
    UNKNOWN_OBLIGATION = "unknown_obligation"
    OBLIGATION_UNFULFILLED = "obligation_unfulfilled"
    OBLIGATION_ALREADY_PLACED = "obligation_already_placed"
    OBLIGATION_NOT_CLAIMED = "obligation_not_claimed"

    # ledger
    DANGLING_ZONE_REF = "dangling_zone_ref"
    ASYMMETRIC_EXIT = "asymmetric_exit"
    UNKNOWN_BEAT = "unknown_beat"
    BAD_OBLIGATION_STATE = "bad_obligation_state"

    # soft
    UNKNOWN_TAG = "unknown_tag"
    MISSING_SCRIPT = "missing_script"
    UNUSED_FLAG = "unused_flag"
    FLAG_REDECLARED = "flag_redeclared"
    UNSUPPORTED_OBLIGATION_KIND = "unsupported_obligation_kind"


@dataclass(frozen=True)
class Issue:
    code: str
    path: str
    message: str
    severity: Severity = Severity.ERROR

    def __str__(self) -> str:
        mark = "E" if self.severity is Severity.ERROR else "W"
        return f"  [{mark}] {self.code:<26} {self.path}\n        {self.message}"


@dataclass
class Report:
    subject: str = ""
    issues: list[Issue] = field(default_factory=list)

    def error(self, code: str, path: str, message: str) -> None:
        self.issues.append(Issue(code, path, message, Severity.ERROR))

    def warn(self, code: str, path: str, message: str) -> None:
        self.issues.append(Issue(code, path, message, Severity.WARNING))

    def extend(self, other: "Report") -> None:
        self.issues.extend(other.issues)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        """Commit-worthy. Warnings never block a commit."""
        return not self.errors

    def codes(self) -> set[str]:
        return {i.code for i in self.issues}

    def error_codes(self) -> set[str]:
        return {i.code for i in self.errors}

    def __str__(self) -> str:
        head = f"{self.subject}: " if self.subject else ""
        if not self.issues:
            return f"{head}PASS"
        verdict = "PASS (with warnings)" if self.ok else "FAIL"
        lines = [f"{head}{verdict} - {len(self.errors)} error(s), {len(self.warnings)} warning(s)"]
        lines += [str(i) for i in self.issues]
        return "\n".join(lines)
