"""Register only the Preset-to-Sprite creation tools and host Plan inspection."""

from dataclasses import dataclass
from typing import Any

from ..planning import PlanAction
from .contracts import (
    PresetCreateInput,
    PresetCreateOutput,
    SpriteComposeInput,
    SpriteComposeOutput,
    SpriteCreateInput,
    SpriteCreateOutput,
    ToolDescriptor,
    ToolInspectInput,
    ToolResult,
)
from .registry import RegisteredTool, ToolFault, get_tool, registered_tools, tool


def _success(data: Any) -> dict[str, Any]:
    """Build a typed success envelope for one creation operation."""
    return {"ok": True, "data": data}


def _failure(exc: Exception, code: str) -> dict[str, Any]:
    """Convert a deterministic creation failure into the public error envelope."""
    if isinstance(exc, ToolFault):
        return {"ok": False, "error": exc.error}
    return {"ok": False, "error": {"code": code, "message": str(exc) or code}}


@tool(
    "preset.create",
    constraints=["The complete source, parameter schema and defaults are saved as a new immutable record."],
    side_effects=["code validation and preset catalog write"],
    error_codes=["INVALID_ARGUMENT", "CODE_VALIDATION_FAILED", "PRESET_STORE_FAILED"],
    examples=[{"input": {"description": "静态文字", "code": "export default function Label(){return null}", "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": False}, "default_parameters": {}}, "output": {"ok": False, "error": {"code": "CODE_VALIDATION_FAILED", "message": "example"}}}],
)
async def preset_create(owner, request: PresetCreateInput) -> ToolResult[PresetCreateOutput]:
    """Validate and save a new immutable Preset definition."""
    try:
        return _success(await owner.create_pr76_preset(request))
    except Exception as exc:
        return _failure(exc, "PRESET_STORE_FAILED")


@tool(
    "sprite.compose",
    constraints=["The host canvas is fixed at 1080x1920, 30 FPS; duration is derived from instances."],
    side_effects=["deterministic source generation; no catalog write"],
    error_codes=["INVALID_ARGUMENT", "PRESET_NOT_FOUND", "COMPOSITION_FAILED"],
    examples=[{"input": {"description": "组合", "instances": [{"instance_id": "title", "source": {"kind": "draft", "preset": {"description": "文字", "code": "export default function Label(){return null}", "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": False}, "default_parameters": {}}}, "layout": {"x": 0.0, "y": 0.0, "width": 100, "height": 100, "z_index": 0}, "timing": {"start_frame": 0, "duration_frames": 1}}]}, "output": {"ok": False, "error": {"code": "COMPOSITION_FAILED", "message": "example"}}}],
)
async def sprite_compose(owner, request: SpriteComposeInput) -> ToolResult[SpriteComposeOutput]:
    """Resolve Presets and produce a complete immutable Sprite draft."""
    try:
        return _success({"sprite": owner.compose_pr76(request)["sprite"]})
    except Exception as exc:
        return _failure(exc, "COMPOSITION_FAILED")


@tool(
    "sprite.create",
    constraints=["Only a compose-produced SpriteDraft with consistent source and parameters may be saved."],
    side_effects=["code validation and sprite catalog write"],
    error_codes=["INVALID_ARGUMENT", "CODE_VALIDATION_FAILED", "SPRITE_STORE_FAILED"],
    examples=[{"input": {"sprite": {"description": "组合", "code": "export default function Sprite(){return null}", "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": False}, "default_parameters": {}, "composition": {"width": 1080, "height": 1920, "fps": 30, "duration_frames": 1}, "instances": [{"instance_id": "title", "preset": {"description": "文字", "code": "export default function Label(){return null}", "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": False}, "default_parameters": {}}, "parameters": {}, "layout": {"x": 0.0, "y": 0.0, "width": 100, "height": 100, "z_index": 0}, "timing": {"start_frame": 0, "duration_frames": 1}}]}}, "output": {"ok": False, "error": {"code": "CODE_VALIDATION_FAILED", "message": "example"}}}],
)
async def sprite_create(owner, request: SpriteCreateInput) -> ToolResult[SpriteCreateOutput]:
    """Validate and persist one composed Sprite draft."""
    try:
        return _success(await owner.create_pr76_sprite(request.sprite))
    except Exception as exc:
        return _failure(exc, "SPRITE_STORE_FAILED")


@tool(
    "tools.inspect",
    constraints=["The name is exact; inspection never discovers or executes tools."],
    side_effects=["registry read only"],
    error_codes=["INVALID_ARGUMENT", "TOOL_NOT_FOUND"],
    examples=[{"input": {"tool_name": "sprite.compose"}, "output": {"ok": False, "error": {"code": "TOOL_NOT_FOUND", "message": "example"}}}],
)
async def tools_inspect(owner, request: ToolInspectInput) -> ToolResult[ToolDescriptor]:
    """Return one exact registered creation-tool descriptor."""
    try:
        return _success(get_tool(request.tool_name).describe())
    except ToolFault as exc:
        return _failure(exc, "TOOL_NOT_FOUND")


@dataclass(frozen=True)
class PlanTool:
    """Host-owned orchestration control exposed to Outer and Plan ReAct."""

    name: str = "tools.plan_execute"
    input: type = PlanAction

    def wire(self) -> dict[str, Any]:
        """Expose the Plan transition schema as a provider function."""
        return {"type": "function", "function": {"name": self.name.replace(".", "_"), "description": "Create, continue, advance or finish the ordered Plan; never executes a business tool.", "parameters": self.input.model_json_schema()}}

    def describe(self) -> dict[str, Any]:
        """Describe the host-owned Plan transition without executing it."""
        return {"tool_id": self.name, "version": 1, "description": "Host-owned Plan transition control.", "input_schema": self.input.model_json_schema(), "writes": False, "available": True}


PLAN_TOOL = PlanTool()


def available(modules=None, *, executor=False):
    """Return only creation tools plus Plan control for the permitted layer."""
    tools: list[RegisteredTool | PlanTool] = []
    if not executor and (modules is None or "tools" in modules):
        tools.append(PLAN_TOOL)
    allowed = {"preset.create", "sprite.compose", "sprite.create", "tools.inspect"}
    for item in registered_tools():
        if item.name in allowed and (modules is None or item.name == "tools.inspect" or item.name.split(".", 1)[0] in modules):
            tools.append(item)
    return tools


def resolve(name: str, modules=None, *, executor=False):
    """Resolve one permitted creation tool by dotted or provider-wire name."""
    for item in available(modules, executor=executor):
        if name in {item.name, item.name.replace(".", "_")}:
            return item
    raise ValueError("Unknown or out-of-scope tool")
