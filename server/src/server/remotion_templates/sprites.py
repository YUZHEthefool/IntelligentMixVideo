"""Publish accepted Remotion versions as immutable Sprites and validate their template placements.

A publication copies the sealed source, parameter contract and interactive player bundle out of the
chat-owned version directory, so deleting or editing the source work never changes a bound Sprite.
Records live in the Remotion SQLite database as `imv.sprite.v1.PublishedSprite` JSON; placement
validation reads them but never mutates one. HTTP framing lives in `sprite_router.py`.
"""

import hashlib
import json
import logging
import math
import shutil
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException
from generated.imv.sprite.v1 import sprite_pb2 as pb
from google.protobuf.json_format import MessageToDict, ParseDict
from jsonschema import ValidationError

from .evidence import digest, verify_artifacts
from .store import Conflict, NotFound, Store
from .tools.schema import validate_parameters

MAX_PLACEMENTS = 100
PREVIEW_BUNDLE = "interactive.js"
# 只有包含逐帧同步处理的预览包才能叠加到模板预览上；更早构建的包缺少此标记。
SYNC_MARKER = b"imv-preview-sync"

# 版本创建时的内容类型与发布类型的对应；composition 版本不固定类型，由发布请求选择。
_VERSION_KINDS = {
    "text": pb.SPRITE_KIND_TEXT,
    "subtitle": pb.SPRITE_KIND_TEXT,
    "filter_overlay": pb.SPRITE_KIND_FILTER_OVERLAY,
    "video_overlay": pb.SPRITE_KIND_VIDEO_OVERLAY,
    "transition_overlay": pb.SPRITE_KIND_TRANSITION_OVERLAY,
}
# 每种发布类型允许绑定的作用对象。
_KIND_TARGETS = {
    pb.SPRITE_KIND_TEXT: {pb.SPRITE_TARGET_TITLE, pb.SPRITE_TARGET_SUBTITLE},
    pb.SPRITE_KIND_FILTER_OVERLAY: {pb.SPRITE_TARGET_FILTER},
    pb.SPRITE_KIND_VIDEO_OVERLAY: {
        pb.SPRITE_TARGET_VIDEO_EFFECT, pb.SPRITE_TARGET_VIDEO_ENTER, pb.SPRITE_TARGET_VIDEO_EXIT,
    },
    pb.SPRITE_KIND_TRANSITION_OVERLAY: {pb.SPRITE_TARGET_TRANSITION},
}
# 这些作用对象由总线按片段边界触发，必须给出固定时长。
_DURATION_REQUIRED = {
    pb.SPRITE_TARGET_TRANSITION, pb.SPRITE_TARGET_VIDEO_ENTER, pb.SPRITE_TARGET_VIDEO_EXIT,
}


def _invalid(message: str) -> HTTPException:
    """Report a request that is well-formed protobuf but violates the Sprite contract."""
    return HTTPException(422, message)


def _scalar(kind: str, value) -> pb.ScalarValue | None:
    """Wrap a JSON value only when it has exactly the type its schema declares."""
    if kind == "string" and isinstance(value, str):
        return pb.ScalarValue(string_value=value)
    if kind in {"number", "integer"} and isinstance(value, (int, float)) and not isinstance(value, bool):
        return pb.ScalarValue(number_value=float(value))
    if kind == "boolean" and isinstance(value, bool):
        return pb.ScalarValue(bool_value=value)
    return None


def _nodes(schema: dict, prefix: str = ""):
    """Yield (dot path, definition) for every declared property, descending through nested objects.

    Property names containing a dot cannot be addressed unambiguously and are skipped.
    """
    for name, definition in schema.get("properties", {}).items():
        if "." in name or not isinstance(definition, dict):
            continue
        path = f"{prefix}{name}"
        yield path, definition
        if definition.get("type") == "object":
            yield from _nodes(definition, f"{path}.")


def _definition(schema: dict, path: str) -> dict | None:
    """Resolve one dot path to its schema definition, or None when it is not declared."""
    return next((definition for found, definition in _nodes(schema) if found == path), None)


def _lookup(values: dict, path: str):
    """Read a dot path from nested configuration; a missing step yields None."""
    for part in path.split("."):
        if not isinstance(values, dict) or part not in values:
            return None
        values = values[part]
    return values


def _assign(values: dict, path: str, value) -> dict:
    """Return a copy of nested configuration with one dot path replaced."""
    result = json.loads(json.dumps(values))
    *parents, leaf = path.split(".")
    node = result
    for part in parents:
        node = node.setdefault(part, {})
    node[leaf] = value
    return result


