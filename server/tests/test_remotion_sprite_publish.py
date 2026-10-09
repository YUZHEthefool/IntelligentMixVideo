"""Remotion 字效保存为 Sprite 资产：发布、目录、预览与云端模板绑定的真实 SQLite/文件/HTTP 回归。

不访问模型、浏览器或 MySQL（模板库使用 conftest 的临时 SQLite）；发布版本由离线渲染替身落盘。
在 server/ 目录执行 `uv run --locked pytest tests/test_remotion_sprite_publish.py -v`。
"""

import asyncio
import json
import shutil
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from generated.imv.sprite.v1 import sprite_pb2 as pb
from sqlalchemy import Engine, select

from server.app import app
from server.remotion_templates.harness import Harness
from server.remotion_templates.models import GenerateTemplateRequest
from server.remotion_templates.provider import Budget
from server.remotion_templates.settings import Settings
from server.remotion_templates.sprite_router import sprite_runtime
from server.remotion_templates.store import Store
from server.remotion_templates.tools.contracts import SpriteDraft
from server.template import store as template_store

from .conftest import template_track
from .test_remotion_version_diagnostics import (
    CodeOnlyRenderer,
    OfflineRenderer,
    _SavedSprite,
    runtime_report,
)

PROTOBUF = {"Content-Type": "application/x-protobuf"}
SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "keywords": {"type": "string"},
        "color": {"type": "string", "title": "文字颜色"},
        "size": {"type": "number", "minimum": 12, "maximum": 300},
        "weight": {"type": "integer", "enum": [400, 700]},
        "shadow": {"type": "boolean"},
    },
    "required": ["text", "keywords", "color", "size", "weight", "shadow"],
    "additionalProperties": False,
}
DEFAULTS = {"text": "标题", "keywords": "", "color": "#ffffff", "size": 64, "weight": 400, "shadow": False}
CODE = 'import React from "react";\nexport default function Sprite(p: {text: string}) { return <div>{p.text}</div>; }\n'


class BundleRebuilder:
    """记录重建请求的渲染替身：写出带同步标记的新预览包，或按要求失败；不执行真实浏览器或沙箱。"""

    def __init__(self):
        """默认成功，requests 保存宿主写给 worker 的请求。"""
        self.requests: list[dict] = []
        self.failure: Exception | None = None

    async def run_worker(self, directory, *, worker=None, timeout_seconds=None):
        """只接受预览包构建；失败时不写任何文件。"""
        assert worker == "presentation-worker.mjs"
        self.requests.append(json.loads((directory / "request.json").read_text()))
        if self.failure:
            raise self.failure
        (directory / "interactive.js").write_text("// rebuilt imv-preview-sync")
        return {}


NESTED_SCHEMA = {
    "type": "object",
    "properties": {"title_main": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "title": "标题文字"},
            "fontSize": {"type": "number", "title": "字号", "minimum": 8, "maximum": 500},
            "textColor": {"type": "string", "title": "文字颜色"},
        },
        "required": ["title", "fontSize", "textColor"],
        "additionalProperties": False,
    }},
    "required": ["title_main"],
    "additionalProperties": False,
}
NESTED_DEFAULTS = {"title_main": {"title": "今日灵感", "fontSize": 160, "textColor": "#FFD400"}}


@pytest.fixture
def published(tmp_path):
    """发布一个带扁平标量参数的成功版本，并让主应用的 Sprite 路由使用同一份临时数据。"""
    yield from published_version(tmp_path, SCHEMA, DEFAULTS)


@pytest.fixture
def nested_published(tmp_path):
    """发布组合 Sprite 常见的嵌套参数版本：业务文字位于 title_main.title。"""
    yield from published_version(tmp_path, NESTED_SCHEMA, NESTED_DEFAULTS)


