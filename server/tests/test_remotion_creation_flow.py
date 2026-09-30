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


def session(tmp_path: Path) -> ToolSession:
    """Build a creation-only session without a model or browser dependency."""
    settings = Settings(_env_file=None, data_dir=tmp_path, creation_only=True)
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


def test_only_creation_tools_are_public():
    """The focused build does not expose image, search or validation business tools."""
    names = {item.name for item in registered_tools()}
    assert names == {"preset.create", "sprite.compose", "sprite.create", "tools.inspect"}
    assert {item.name for item in available()} == names | {"tools.plan_execute"}


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
        assert len(current._read_records("sprites", type(current.saved_sprites[next(iter(current.saved_sprites))]))) == 1

    asyncio.run(run())


@pytest.mark.skipif(os.environ.get("IMV_TEST_RENDERER") != "1", reason="set IMV_TEST_RENDERER=1 for Linux preview integration")
def test_real_creation_flow_builds_preview(tmp_path):
    """Linux integration verifies the saved Sprite produces Export.tsx and interactive.js."""
    from server.remotion_templates.harness import Harness
    from server.remotion_templates.renderer import Renderer

    settings = Settings(_env_file=None, data_dir=tmp_path)
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
