"""PR76 business tool catalog plus the single host-owned Plan control tool."""

from dataclasses import dataclass
from typing import Any

from ..planning import PlanAction
from .contracts import (
    CodeValidationInput,
    CodeValidationReport,
    ImageCropInput,
    ImageInfo,
    ImageInfoInput,
    ImageResizeInput,
    PresetCreateInput,
    PresetCreateOutput,
    PresetModifyInput,
    PresetModifyOutput,
    PresetSearchInput,
    PresetSearchOutput,
    RenderValidationInput,
    RenderValidationReport,
    SpriteComposeInput,
    SpriteComposeOutput,
    SpriteCreateInput,
    SpriteCreateOutput,
    ToolInspectInput,
    ToolDescriptor,
    ToolResult,
)
from .image_tools import ImageToolError, execute_image
from .registry import RegisteredTool, ToolFault, get_tool, registered_tools, tool


def _success(data):
    """Build a typed success envelope while keeping handlers concise."""
    return {"ok": True, "data": data}


def _failure(exc: Exception, code: str = "TOOL_FAILED"):
    """Convert deterministic implementation failures to the public error envelope."""
    if isinstance(exc, ToolFault):
        return {"ok": False, "error": exc.error}
    if isinstance(exc, ImageToolError):
        code = exc.code
        message = str(exc).split(": ", 1)[-1]
    else:
        message = str(exc) or code
    return {"ok": False, "error": {"code": code, "message": message}}


@tool(
    "image.info",
    constraints=["Reads one single-frame PNG, JPEG or WebP URL."],
    side_effects=["network read only"],
    error_codes=["INVALID_ARGUMENT", "IMAGE_FETCH_FAILED", "UNSUPPORTED_IMAGE", "IMAGE_DECODE_FAILED", "RESOURCE_LIMIT_EXCEEDED"],
    examples=[{"input": {"image_url": "https://example.test/reference.png"}, "output": {"ok": False, "error": {"code": "IMAGE_FETCH_FAILED", "message": "example"}}}],
)
async def image_info(owner, request: ImageInfoInput) -> ToolResult[ImageInfo]:
    """Read image dimensions, format, byte size and alpha presence."""
    try:
        return _success(await execute_image("image.info", request, owner.harness.settings))
    except Exception as exc:
        return _failure(exc)


@tool(
    "image.resize",
    constraints=["Width and height are positive target pixels; aspect ratio is intentionally not preserved."],
    side_effects=["network read and new PNG write"],
    error_codes=["INVALID_ARGUMENT", "IMAGE_FETCH_FAILED", "IMAGE_PROCESSING_FAILED", "IMAGE_STORE_FAILED", "RESOURCE_LIMIT_EXCEEDED"],
    examples=[{"input": {"image_url": "https://example.test/reference.png", "width": 100, "height": 100}, "output": {"ok": False, "error": {"code": "IMAGE_FETCH_FAILED", "message": "example"}}}],
)
async def image_resize(owner, request: ImageResizeInput) -> ToolResult[ImageInfo]:
    """Resize an image to exact target pixels and return a durable PNG URL."""
    try:
        return _success(await execute_image("image.resize", request, owner.harness.settings))
    except Exception as exc:
        return _failure(exc)


@tool(
    "image.crop",
    constraints=["The half-open crop rectangle must remain inside the source image."],
    side_effects=["network read and new PNG write"],
    error_codes=["INVALID_ARGUMENT", "CROP_OUT_OF_BOUNDS", "IMAGE_FETCH_FAILED", "IMAGE_PROCESSING_FAILED", "IMAGE_STORE_FAILED"],
    examples=[{"input": {"image_url": "https://example.test/reference.png", "x": 0, "y": 0, "width": 100, "height": 100}, "output": {"ok": False, "error": {"code": "IMAGE_FETCH_FAILED", "message": "example"}}}],
)
async def image_crop(owner, request: ImageCropInput) -> ToolResult[ImageInfo]:
    """Crop a pixel rectangle without scaling and return a durable PNG URL."""
    try:
        return _success(await execute_image("image.crop", request, owner.harness.settings))
    except Exception as exc:
        return _failure(exc)


