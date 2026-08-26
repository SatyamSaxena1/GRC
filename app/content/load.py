"""Load and validate UCF content packs.

Content is data, not code: frameworks, requirements, UCO mappings and delta
conditions all live in the YAML files next to this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

CONTENT_DIR = Path(__file__).parent

Operator = Literal[">=", "<=", ">", "<", "==", "!=", "contains_all", "one_of"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Uco(_Model):
    code: str
    title: str
    domain: str


class DeltaCondition(_Model):
    attribute: str
    operator: Operator
    value: Any


class Mapping(_Model):
    uco: str
    coverage: Literal["FULL", "PARTIAL", "SUPPORTING"]
    confidence: float
    source: Literal["EXPERT", "AI", "IMPORTED"]
    delta_conditions: tuple[DeltaCondition, ...] = ()


class EvidenceRequirement(_Model):
    artefact_type: str
    required_attributes: tuple[str, ...]


class EvidenceValidity(_Model):
    """How long evidence for this requirement stays good.

    Freshness is a property of the requirement, not of the document: an ASV scan
    is valid for 90 days because PCI says so, not because of anything in the PDF.
    Evaluated against the audit period when one is supplied, so a verdict means
    "current for this audit" rather than "current when the job happened to run".
    """
    # Attribute holding an explicit expiry date stated by the document itself.
    expiry_attribute: str | None = None
    # Or derive expiry: this attribute (a date) plus max_age_days.
    issued_attribute: str | None = None
    max_age_days: int | None = None
    # A requirement can insist the document state its expiry rather than infer it.
    required: bool = True


class Requirement(_Model):
    clause: str
    title: str
    text: str
    evidence_requirements: tuple[EvidenceRequirement, ...]
    mappings: tuple[Mapping, ...]
    evidence_validity: EvidenceValidity | None = None


class FrameworkRef(_Model):
    code: str
    version: str


class Pack(_Model):
    framework: FrameworkRef
    requirements: tuple[Requirement, ...]


class Content(_Model):
    ucos: tuple[Uco, ...]
    packs: tuple[Pack, ...]

    def framework(self, code: str) -> Pack:
        for pack in self.packs:
            if pack.framework.code == code:
                return pack
        raise KeyError(code)


def load(content_dir: Path = CONTENT_DIR) -> Content:
    ucos = tuple(
        Uco(**u)
        for u in yaml.safe_load((content_dir / "uco.yaml").read_text())["ucos"]
    )
    packs = tuple(
        Pack(**yaml.safe_load(path.read_text()))
        for path in sorted(content_dir.glob("*.yaml"))
        if path.name != "uco.yaml"
    )
    _check_references(ucos, packs)
    return Content(ucos=ucos, packs=packs)


def _check_references(ucos: tuple[Uco, ...], packs: tuple[Pack, ...]) -> None:
    known = {u.code for u in ucos}
    if len(known) != len(ucos):
        raise ValueError("duplicate UCO codes")
    for pack in packs:
        clauses = [r.clause for r in pack.requirements]
        if len(set(clauses)) != len(clauses):
            raise ValueError(f"duplicate clauses in {pack.framework.code}")
        for req in pack.requirements:
            for mapping in req.mappings:
                if mapping.uco not in known:
                    raise ValueError(
                        f"{pack.framework.code} {req.clause} maps to unknown "
                        f"UCO {mapping.uco}"
                    )


if __name__ == "__main__":
    content = load()
    print(f"{len(content.ucos)} UCOs, {len(content.packs)} frameworks")
    for pack in content.packs:
        print(f"  {pack.framework.code} {pack.framework.version}: "
              f"{len(pack.requirements)} requirements")
