"""MySQL 模板存储：唯一名称、完整 JSON 快照和事务更新；不迁移旧项目数据。"""

from datetime import UTC, datetime
from threading import Lock
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import JSON, BigInteger, Column, MetaData, String, Table, delete, select
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.exc import IntegrityError

from ..database import get_engine
from .schema import Template, TemplateSave, effect_catalog

# 模板元数据用于查询和约束，配置 JSON 保留完整编辑字段与可信效果快照。
metadata = MetaData()
templates = Table(
    "templates", metadata,
    Column("template_id", String(36), primary_key=True),
    Column("name", String(100, collation="utf8mb4_bin"), nullable=False, unique=True),
    Column("configuration", JSON, nullable=False),
    Column("created_at", DATETIME(fsp=6), nullable=False),
    Column("updated_at", DATETIME(fsp=6), nullable=False, index=True),
    mysql_charset="utf8mb4",
)
# Remotion Sprite 绑定独立保存；整体替换并以 revision 乐观锁防止覆盖他人修改。
sprite_bindings = Table(
    "style_sprite_bindings", metadata,
    Column("style_id", String(36), primary_key=True),
    Column("revision", BigInteger, nullable=False),
    Column("placements", JSON, nullable=False),
    Column("updated_at", DATETIME(fsp=6), nullable=False),
    mysql_charset="utf8mb4",
)
_schema_lock = Lock()
_ready_engine = None


def initialize_schema():
    """首次模板请求创建缺失表；数据库已在应用启动时确保存在，失败后可重试。"""
    global _ready_engine
    engine = get_engine()
    with _schema_lock:
        if _ready_engine is not engine:
            metadata.create_all(engine)
            _ready_engine = engine
    return engine


def to_template(row) -> Template:
    """将 MySQL 的无时区 UTC 字段恢复为带时区的 API 响应。"""
    return Template(
        **row.configuration, template_id=row.template_id, name=row.name,
        created_at=row.created_at.replace(tzinfo=UTC),
        updated_at=row.updated_at.replace(tzinfo=UTC),
    )


def list_templates() -> list[Template]:
    """按最近更新优先返回模板；同一时间使用 ID 稳定排序。"""
    with initialize_schema().connect() as connection:
        rows = connection.execute(select(templates).order_by(
            templates.c.updated_at.desc(), templates.c.template_id,
        ))
        return [to_template(row) for row in rows]


def get_template(template_id: UUID) -> Template:
    """查找单个模板；不存在返回 404。"""
    with initialize_schema().connect() as connection:
        row = connection.execute(select(templates).where(
            templates.c.template_id == str(template_id),
        )).first()
        if row is None:
            raise HTTPException(404, "模板不存在")
        return to_template(row)


def save_template(data: TemplateSave) -> Template:
    """原子创建或完整覆盖；锁定待更新行，并以数据库唯一约束处理并发重名。"""
    template_id = str(data.template_id or uuid4())
    catalog = effect_catalog()
    configuration = data.model_dump(mode="json", by_alias=True, exclude={"template_id", "name"})
    configuration["effects"] = [catalog[key].model_dump(mode="json") for key in data.effect_ids]
    try:
        with initialize_schema().begin() as connection:
            now = datetime.now(UTC).replace(tzinfo=None)
            values = {"name": data.name, "configuration": configuration, "updated_at": now}
            if data.template_id:
                existing = connection.execute(select(templates.c.template_id).where(
                    templates.c.template_id == template_id,
                ).with_for_update()).first()
                if existing is None:
                    raise HTTPException(404, "模板不存在")
                connection.execute(templates.update().where(
                    templates.c.template_id == template_id,
                ).values(**values))
            else:
                connection.execute(templates.insert().values(
                    template_id=template_id, created_at=now, **values,
                ))
            row = connection.execute(select(templates).where(
                templates.c.template_id == template_id,
            )).one()
            result = to_template(row)
        return result
    except IntegrityError as exc:
        if exc.orig.args[0] == 1062:
            raise HTTPException(409, "模板名称已存在，请使用其他名称") from None
        raise


def delete_template(template_id: UUID) -> None:
    """事务删除指定模板；重复删除返回 404，不删除任何其他记录。"""
    with initialize_schema().begin() as connection:
        result = connection.execute(delete(templates).where(
            templates.c.template_id == str(template_id),
        ))
        if result.rowcount == 0:
            raise HTTPException(404, "模板不存在")
        connection.execute(delete(sprite_bindings).where(
            sprite_bindings.c.style_id == str(template_id),
        ))


def get_sprite_bindings(template_id: UUID) -> tuple[int, list[dict], datetime | None]:
    """读取模板的 Sprite 绑定；模板存在但无记录时返回版本 0 与空列表，模板不存在返回 404。"""
    with initialize_schema().connect() as connection:
        if connection.execute(select(templates.c.template_id).where(
            templates.c.template_id == str(template_id),
        )).first() is None:
            raise HTTPException(404, "模板不存在")
        row = connection.execute(select(sprite_bindings).where(
            sprite_bindings.c.style_id == str(template_id),
        )).first()
        if row is None:
            return 0, [], None
        return row.revision, row.placements, row.updated_at.replace(tzinfo=UTC)


def replace_sprite_bindings(
    template_id: UUID, placements: list[dict], expected_revision: int,
) -> tuple[int, list[dict], datetime]:
    """锁定模板行后整体替换绑定；revision 与调用方读取值不同返回 409，成功后递增。"""
    with initialize_schema().begin() as connection:
        if connection.execute(select(templates.c.template_id).where(
            templates.c.template_id == str(template_id),
        ).with_for_update()).first() is None:
            raise HTTPException(404, "模板不存在")
        row = connection.execute(select(sprite_bindings.c.revision).where(
            sprite_bindings.c.style_id == str(template_id),
        )).first()
        current = row.revision if row else 0
        if current != expected_revision:
            raise HTTPException(409, "Sprite 绑定已被其他修改更新，请刷新后重试")
        now = datetime.now(UTC).replace(tzinfo=None)
        values = {"revision": current + 1, "placements": placements, "updated_at": now}
        if row is None:
            connection.execute(sprite_bindings.insert().values(style_id=str(template_id), **values))
        else:
            connection.execute(sprite_bindings.update().where(
                sprite_bindings.c.style_id == str(template_id),
            ).values(**values))
    return current + 1, placements, now.replace(tzinfo=UTC)
