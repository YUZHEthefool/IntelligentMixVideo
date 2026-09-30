"""Focused tests for Preset creation, Sprite composition, persistence and preview publication."""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.remotion_templates.provider import Budget
from server.remotion_templates.settings import Settings
from server.remotion_templates.tools.catalog import available
from server.remotion_templates.tools.contracts import (
    CodeValidationReport,
    ComponentDefinition,
    PresetDraft,
    SpriteComposeInput,
    SpriteCreateInput,
)
from server.remotion_templates.tools.registry import registered_tools
from server.remotion_templates.tools.session import ToolSession


RENDERER_DEPS = Path(__file__).parents[1] / "src" / "server" / "remotion" / "node_modules" / "esbuild"


def session(tmp_path: Path) -> ToolSession:
    """Build a creation-only session without a model or browser dependency."""
    settings = Settings(_env_file=None, data_dir=tmp_path)
    harness = SimpleNamespace(settings=settings, renderer=None)
    return ToolSession(harness, None, None, Budget(), tmp_path / "run", [], lambda *_: None, {})


def valid_report() -> CodeValidationReport:
    """Return a deterministic host report for data-only composition tests."""
    return CodeValidationReport(passed=True, diagnostics=[])


def patch_validation(current: ToolSession) -> None:
    """Replace isolated browser validation for the no-browser unit path."""
    async def validate(_component: ComponentDefinition) -> CodeValidationReport:
        """Keep the test focused on the creation catalog and source integrity."""
        return valid_report()

    current.validate_pr76_code = validate


def draft() -> PresetDraft:
    """Return a minimal valid title Preset."""
    return PresetDraft(
        description="title",
        code="export default function Label(){return <div>Title</div>}",
        parameter_schema={"type": "object", "properties": {}, "additionalProperties": False},
        default_parameters={},
    )


def test_full_catalog_is_registered_but_only_implemented_tools_are_public():
    """The documented catalog registers eleven tools; deferred ones stay out of the model window."""
    names = {item.name for item in registered_tools()}
    assert names == {
        "image.info", "image.resize", "image.crop",
        "preset.search", "preset.create", "preset.modify",
        "validate.code", "validate.render", "sprite.compose", "sprite.create",
        "tools.inspect",
    }
    implemented = {item.name for item in registered_tools() if item.implemented}
    assert implemented == {"preset.create", "sprite.compose", "sprite.create", "tools.inspect"}
    assert {item.name for item in available()} == implemented | {"tools.plan_execute"}


@pytest.mark.skipif(not RENDERER_DEPS.exists(), reason="install locked Remotion renderer dependencies")
def test_creation_flow_persists_one_sprite_without_semantic_index(tmp_path):
    """Preset creation, composition and Sprite storage work without ChromaDB or model calls."""
    async def run():
        current = session(tmp_path)
        patch_validation(current)
        preset = await current.execute("preset.create", draft(), available())
        composed = await current.execute(
            "sprite.compose",
            SpriteComposeInput.model_validate({
                "description": "title preview",
                "instances": [{
                    "instance_id": "title",
                    "source": {"kind": "stored", "preset_id": preset["preset"]["preset_id"]},
                    "layout": {"x": 0, "y": 0, "width": 1080, "height": 1920, "z_index": 0},
                    "timing": {"start_frame": 0, "duration_frames": 30},
                }],
            }),
            available(),
        )
        saved = await current.execute("sprite.create", SpriteCreateInput.model_validate(composed), available())
        assert saved["sprite"]["code"] == composed["sprite"]["code"]
        assert len(current.saved_sprites) == 1
        assert len(current.catalog.read_sprites()) == 1

    asyncio.run(run())


@pytest.mark.skipif(os.environ.get("IMV_TEST_RENDERER") != "1", reason="set IMV_TEST_RENDERER=1 for Linux preview integration")
def test_real_creation_flow_builds_preview(tmp_path):
    """Linux integration verifies the saved Sprite produces Export.tsx and interactive.js."""
    from server.remotion_templates.harness import Harness
    from server.remotion_templates.renderer import Renderer

    # The autouse isolation fixture strips IMV_* variables, so read the renderer
    # locations this run was configured with before building the settings object.
    configured = {
        name: Path(value)
        for name, value in (
            ("browser_executable", os.environ.get("IMV_BROWSER_EXECUTABLE")),
            ("font_regular", os.environ.get("IMV_FONT_REGULAR")),
            ("font_bold", os.environ.get("IMV_FONT_BOLD")),
        )
        if value
    }
    settings = Settings(_env_file=None, data_dir=tmp_path, **configured)
    renderer = Renderer(settings)
    harness = Harness(SimpleNamespace(settings=settings), renderer)

    async def run():
        current = ToolSession(harness, None, None, Budget(), tmp_path / "run", [], lambda *_: None, {})
        preset = await current.execute("preset.create", draft(), available())
        composed = await current.execute("sprite.compose", SpriteComposeInput.model_validate({
            "description": "title preview",
            "instances": [{
                "instance_id": "title",
                "source": {"kind": "stored", "preset_id": preset["preset"]["preset_id"]},
                "layout": {"x": 0, "y": 0, "width": 1080, "height": 1920, "z_index": 0},
                "timing": {"start_frame": 0, "duration_frames": 30},
            }],
        }), available())
        saved = await current.execute("sprite.create", SpriteCreateInput.model_validate(composed), available())
        result = await harness.finalize_sprite(current, saved["sprite"]["sprite_id"], Budget(), tmp_path)
        assert (result[3] / "Export.tsx").stat().st_size > 0
        assert (result[3] / "interactive.js").stat().st_size > 0

    asyncio.run(run())


def test_deferred_tools_refuse_instead_of_fabricating():
    """延后实现的工具仍可查询契约，但调用只返回明确错误，不伪造成功结果。"""
    asyncio.run(_deferred_scenario())


async def _deferred_scenario():
    """逐个调用延后工具，确认统一返回 NOT_IMPLEMENTED 与自身名称。"""
    from server.remotion_templates.tools.registry import get_tool

    deferred = {
        "image.info": {"image": {"asset_id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301"}},
        "preset.search": {"query": "渐显标题"},
        "validate.code": {"component": {"code": "export default function C(){return null}", "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": False}, "default_parameters": {}}},
    }
    for name, values in deferred.items():
        tool = get_tool(name)
        result = await tool.invoke(None, tool.input.model_validate(values))
        assert result["ok"] is False
        assert result["error"]["code"] == "NOT_IMPLEMENTED"
        assert name in result["error"]["message"]


def test_deferred_tools_stay_out_of_the_model_window():
    """延后工具不得出现在任何一层的工具列表里。"""
    skipped = [item.name for item in available() if item.name in {"image.info", "preset.search", "validate.code"}]
    assert skipped == []


def test_mysql_preset_create_persists_through_the_catalog_store(tmp_path):
    """preset.create 经目录存储写入；数据库不可用时仍能在本地目录读回。"""
    async def run():
        """用仅创建模式的会话保存预设，再从同一目录重新读取。"""
        current = session(tmp_path)
        patch_validation(current)
        saved = await current.execute("preset.create", draft(), available())
        assert current.catalog_backend in {"mysql", "local"}
        assert current.catalog.find_preset(saved["preset"]["preset_id"]).description == "title"

    asyncio.run(run())