@tool(
    "preset.search",
    constraints=["Search is deterministic and read-only; it does not generate code or invoke another model."],
    side_effects=["preset catalog read only"],
    error_codes=["INVALID_ARGUMENT", "SEARCH_UNAVAILABLE"],
    examples=[{"input": {"query": "文字标题", "limit": 5}, "output": {"ok": False, "error": {"code": "SEARCH_UNAVAILABLE", "message": "example"}}}],
)
async def preset_search(owner, request: PresetSearchInput) -> ToolResult[PresetSearchOutput]:
    """Search reusable Presets by their stored description and return complete records."""
    try:
        return _success(await owner.search_pr76(request))
    except Exception as exc:
        return _failure(exc, "SEARCH_UNAVAILABLE")


@tool(
    "preset.create",
    constraints=["The complete source, parameter schema and defaults are saved as a new immutable record."],
    side_effects=["code validation and preset catalog write"],
    error_codes=["INVALID_ARGUMENT", "CODE_VALIDATION_FAILED", "PRESET_STORE_FAILED"],
    examples=[{"input": {"description": "静态文字", "code": "export default function Label(){return null}", "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": False}, "default_parameters": {}}, "output": {"ok": False, "error": {"code": "CODE_VALIDATION_FAILED", "message": "example"}}}],
)
async def preset_create(owner, request: PresetCreateInput) -> ToolResult[PresetCreateOutput]:
    """Validate and save a complete Preset definition."""
    try:
        return _success(await owner.create_pr76_preset(request))
    except Exception as exc:
        return _failure(exc, "PRESET_STORE_FAILED")


@tool(
    "preset.modify",
    constraints=["Changes replace whole fields and never mutate the selected record."],
    side_effects=["preset catalog read only"],
    error_codes=["INVALID_ARGUMENT", "PRESET_NOT_FOUND"],
    examples=[{"input": {"preset_id": "missing", "changes": {"description": "副本"}}, "output": {"ok": False, "error": {"code": "PRESET_NOT_FOUND", "message": "example"}}}],
)
async def preset_modify(owner, request: PresetModifyInput) -> ToolResult[PresetModifyOutput]:
    """Return an independent modified Preset draft without saving it."""
    try:
        return _success(await owner.modify_pr76_preset(request))
    except Exception as exc:
        return _failure(exc, "PRESET_NOT_FOUND")


@tool(
    "validate.code",
    constraints=["Diagnostics describe source/contract validity and do not prove visual behavior."],
    side_effects=["isolated language-service read and temporary files"],
    error_codes=["INVALID_ARGUMENT", "VALIDATION_UNAVAILABLE"],
    examples=[{"input": {"component": {"code": "export default function Label(){return null}", "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": False}, "default_parameters": {}}}, "output": {"ok": False, "error": {"code": "VALIDATION_UNAVAILABLE", "message": "example"}}}],
)
async def validate_code(owner, request: CodeValidationInput) -> ToolResult[CodeValidationReport]:
    """Run the host TypeScript/source-policy checks for one component."""
    try:
        return _success(await owner.validate_pr76_code(request.component))
    except Exception as exc:
        return _failure(exc, "VALIDATION_UNAVAILABLE")