def published_version(tmp_path, schema, defaults):
    """用离线渲染替身封存一个成功版本，并在使用结束后恢复路由依赖。"""
    font = tmp_path / "font.ttc"
    font.write_bytes(b"fixture-font")
    settings = Settings(_env_file=None, data_dir=tmp_path / "state", font_regular=font, font_bold=font)
    harness = Harness(SimpleNamespace(settings=settings), OfflineRenderer(settings, CodeOnlyRenderer(settings)))
    store = Store(settings.data_dir)
    store.initialize()
    sprite = SpriteDraft(
        description="标题字效",
        code=CODE,
        parameter_schema=schema,
        default_parameters=defaults,
        composition={"width": 1080, "height": 1920, "fps": 30, "duration_frames": 30},
        instances=[{
            "instance_id": "title",
            "preset": {"code": CODE, "parameter_schema": schema, "default_parameters": defaults, "description": "标题"},
            "parameters": defaults,
            "layout": {"x": 0, "y": 0, "width": 1080, "height": 1920, "z_index": 0},
            "timing": {"start_frame": 0, "duration_frames": 30},
        }],
    )
    _work, job = store.create(GenerateTemplateRequest(description="标题"))
    store.claim()
    result = asyncio.run(harness.finalize_sprite(
        SimpleNamespace(saved_sprite=lambda _id: _SavedSprite(sprite), validation_for=lambda _r: runtime_report(sprite)),
        "saved", Budget(), store.job_dir(job.id),
    ))
    version = store.publish(job.id, *result)
    renderer = BundleRebuilder()
    service = SimpleNamespace(store=store, settings=settings, harness=SimpleNamespace(renderer=renderer))
    app.dependency_overrides[sprite_runtime] = lambda: service
    yield SimpleNamespace(store=store, version=version, renderer=renderer)
    app.dependency_overrides.pop(sprite_runtime)


def publish_request(version_id, **fields) -> pb.PublishSpriteRequest:
    """默认把版本发布为带关键词字段的文字 Sprite；用例按需覆盖字段。"""
    values = {"kind": pb.SPRITE_KIND_TEXT, "text_prop": "text", "keywords_prop": "keywords", **fields}
    return pb.PublishSpriteRequest(source_version_id=str(version_id), **values)


def publish(client: TestClient, request: pb.PublishSpriteRequest):
    """发送二进制发布请求。"""
    return client.post("/api/sprites/publish", content=request.SerializeToString(), headers=PROTOBUF)


def published_sprite(client: TestClient, version_id, **fields) -> pb.SpriteSummary:
    """发布成功并返回摘要。"""
    response = publish(client, publish_request(version_id, **fields))
    assert response.status_code == 200
    return pb.PublishSpriteResponse.FromString(response.content).sprite


def placement(sprite_id: str, **fields) -> pb.SpritePlacement:
    """默认在成片开头绑定标题；用例按需覆盖字段。"""
    values = {"id": "p1", "target": pb.SPRITE_TARGET_TITLE, "start_mode": "seconds", "start": 0, "order": 0, **fields}
    return pb.SpritePlacement(sprite_id=sprite_id, **values)


def save_bindings(client: TestClient, style_id: str, placements: list, expected_revision: int = 0, body_style_id: str | None = None):
    """整体替换模板的 Sprite 绑定。"""
    request = pb.SaveStyleSpritesRequest(
        style_id=body_style_id or style_id, placements=placements, expected_revision=expected_revision,
    )
    return client.post(f"/api/sprites/styles/{style_id}", content=request.SerializeToString(), headers=PROTOBUF)


def bindings(response) -> pb.StyleSpriteBindings:
    """解码绑定读取/保存响应。"""
    return pb.GetStyleSpritesResponse.FromString(response.content).bindings


def create_style(client: TestClient, template_payload: dict) -> str:
    """创建云端模板并返回其 ID。"""
    from generated.imv.template.v1 import template_pb2 as template_pb
    from .template_wire import post_template

    response = post_template(client, template_payload)
    assert response.status_code == 201
    return template_pb.SaveTemplateResponse.FromString(response.content).template.template_id


