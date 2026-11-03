"""The skill tool: deck-craft guidance the agent reads when it needs it, not up front."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from autodeck.agents.skills import SkillError, _without_project, available_skills, load_skill
from autodeck.agents.tools.registry import Tool, ToolResult, error_result


class LoadSkillArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="A skill name, e.g. 'citations'.")


def skill_tools(*, project: str | None) -> list[Tool]:
    def run(args: LoadSkillArgs) -> ToolResult:
        try:
            skill = load_skill(args.name)
        except SkillError as exc:
            return error_result(str(exc), f"load_skill {args.name}: unknown")
        body = _without_project(skill.body, project)
        return ToolResult(f"## Skill: {skill.name}\n\n{body}", f"loaded skill {skill.name}")

    names = ", ".join(available_skills())
    return [
        Tool(
            "load_skill",
            f"Read one deck-craft skill. Available: {names}.",
            LoadSkillArgs,
            run,
        )
    ]