@tool(
    "validate.render",
    constraints=["The supplied duration is measured in frames at 30 FPS."],
    side_effects=["isolated code and render validation"],
    error_codes=["INVALID_ARGUMENT", "VALIDATION_UNAVAILABLE"],
    examples=[{
        "input": {
            "component": {
                "code": 'import React from "react"; export default function Label(props: {text: string}) { return <div data-testid="label">{props.text}</div>; }',
                "parameter_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False},
                "default_parameters": {"text": "Hello"},
            },
            "duration_frames": 30,
            "tests": [{"name": "visible_text_and_parameters", "code": '''export default async function run(ctx) {
  await ctx.set_frame(29);
  const label = await ctx.query('[data-testid="label"]');
  ctx.assert(label !== null, 'label exists');
  ctx.assert_equal(label.text, 'Hello', 'visible text');
  ctx.assert(label.box.width > 0, 'visible width');
  await ctx.set_parameters({text: 'Changed'});
  const changed = await ctx.query('[data-testid="label"]');
  ctx.assert_equal(changed.text, 'Changed', 'parameter update');
}'''}],
        },
        "output": {"ok": False, "error": {"code": "VALIDATION_UNAVAILABLE", "message": "example of unavailable browser environment"}},
    }],
)
async def validate_render(owner, request: RenderValidationInput) -> ToolResult[RenderValidationReport]:
    """Render a component and run named TypeScript behavior tests in an isolated browser.

    Each test must export default async function run(ctx), with no imports or globals.
    Await ctx.set_frame(frame), ctx.set_parameters(partial_patch), ctx.query(css_selector)
    or ctx.query_all(css_selector). query returns null or {text, box:{x,y,width,height},
    styles:{CSS-property-name:string}}; query_all returns an array. Coordinates are
    canvas-relative pixels; use styles['font-weight'], styles.color, etc.
    Record checks with ctx.assert(condition, message), ctx.assert_equal(actual, expected,
    message), or ctx.assert_close(actual, expected, tolerance, message). Returning an
    assertion array does not record checks. ctx has no props, check, getFrame or DOM APIs.
    ctx.composition contains width, height, fps, duration_frames; frames are zero-based.
    Tests reset independently to frame 0 and configured parameters. At least one real
    assertion is required per test. Query rendered elements to verify visible behavior.
    Use tools.inspect('validate.render') for a runnable example.
    """
    try:
        return _success(await owner.validate_pr76_render(request))
    except Exception as exc:
        return _failure(exc, "VALIDATION_UNAVAILABLE")


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
    """Validate and persist a complete Sprite draft."""
    try:
        return _success(await owner.create_pr76_sprite(request.sprite))
    except Exception as exc:
        return _failure(exc, "SPRITE_STORE_FAILED")


@tool(
    "tools.inspect",
    constraints=["The name is exact; inspection never performs discovery or executes the inspected tool."],
    side_effects=["registry read only"],
    error_codes=["INVALID_ARGUMENT", "TOOL_NOT_FOUND"],
    examples=[{"input": {"tool_name": "image.info"}, "output": {"ok": False, "error": {"code": "TOOL_NOT_FOUND", "message": "example"}}}],
)
async def tools_inspect(owner, request: ToolInspectInput) -> ToolResult[ToolDescriptor]:
    """Return one exact registered tool descriptor."""
    try:
        return _success(get_tool(request.tool_name).describe())
    except ToolFault as exc:
        return _failure(exc)


@dataclass(frozen=True)
class PlanTool:
    """Host-owned orchestration control exposed only to Outer and Plan ReAct."""

    name: str = "tools.plan_execute"
    input: type = PlanAction

    def wire(self) -> dict[str, Any]:
        """Expose the Plan transition schema as a normal provider function."""
        return {
            "type": "function",
            "function": {
                "name": self.name.replace(".", "_"),
                "description": "Create, continue, advance or finish the ordered Plan; never executes a business tool.",
                "parameters": self.input.model_json_schema(),
            },
        }

    def describe(self) -> dict[str, Any]:
        """Describe the orchestration control without pretending it is a PR76 business tool."""
        return {
            "tool_id": self.name,
            "version": 1,
            "description": "Host-owned Plan transition control.",
            "input_schema": self.input.model_json_schema(),
            "writes": False,
            "available": True,
        }


PLAN_TOOL = PlanTool()


def available(modules=None, *, executor=False):
    """Return exact PR76 tools filtered by Plan module and Executor permissions."""
    tools = []
    if not executor and (modules is None or "tools" in modules):
        tools.append(PLAN_TOOL)
    for item in registered_tools():
        module = item.name.split(".", 1)[0]
        if modules is None or module in modules or item.name == "tools.inspect":
            if executor and item.name == "tools.plan_execute":
                continue
            tools.append(item)
    return tools


def resolve(name: str, modules=None, *, executor=False):
    """Resolve one allowed dotted or provider-wire name."""
    for item in available(modules, executor=executor):
        if name in {item.name, item.name.replace(".", "_")}:
            return item
    raise ValueError("Unknown or out-of-scope tool")