def test_publish_copies_content_and_lists_summary_without_source(client: TestClient, published) -> None:
    """发布后目录只含摘要与可编辑参数；文字与关键词字段归总线，不进入参数。"""
    summary = published_sprite(client, published.version.id)
    assert (summary.name, summary.kind, summary.keywords_supported) == ("标题字效", pb.SPRITE_KIND_TEXT, True)
    assert (summary.canvas.width, summary.canvas.height, summary.canvas.fps, summary.canvas.preview_frames) == (1080, 1920, 30, 30)
    assert summary.source_version_id == str(published.version.id)
    parameters = {item.key: item for item in summary.parameters}
    assert set(parameters) == {"color", "size", "weight", "shadow"}
    assert parameters["color"].label == "文字颜色"
    assert (parameters["size"].minimum, parameters["size"].maximum) == (12, 300)
    assert [item.number_value for item in parameters["weight"].allowed_values] == [400, 700]
    assert all(item.access == pb.OPERATOR_ACCESS_VISIBLE_EDITABLE for item in parameters.values())

    listed = client.get("/api/sprites")
    assert listed.status_code == 200
    assert listed.headers["content-type"] == "application/x-protobuf"
    assert [item.sprite_id for item in pb.ListSpritesResponse.FromString(listed.content).sprites] == [summary.sprite_id]
    assert b"export default" not in listed.content
    assert (published.store.root / "sprites" / summary.sprite_id / "interactive.js").is_file()


def test_republishing_returns_the_original_sprite(client: TestClient, published) -> None:
    """相同来源与字段选择重复发布幂等；不同字段选择产生独立资产。"""
    first = published_sprite(client, published.version.id)
    again = published_sprite(client, published.version.id)
    other = published_sprite(client, published.version.id, keywords_prop="")
    assert again.sprite_id == first.sprite_id
    assert other.sprite_id != first.sprite_id and not other.keywords_supported
    assert len(pb.ListSpritesResponse.FromString(client.get("/api/sprites").content).sprites) == 2


def test_published_sprite_survives_deleting_its_source_version(client: TestClient, published) -> None:
    """源版本的封存目录与记录被清理后，目录条目和预览仍来自发布自己的副本。"""
    summary = published_sprite(client, published.version.id)
    shutil.rmtree(published.store.root / "accepted" / str(published.version.id))
    with published.store.connection() as db:
        db.execute("DELETE FROM versions")
    assert pb.ListSpritesResponse.FromString(client.get("/api/sprites").content).sprites[0].sprite_id == summary.sprite_id
    preview = client.get(summary.preview_url)
    assert preview.status_code == 200
    assert "rebuilt imv-preview-sync" in preview.text
    assert "sandbox allow-scripts" in preview.headers["content-security-policy"]


@pytest.mark.parametrize(("fields", "status"), [
    ({"kind": pb.SPRITE_KIND_UNSPECIFIED}, 422),
    ({"text_prop": "size"}, 422),
    ({"text_prop": "missing"}, 422),
    ({"keywords_prop": "text"}, 422),
    ({"keywords_prop": "missing"}, 422),
    ({"kind": pb.SPRITE_KIND_VIDEO_OVERLAY}, 422),
], ids=["no-kind", "non-string-text", "unknown-text", "same-keywords", "unknown-keywords", "visual-with-text-fields"])
def test_publish_rejects_invalid_field_choices(client: TestClient, published, fields, status) -> None:
    """类型必须明确，文字字段必须是字符串参数，视觉类型不能声明文字字段。"""
    response = publish(client, publish_request(published.version.id, **fields))
    assert response.status_code == status
    assert client.get("/api/sprites").content == b""