def _parameters(schema: dict, defaults: dict, reserved: set[str]) -> list[pb.SpriteParameter]:
    """Expose scalar controls at any depth as editable parameters keyed by dot path.

    Bus-owned fields (text, keywords) and structured values are skipped.
    """
    result = []
    for key, definition in _nodes(schema):
        if key in reserved:
            continue
        kind = definition.get("type")
        default = _scalar(kind, _lookup(defaults, key))
        if default is None:
            continue
        parameter = pb.SpriteParameter(
            key=key,
            label=str(definition.get("title") or key)[:100],
            access=pb.OPERATOR_ACCESS_VISIBLE_EDITABLE,
            default_value=default,
        )
        if kind in {"number", "integer"}:
            for bound in ("minimum", "maximum"):
                if isinstance(definition.get(bound), (int, float)) and not isinstance(definition[bound], bool):
                    setattr(parameter, bound, float(definition[bound]))
        for item in definition.get("enum", []):
            allowed = _scalar(kind, item)
            if allowed is not None:
                parameter.allowed_values.append(allowed)
        result.append(parameter)
    return result


def _sprite_from(row: sqlite3.Row) -> pb.PublishedSprite:
    """Restore a stored publication and refuse source bytes that no longer match their hash."""
    sprite = ParseDict(json.loads(row["data"]), pb.PublishedSprite())
    if hashlib.sha256(sprite.tsx_code.encode()).hexdigest() != sprite.code_sha256:
        raise Conflict("Published Sprite failed integrity verification.")
    return sprite


def get(store: Store, sprite_id: str) -> pb.PublishedSprite:
    """Read one publication by ID; unknown or malformed IDs are a 404."""
    try:
        identifier = str(UUID(sprite_id))
    except ValueError:
        raise NotFound("sprite not found") from None
    with store.connection() as db:
        row = db.execute("SELECT data FROM sprites WHERE id=?", (identifier,)).fetchone()
    if row is None:
        raise NotFound("sprite not found")
    return _sprite_from(row)


def summarize(sprite: pb.PublishedSprite) -> pb.SpriteSummary:
    """Project a publication onto the public catalog entry, never including TSX."""
    return pb.SpriteSummary(
        sprite_id=sprite.sprite_id,
        name=sprite.name,
        kind=sprite.kind,
        canvas=sprite.canvas,
        parameters=sprite.parameters,
        source_version_id=sprite.source_version_id,
        preview_url=f"/api/sprites/{sprite.sprite_id}/preview",
        keywords_supported=bool(sprite.keywords_prop),
    )


def catalog(store: Store) -> list[pb.SpriteSummary]:
    """List publications newest first."""
    with store.connection() as db:
        rows = db.execute("SELECT data FROM sprites ORDER BY published_at DESC, id").fetchall()
    return [summarize(_sprite_from(row)) for row in rows]


def preview_script(store: Store, sprite_id: str) -> str:
    """Read the sprite's own copy of the player bundle after checking it against the published hash."""
    sprite = get(store, sprite_id)
    path = store.root / "sprites" / sprite.sprite_id / PREVIEW_BUNDLE
    try:
        if digest(path) != sprite.preview_sha256:
            raise ValueError("preview changed")
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise NotFound("sprite preview unavailable") from exc


def _validated_request(request: pb.PublishSpriteRequest, schema: dict, version_kind: str) -> None:
    """Check the declared kind and the text/keyword field names against the sealed schema."""
    if request.kind not in _KIND_TARGETS:
        raise _invalid("kind 必须是文字、滤镜叠加、视频叠加或转场叠加")
    expected = _VERSION_KINDS.get(version_kind)
    if expected is not None and expected != request.kind:
        raise _invalid("kind 与该版本创建时的类型不一致")
    if request.kind == pb.SPRITE_KIND_TEXT:
        text = _definition(schema, request.text_prop)
        if text is None or text.get("type") != "string":
            raise _invalid("text_prop 必须是该版本参数中的字符串字段（嵌套字段用点号，如 title_main.title）")
        if request.keywords_prop and (
            _definition(schema, request.keywords_prop) is None
            or request.keywords_prop == request.text_prop
            or _definition(schema, request.keywords_prop).get("type") == "object"
        ):
            raise _invalid("keywords_prop 必须是该版本参数中不同于 text_prop 的非对象字段")
    elif request.text_prop or request.keywords_prop:
        raise _invalid("只有文字 Sprite 可以声明 text_prop 与 keywords_prop")


