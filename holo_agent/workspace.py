from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


INSTRUCTION_FILENAMES = ("HOLO.md", "AGENTS.md", "CLAUDE.md")


@dataclass(slots=True)
class InstructionLayer:
    path: str
    scope: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "scope": self.scope, "text": self.text}


@dataclass(slots=True)
class Skill:
    name: str
    path: str
    description: str
    body: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "path": self.path, "description": self.description, "body": self.body}


@dataclass(slots=True)
class WorkspaceContext:
    root: Path
    instruction_layers: list[InstructionLayer] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    preferences: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "instruction_layers": [item.to_dict() for item in self.instruction_layers],
            "skills": [item.to_dict() for item in self.skills],
            "preferences": dict(self.preferences),
        }


def _safe_read(path: Path, *, limit: int = 12000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[:limit]


def load_instruction_layers(root: Path) -> list[InstructionLayer]:
    root = Path(root).resolve()
    layers: list[InstructionLayer] = []
    current = root
    chain = [current]
    for parent in current.parents:
        chain.append(parent)
        if parent.parent == parent:
            break
    for directory in reversed(chain):
        for name in INSTRUCTION_FILENAMES:
            path = directory / name
            if not path.exists() or not path.is_file():
                continue
            try:
                rel = path.relative_to(root)
                scope = "workspace"
            except ValueError:
                rel = path
                scope = "ancestor"
            text = _safe_read(path)
            if text.strip():
                layers.append(InstructionLayer(path=str(rel), scope=scope, text=text.strip()))
    return layers


def load_skills(root: Path) -> list[Skill]:
    root = Path(root).resolve()
    skill_root = root / ".holo" / "skills"
    if not skill_root.exists():
        return []
    skills: list[Skill] = []
    for skill_file in sorted(skill_root.glob("*/SKILL.md")):
        body = _safe_read(skill_file)
        if not body.strip():
            continue
        name = skill_file.parent.name
        first_line = next((line.strip("# ").strip() for line in body.splitlines() if line.strip()), name)
        skills.append(
            Skill(
                name=name,
                path=str(skill_file.relative_to(root)),
                description=first_line,
                body=body.strip(),
            )
        )
    return skills


def load_preferences(root: Path) -> dict[str, Any]:
    path = Path(root).resolve() / ".holo" / "preferences.json"
    if not path.exists():
        return {}
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"load_error": "invalid_preferences_json"}
    return data if isinstance(data, dict) else {}


def load_workspace_context(root: Path) -> WorkspaceContext:
    root = Path(root).resolve()
    return WorkspaceContext(
        root=root,
        instruction_layers=load_instruction_layers(root),
        skills=load_skills(root),
        preferences=load_preferences(root),
    )