def test_publish_rejects_unknown_malformed_or_tampered_sources(client: TestClient, published) -> None:
    """未知或格式错误的版本、被改写的封存产物都不能发布。"""
    assert publish(client, publish_request("00000000-0000-4000-8000-000000000000")).status_code == 404
    assert publish(client, publish_request("not-a-uuid")).status_code == 422
    (published.store.root / "accepted" / str(published.version.id) / "interactive.js").write_text("tampered")
    assert publish(client, publish_request(published.version.id)).status_code == 409
    assert client.post("/api/sprites/publish", json={}).status_code == 415
    assert client.post("/api/sprites/publish", content=b"\xff\xff", headers=PROTOBUF).status_code == 400


def test_style_bindings_roundtrip_with_revision_lock(client: TestClient, published, template_payload) -> None:
    """未保存时为版本 0；保存递增 revision，过期 revision 返回 409 且不改动已存绑定。"""
    sprite = published_sprite(client, published.version.id)
    style_id = create_style(client, template_payload)
    empty = client.get(f"/api/sprites/styles/{style_id}")
    assert (bindings(empty).revision, list(bindings(empty).placements)) == (0, [])

    override = pb.SpriteParameterOverride(key="size", value=pb.ScalarValue(number_value=88))
    first = save_bindings(client, style_id, [
        placement(sprite.sprite_id, overrides=[override]),
        placement(sprite.sprite_id, id="p2", target=pb.SPRITE_TARGET_SUBTITLE, start_mode="percent", start=50, order=1, duration=2),
    ])
    assert first.status_code == 200
    saved = bindings(first)
    assert saved.revision == 1 and [item.id for item in saved.placements] == ["p1", "p2"]
    assert saved.placements[0].overrides[0].value.number_value == 88
    assert saved.placements[1].duration == 2 and not saved.placements[0].HasField("duration")

    stale = save_bindings(client, style_id, [], expected_revision=0)
    assert stale.status_code == 409
    again = bindings(client.get(f"/api/sprites/styles/{style_id}"))
    assert again.revision == 1 and len(again.placements) == 2
    cleared = bindings(save_bindings(client, style_id, [], expected_revision=1))
    assert cleared.revision == 2 and list(cleared.placements) == []


@pytest.mark.parametrize("build", [
    lambda sid: [placement(sid, target=pb.SPRITE_TARGET_FILTER)],
    lambda sid: [placement(sid, target=pb.SPRITE_TARGET_UNSPECIFIED)],
    lambda sid: [placement(sid, start_mode="frames")],
    lambda sid: [placement(sid, start_mode="percent", start=100)],
    lambda sid: [placement(sid, start=-1)],
    lambda sid: [placement(sid, duration=0)],
    lambda sid: [placement(sid, order=1)],
    lambda sid: [placement(sid), placement(sid, order=1)],
    lambda sid: [placement(sid, overrides=[pb.SpriteParameterOverride(key="text", value=pb.ScalarValue(string_value="x"))])],
    lambda sid: [placement(sid, overrides=[pb.SpriteParameterOverride(key="size", value=pb.ScalarValue(string_value="big"))])],
    lambda sid: [placement(sid, overrides=[pb.SpriteParameterOverride(key="size", value=pb.ScalarValue(number_value=500))])],
    lambda sid: [placement(sid, overrides=[pb.SpriteParameterOverride(key="weight", value=pb.ScalarValue(number_value=500))])],
    lambda sid: [placement(sid, overrides=[pb.SpriteParameterOverride(key="weight", value=pb.ScalarValue(number_value=400.5))])],
    lambda sid: [placement("00000000-0000-4000-8000-000000000000")],
], ids=[
    "wrong-target", "unspecified-target", "bad-start-mode", "percent-100", "negative-start", "zero-duration",
    "order-gap", "duplicate-id", "bus-owned-override", "wrong-type", "above-maximum", "outside-enum",
    "fractional-integer", "unknown-sprite",
])
def test_invalid_placements_are_rejected_without_saving(client: TestClient, published, template_payload, build) -> None:
    """目标、时间、顺序与样式覆盖任一违规都返回 422，且不产生绑定记录。"""
    sprite = published_sprite(client, published.version.id)
    style_id = create_style(client, template_payload)
    assert save_bindings(client, style_id, build(sprite.sprite_id)).status_code == 422
    assert bindings(client.get(f"/api/sprites/styles/{style_id}")).revision == 0