async def _rebuild_bundle(service, version) -> bytes | None:
    """Rebuild the player bundle from the sealed source with the current host code; None when unavailable.

    Failure is non-fatal: the asset is still saved with its original bundle and simply cannot be previewed
    over the template.
    """
    store = service.store
    work = store.root / "sprites" / f".build-{uuid4()}"
    try:
        work.mkdir(parents=True)
        (work / "request.json").write_text(json.dumps({
            "code": version.candidate.tsx_code,
            "config": version.candidate.default_config,
            "composition": version.spec.composition.model_dump(),
        }, ensure_ascii=False), encoding="utf-8")
        await service.harness.renderer.run_worker(work, worker="presentation-worker.mjs")
        data = (work / PREVIEW_BUNDLE).read_bytes()
        return data if SYNC_MARKER in data else None
    except Exception:
        logging.getLogger(__name__).exception("Sprite preview rebuild failed: %s", version.id)
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _store_bundle(store: Store, sprite: pb.PublishedSprite, data: bytes) -> None:
    """Replace a publication's player copy and its recorded hash; the source and parameters are untouched."""
    (store.root / "sprites" / sprite.sprite_id / PREVIEW_BUNDLE).write_bytes(data)
    sprite.preview_sha256 = hashlib.sha256(data).hexdigest()
    with store.connection() as db:
        db.execute(
            "UPDATE sprites SET data=? WHERE id=?",
            (json.dumps(MessageToDict(sprite, preserving_proto_field_name=True), ensure_ascii=False), sprite.sprite_id),
        )


async def publish(service, request: pb.PublishSpriteRequest) -> pb.SpriteSummary:
    """Copy a verified accepted version into an immutable publication; repeating returns the original.

    The player bundle is rebuilt with the current host code when the sealed one predates frame-synchronised
    previews, so older versions can still be previewed over a template after saving.
    """
    store = service.store
    try:
        version_id = UUID(request.source_version_id)
    except ValueError:
        raise _invalid("source_version_id 不是有效的 UUID") from None
    version = store.version(version_id)
    accepted = store.root / "accepted" / str(version.id)
    try:
        verify_artifacts(version.candidate, version.spec, version.validation, accepted)
    except (ValueError, OSError) as exc:
        raise Conflict("accepted artifact unavailable") from exc
    if PREVIEW_BUNDLE not in version.validation.artifacts:
        raise Conflict("该版本没有可发布的交互预览")
    schema = version.candidate.config_schema
    _validated_request(request, schema, version.spec.sprite_kind)

    def existing() -> sqlite3.Row | None:
        """Look up the publication that this exact source and field choice already produced."""
        with store.connection() as db:
            return db.execute(
                "SELECT data FROM sprites WHERE source_version_id=? AND kind=? AND text_prop=? AND keywords_prop=?",
                (str(version.id), request.kind, request.text_prop, request.keywords_prop),
            ).fetchone()

    async def current_bundle() -> bytes:
        """The sealed bundle, or a fresh build when the sealed one has no synchronisation support."""
        sealed = (accepted / PREVIEW_BUNDLE).read_bytes()
        return sealed if SYNC_MARKER in sealed else (await _rebuild_bundle(service, version) or sealed)

    if (row := existing()) is not None:
        sprite = _sprite_from(row)
        stored = store.root / "sprites" / sprite.sprite_id / PREVIEW_BUNDLE
        if SYNC_MARKER not in stored.read_bytes() and (fresh := await _rebuild_bundle(service, version)):
            _store_bundle(store, sprite, fresh)
        return summarize(sprite)

    composition = version.spec.composition
    sprite_id = str(uuid4())
    published_at = datetime.now(UTC)
    bundle = await current_bundle()
    directory = store.root / "sprites" / sprite_id
    directory.mkdir(parents=True)
    try:
        (directory / PREVIEW_BUNDLE).write_bytes(bundle)
        sprite = pb.PublishedSprite(
            sprite_id=sprite_id,
            source_version_id=str(version.id),
            name=version.spec.name,
            kind=request.kind,
            canvas=pb.SpriteCanvas(
                width=composition.width,
                height=composition.height,
                fps=round(composition.fps),
                preview_frames=composition.duration_in_frames,
            ),
            tsx_code=version.candidate.tsx_code,
            code_sha256=hashlib.sha256(version.candidate.tsx_code.encode()).hexdigest(),
            parameters=_parameters(schema, version.candidate.default_config, {request.text_prop, request.keywords_prop}),
            text_prop=request.text_prop,
            keywords_prop=request.keywords_prop,
            preview_sha256=hashlib.sha256(bundle).hexdigest(),
            config_schema_json=json.dumps(schema, ensure_ascii=False),
            default_config_json=json.dumps(version.candidate.default_config, ensure_ascii=False),
        )
        sprite.published_at.FromDatetime(published_at)
        with store.connection() as db:
            db.execute(
                "INSERT INTO sprites VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    sprite_id, str(version.id), request.kind, request.text_prop, request.keywords_prop,
                    published_at.isoformat(),
                    json.dumps(MessageToDict(sprite, preserving_proto_field_name=True), ensure_ascii=False),
                ),
            )
    except sqlite3.IntegrityError:
        shutil.rmtree(directory, ignore_errors=True)
        if (row := existing()) is None:
            raise
        return summarize(_sprite_from(row))
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return summarize(sprite)


