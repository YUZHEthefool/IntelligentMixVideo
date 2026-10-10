"""共用视频项目 HTTP/SQLite 回归：原子保存、冲突、数据隔离；pytest 无需模型或真实 MySQL。"""

from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from generated.imv.template.v1 import template_pb2
from server.projects import store as project_store
from server.remotion_templates.store import Conflict, Store
from .test_remotion_sprite_publish import published, published_sprite
from .template_wire import post_template


@pytest.fixture
def template_asset(client, published):
    """发布真实离线资产供项目引用，整个测试不接触生产数据。"""
    asset = published_sprite(client, published.version.id)
    return published.store, asset.sprite_id


def draft(sprite_id, **changes):
    """只使用 Remotion 字段；服务端推导固定资产时长，不接收 IMS 目标或样式。"""
    return {"name": "独立 Remotion", "media": None, "tracks": [],
            "expected_revision": 0, "clips": [{"id": "clip-1", "sprite_id": sprite_id, "start": 2}], **changes}


def test_independent_template_roundtrip_and_ims_isolation(client, template_asset, template_payload):
    """不创建 IMS 即可保存；同 UUID 的两个库也不关联，双向删除互不影响。"""
    _store, asset_id = template_asset
    ims = post_template(client, template_payload)
    identifier = template_pb2.SaveTemplateResponse.FromString(ims.content).template.template_id
    path = f"/api/projects/{identifier}"
    result = client.put(path, json=draft(asset_id))
    assert result.status_code == 200
    saved = result.json()
    assert saved["id"] == identifier and saved["revision"] == 1
    assert saved["clips"] == [{"id": "clip-1", "sprite_id": asset_id, "start": 2, "duration": 1}]
    assert client.get(path).json() == saved
    assert client.get("/api/projects").json() == [saved]
    assert client.delete(f"/template/{identifier}").status_code == 204
    assert client.get(path).json() == saved
    # 项目删除后资产仍可预览，IMS 的另一个模板仍存在。
    other = template_pb2.SaveTemplateResponse.FromString(post_template(client, template_payload).content).template.template_id
    assert client.delete(path, params={"expected_revision": 1}).status_code == 204
    assert client.get(path).status_code == 404
    assert client.get(f"/template/{other}").status_code == 200
    assert client.get(f"/api/sprites/{asset_id}/preview").status_code == 200
    assert client.get(f"/api/sprites/styles/{other}").status_code == 404


def test_single_save_needs_no_ims_and_preserves_revision_on_failure(client, template_asset):
    """项目元数据和片段同一次写入；无效资产或过期版本不改变已保存数据。"""
    store, asset_id = template_asset
    path = f"/api/projects/{uuid4()}"
    initial = client.put(path, json=draft(asset_id)).json()
    assert template_pb2.ListTemplatesResponse.FromString(client.get("/template").content).templates == []
    invalid = draft(str(uuid4()), expected_revision=1, name="不能部分保存")
    assert client.put(path, json=invalid).status_code == 422
    assert client.get(path).json() == initial
    assert client.put(path, json=draft(asset_id)).status_code == 409
    assert client.delete(path, params={"expected_revision": 9}).status_code == 409
    updated = client.put(path, json=draft(asset_id, clips=[], expected_revision=1))
    assert updated.status_code == 200 and updated.json()["revision"] == 2
    reopened = Store(store.root)
    reopened.initialize()
    assert len(project_store.list_projects(reopened)) == 1
    assert project_store.list_projects(reopened)[0].clips == []


@pytest.mark.parametrize("change", [
    {"name": " "}, {"media": {"url": "http://test/video", "width": 0, "height": 1080, "duration": 10}}, {"tracks": [{}]}, {"media": {"url": "file:///secret", "width": 1920, "height": 1080, "duration": 10}},
    {"expected_revision": -1}, {"style_id": str(uuid4())},
    {"clips": [{"id": "x", "sprite_id": str(uuid4()), "start": -1}]},
    {"clips": [{"id": "x", "sprite_id": str(uuid4()), "start": 0, "duration": 9}]},
])
def test_invalid_template_does_not_create_a_record(client, template_asset, change):
    """非法时间、画布、额外 IMS 字段或伪造时长返回 422 且不写入。"""
    _store, asset_id = template_asset
    path = f"/api/projects/{uuid4()}"
    assert client.put(path, json=draft(asset_id, **change)).status_code == 422
    assert client.get(path).status_code == 404


def test_concurrent_saves_only_accept_one_revision(client, template_asset):
    """两个编辑器同时首次保存同 ID，只允许一个成功，不覆盖另一个编辑器的片段。"""
    store, asset_id = template_asset
    identifier = uuid4()
    barrier = Barrier(2, timeout=5)

    def save(name):
        """并发执行真实 SQLite 事务，返回成功版本或明确的版本冲突。"""
        barrier.wait()
        try:
            return project_store.save_project(store, identifier, project_store.SaveProject(**draft(asset_id, name=name))).revision
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["A", "B"]))
    assert results.count(1) == results.count("conflict") == 1
    assert project_store.get_project(store, identifier).revision == 1


def test_mixed_project_persists_one_media_and_both_track_types(client, template_asset, template_payload):
    """IMS 和 Remotion 共用同一媒体/画布，首次保存及更新均在一份 revision 中往返。"""
    _store, asset_id = template_asset
    path = f"/api/projects/{uuid4()}"
    media = {"url": "https://example.test/source.mp4", "width": 1920, "height": 1080, "duration": 20}
    payload = draft(asset_id, media=media, tracks=template_payload["tracks"])
    response = client.put(path, json=payload)
    assert response.status_code == 200
    saved = response.json()
    assert saved["media"] == media and len(saved["tracks"]) == len(saved["clips"]) == 1
    assert saved["tracks"][0]["editor"]["titleIn"] == "in/fade_in"
    media = {**media, "width": 1080, "height": 1920, "duration": 5}
    changed = client.put(path, json=draft(asset_id, media=media, tracks=saved["tracks"], expected_revision=1))
    assert changed.status_code == 200
    assert client.get(path).json() == changed.json()
    assert changed.json()["media"] == media and changed.json()["revision"] == 2
    assert changed.json()["clips"] == saved["clips"]
    assert template_pb2.ListTemplatesResponse.FromString(client.get("/template").content).templates == []


def test_invalid_ims_effect_cannot_partially_save_project(client, template_asset, template_payload):
    """未知 IMS 效果不得随合法 Remotion 片段写入项目，现有数据保持原样。"""
    _store, asset_id = template_asset
    path = f"/api/projects/{uuid4()}"
    saved = client.put(path, json=draft(asset_id)).json()
    template_payload["tracks"][0]["editor"]["titleIn"] = "in/does-not-exist"
    assert client.put(path, json=draft(asset_id, tracks=template_payload["tracks"], expected_revision=1)).status_code == 422
    assert client.get(path).json() == saved