def test_boundary_targets_need_duration_and_subtitle_needs_keywords(client: TestClient, published, template_payload) -> None:
    """视觉 Sprite 的入场必须指定时长；未验收关键词高亮的文字 Sprite 不能绑定字幕。"""
    visual = published_sprite(client, published.version.id, kind=pb.SPRITE_KIND_VIDEO_OVERLAY, text_prop="", keywords_prop="")
    plain_text = published_sprite(client, published.version.id, keywords_prop="")
    style_id = create_style(client, template_payload)
    enter = placement(visual.sprite_id, target=pb.SPRITE_TARGET_VIDEO_ENTER)
    assert save_bindings(client, style_id, [enter]).status_code == 422
    enter.duration = 1.5
    assert save_bindings(client, style_id, [enter]).status_code == 200
    subtitle = placement(plain_text.sprite_id, target=pb.SPRITE_TARGET_SUBTITLE)
    assert save_bindings(client, style_id, [subtitle], expected_revision=1).status_code == 422


def test_binding_routes_reject_unknown_styles_and_mismatched_bodies(client: TestClient, published, template_payload) -> None:
    """模板不存在返回 404；请求体 style_id 与路径不一致返回 422。"""
    sprite = published_sprite(client, published.version.id)
    missing = "00000000-0000-4000-8000-000000000000"
    assert client.get(f"/api/sprites/styles/{missing}").status_code == 404
    assert save_bindings(client, missing, [placement(sprite.sprite_id)]).status_code == 404
    style_id = create_style(client, template_payload)
    assert save_bindings(client, style_id, [], body_style_id=missing).status_code == 422
    assert client.post(f"/api/sprites/styles/{style_id}", json={}).status_code == 415


def test_deleting_a_template_removes_its_bindings(client: TestClient, template_db: Engine, published, template_payload) -> None:
    """删除云端模板同一事务清除其绑定，但保留已发布 Sprite 资产。"""
    sprite = published_sprite(client, published.version.id)
    style_id = create_style(client, template_payload)
    assert save_bindings(client, style_id, [placement(sprite.sprite_id)]).status_code == 200
    assert client.delete(f"/template/{style_id}").status_code == 204
    with template_db.connect() as connection:
        assert connection.execute(select(template_store.sprite_bindings)).all() == []
    assert len(pb.ListSpritesResponse.FromString(client.get("/api/sprites").content).sprites) == 1


def test_nested_parameters_publish_with_dot_paths_and_validate_overrides(client: TestClient, nested_published, template_payload) -> None:
    """组合 Sprite 的业务文字在嵌套对象里：用点号路径发布，文字字段不入参数，覆盖按嵌套值校验。"""
    summary = published_sprite(client, nested_published.version.id, text_prop="title_main.title", keywords_prop="")
    assert {item.key for item in summary.parameters} == {"title_main.fontSize", "title_main.textColor"}
    size = next(item for item in summary.parameters if item.key == "title_main.fontSize")
    assert (size.minimum, size.maximum, size.default_value.number_value) == (8, 500, 160)

    style_id = create_style(client, template_payload)
    ok = pb.SpriteParameterOverride(key="title_main.fontSize", value=pb.ScalarValue(number_value=200))
    assert save_bindings(client, style_id, [placement(summary.sprite_id, overrides=[ok])]).status_code == 200
    for key, value in [
        ("title_main.fontSize", pb.ScalarValue(number_value=900)),
        ("title_main.title", pb.ScalarValue(string_value="x")),
        ("title_main", pb.ScalarValue(string_value="x")),
    ]:
        bad = pb.SpriteParameterOverride(key=key, value=value)
        assert save_bindings(client, style_id, [placement(summary.sprite_id, overrides=[bad])], expected_revision=1).status_code == 422