def _override_value(parameter: pb.SpriteParameter, override: pb.SpriteParameterOverride):
    """Return a plain JSON value after checking type, numeric bounds and enumeration against the parameter."""
    expected = parameter.default_value.WhichOneof("value")
    if override.value.WhichOneof("value") != expected:
        raise _invalid(f"参数 {parameter.key} 的覆盖值类型必须与默认值一致")
    value = getattr(override.value, expected)
    if expected == "number_value":
        if not math.isfinite(value):
            raise _invalid(f"参数 {parameter.key} 必须是有限数字")
        if parameter.HasField("minimum") and value < parameter.minimum:
            raise _invalid(f"参数 {parameter.key} 不能小于 {parameter.minimum:g}")
        if parameter.HasField("maximum") and value > parameter.maximum:
            raise _invalid(f"参数 {parameter.key} 不能大于 {parameter.maximum:g}")
    if parameter.allowed_values and not any(
        item.WhichOneof("value") == expected and getattr(item, expected) == value for item in parameter.allowed_values
    ):
        raise _invalid(f"参数 {parameter.key} 的取值不在允许范围内")
    return value


def _validate_placement(sprite: pb.PublishedSprite, placement: pb.SpritePlacement) -> None:
    """Check target, timing and style overrides of one placement against its publication."""
    if placement.target not in _KIND_TARGETS.get(sprite.kind, set()):
        raise _invalid(f"Sprite「{sprite.name}」的类型不支持该作用对象")
    if placement.target == pb.SPRITE_TARGET_SUBTITLE and not sprite.keywords_prop:
        raise _invalid(f"Sprite「{sprite.name}」未验收关键词高亮，不能绑定字幕")
    if placement.start_mode not in {"seconds", "percent"}:
        raise _invalid("start_mode 只能是 seconds 或 percent")
    if not math.isfinite(placement.start) or placement.start < 0:
        raise _invalid("start 必须是不小于 0 的有限数字")
    if placement.start_mode == "percent" and placement.start >= 100:
        raise _invalid("百分比起点必须小于 100")
    if placement.HasField("duration"):
        if not math.isfinite(placement.duration) or placement.duration <= 0:
            raise _invalid("duration 必须是大于 0 的有限数字")
    elif placement.target in _DURATION_REQUIRED:
        raise _invalid("转场、片段入场和片段出场必须指定 duration")
    parameters = {item.key: item for item in sprite.parameters}
    overrides = {}
    for override in placement.overrides:
        parameter = parameters.get(override.key)
        if parameter is None or parameter.access != pb.OPERATOR_ACCESS_VISIBLE_EDITABLE:
            raise _invalid(f"参数 {override.key} 不存在或不可编辑")
        if override.key in overrides:
            raise _invalid(f"参数 {override.key} 重复")
        overrides[override.key] = _override_value(parameter, override)
    schema = json.loads(sprite.config_schema_json)
    configuration = json.loads(sprite.default_config_json)
    for key, value in overrides.items():
        if _definition(schema, key).get("type") == "integer":
            if not float(value).is_integer():
                raise _invalid(f"参数 {key} 必须是整数")
            value = int(value)
        configuration = _assign(configuration, key, value)
    try:
        validate_parameters(schema, configuration)
    except ValidationError as exc:
        raise _invalid(f"样式覆盖不满足参数约束：{exc.message}") from exc


def validate_placements(store: Store, placements: Iterable[pb.SpritePlacement]) -> None:
    """Reject a binding list that references unknown Sprites or breaks any placement rule."""
    items = list(placements)
    if len(items) > MAX_PLACEMENTS:
        raise _invalid(f"最多绑定 {MAX_PLACEMENTS} 个 Sprite")
    if sorted(item.order for item in items) != list(range(len(items))):
        raise _invalid("order 必须从 0 开始连续且不重复")
    identifiers = [item.id for item in items]
    if any(not identifier or len(identifier) > 64 for identifier in identifiers) or len(set(identifiers)) != len(items):
        raise _invalid("绑定实例 id 必须非空、不超过 64 个字符且互不相同")
    publications: dict[str, pb.PublishedSprite] = {}
    for item in items:
        if item.sprite_id not in publications:
            try:
                publications[item.sprite_id] = get(store, item.sprite_id)
            except NotFound:
                raise _invalid(f"Sprite {item.sprite_id} 不存在") from None
        _validate_placement(publications[item.sprite_id], item)