@pytest.mark.parametrize("text_prop", ["title", "title_main", "title_main.missing", "title_main.fontSize"], ids=["flat-name-of-nested", "object", "unknown-path", "non-string"])
def test_nested_publish_rejects_wrong_text_paths(client: TestClient, nested_published, text_prop) -> None:
    """文字字段必须是真实存在的嵌套字符串叶子，顶层同名、对象或数字字段都被拒绝。"""
    assert publish(client, publish_request(nested_published.version.id, text_prop=text_prop, keywords_prop="")).status_code == 422


def test_overlay_preview_is_transparent_and_serves_managed_fonts(client: TestClient, published) -> None:
    """模板编辑叠加使用透明背景页；普通预览保留检查棋盘格。字体路由随页面相对路径可用，缺失资产或字重返回 404。"""
    summary = published_sprite(client, published.version.id)
    plain = client.get(summary.preview_url)
    overlay = client.get(summary.preview_url, params={"overlay": "true"})
    assert "conic-gradient" in plain.text and "conic-gradient" not in overlay.text
    assert "background:transparent" in overlay.text
    assert "sandbox allow-scripts" in overlay.headers["content-security-policy"]
    font = client.get(f"/api/sprites/{summary.sprite_id}/fonts/400")
    assert (font.status_code, font.content) == (200, b"fixture-font")
    assert font.headers["access-control-allow-origin"] == "*"
    assert client.get(f"/api/sprites/{summary.sprite_id}/fonts/500").status_code == 404
    assert client.get("/api/sprites/00000000-0000-4000-8000-000000000000/fonts/400").status_code == 404


def test_stale_player_bundle_is_rebuilt_from_sealed_source(client: TestClient, published) -> None:
    """封存包缺少同步支持时发布会用封存的源码、默认参数和画布重建；原版本目录不被改动。"""
    summary = published_sprite(client, published.version.id)
    request = published.renderer.requests[0]
    assert request["code"] == published.version.candidate.tsx_code
    assert request["config"] == published.version.candidate.default_config
    assert request["composition"]["duration_in_frames"] == 30
    copied = published.store.root / "sprites" / summary.sprite_id / "interactive.js"
    assert b"imv-preview-sync" in copied.read_bytes()
    assert b"offline Player fixture" in (published.store.root / "accepted" / str(published.version.id) / "interactive.js").read_bytes()
    assert not [item for item in (published.store.root / "sprites").iterdir() if item.name.startswith(".build-")]


def test_current_sealed_bundle_is_copied_without_rebuilding(client: TestClient, published) -> None:
    """封存包已含同步支持时直接复制，不启动任何构建。"""
    (published.store.root / "accepted" / str(published.version.id) / "interactive.js").write_text("// imv-preview-sync")
    from server.remotion_templates.evidence import digest
    published.version.validation.artifacts["interactive.js"] = digest(published.store.root / "accepted" / str(published.version.id) / "interactive.js")
    with published.store.connection() as db:
        db.execute("UPDATE versions SET data=? WHERE id=?", (published.version.model_dump_json(), str(published.version.id)))
    summary = published_sprite(client, published.version.id)
    assert published.renderer.requests == []
    assert client.get(summary.preview_url).text.count("imv-preview-sync") == 1


def test_rebuild_failure_still_saves_and_republishing_refreshes_the_old_copy(client: TestClient, published) -> None:
    """重建失败不阻止保存（仅无法叠加预览）；之后重新保存同一资产会把旧副本刷新为新包，其余内容不变。"""
    published.renderer.failure = RuntimeError("sandbox unavailable")
    first = published_sprite(client, published.version.id)
    assert "offline Player fixture" in client.get(first.preview_url).text
    published.renderer.failure = None
    again = published_sprite(client, published.version.id)
    assert again.sprite_id == first.sprite_id
    assert "rebuilt imv-preview-sync" in client.get(first.preview_url).text
    assert len(pb.ListSpritesResponse.FromString(client.get("/api/sprites").content).sprites) == 1
