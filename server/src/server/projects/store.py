"""Shared video project persistence: source canvas, IMS tracks and Remotion clips saved atomically.

Media uses the existing IMS editor metadata contract; each content type keeps its own validation.
No IMS template record is created, so Remotion-only projects can be saved without a dummy effect.
"""

from datetime import datetime
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..remotion_templates import sprites
from ..remotion_templates.store import Conflict, NotFound, Store, now
from ..template.schema import EffectTrack, TemplateSave


class ClipInput(BaseModel):
    """One immutable asset placed at a nonnegative time; duration comes from the publication."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    sprite_id: UUID
    start: float = Field(ge=0, le=3600)


class Clip(ClipInput):
    """Saved clip with its server-derived duration, independent of preview truncation."""

    duration: float = Field(gt=0)


class ProjectMedia(BaseModel):
    """Shared source video metadata, matching the IMS editor's MasterVideo canvas and timing."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    url: str = Field(min_length=1, max_length=8000, pattern=r"^https?://")
    width: int = Field(ge=1, le=16384, strict=True)
    height: int = Field(ge=1, le=16384, strict=True)
    duration: float = Field(gt=0)


class ProjectData(BaseModel):
    """Project name, shared source media and IMS tracks; Remotion clips are stored alongside them."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    media: ProjectMedia | None = None
    tracks: list[EffectTrack] = Field(max_length=100)

    @model_validator(mode="after")
    def validate_ims_tracks(self):
        """Validate IMS effects only when present; a Remotion-only project needs none."""
        if self.tracks:
            effect_ids = {value for track in self.tracks for value in track.editor.selected_effects().values()}
            if effect_ids:
                TemplateSave(name=self.name, tracks=self.tracks, effect_ids=list(effect_ids))
            elif any(track.target not in {"title", "subtitle", "bubble"} for track in self.tracks):
                raise ValueError("IMS 轨道缺少效果")
        if len({track.id for track in self.tracks}) != len(self.tracks):
            raise ValueError("IMS 轨道 ID 不能重复")
        return self


class SaveProject(ProjectData):
    """One complete save request; revision zero creates a new client-generated UUID."""

    expected_revision: int = Field(ge=0, le=2**53 - 2, strict=True)
    clips: list[ClipInput] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_clips(self):
        """Reject duplicate instance IDs while allowing repeated uses of an asset."""
        if len({clip.id for clip in self.clips} | {track.id for track in self.tracks}) != len(self.clips) + len(self.tracks):
            raise ValueError("Remotion 片段 ID 不能重复")
        return self


class VideoProject(ProjectData):
    """Durable project snapshot returned by list, read and save endpoints."""

    id: UUID
    revision: int
    clips: list[Clip]
    updated_at: datetime


def list_projects(store: Store) -> list[VideoProject]:
    """List newest projects without reading the separate IMS template library."""
    with store.connection() as db:
        rows = db.execute("SELECT data FROM composition_projects ORDER BY updated_at DESC, id").fetchall()
    return [VideoProject.model_validate_json(row["data"]) for row in rows]


def get_project(store: Store, project_id: UUID) -> VideoProject:
    """Read the exact saved revision or return 404."""
    with store.connection() as db:
        row = db.execute("SELECT data FROM composition_projects WHERE id=?", (str(project_id),)).fetchone()
    if row is None:
        raise NotFound("视频项目不存在")
    return VideoProject.model_validate_json(row["data"])


def save_project(store: Store, project_id: UUID, data: SaveProject) -> VideoProject:
    """Validate publications first, then save all fields atomically under a revision lock."""
    clips = []
    for item in data.clips:
        try:
            asset = sprites.get(store, str(item.sprite_id))
        except NotFound:
            raise HTTPException(422, "Remotion 资产不存在，请刷新资产库") from None
        if not asset.canvas.fps or not asset.canvas.preview_frames:
            raise HTTPException(422, "Remotion 资产时长无效")
        clips.append(Clip(**item.model_dump(), duration=asset.canvas.preview_frames / asset.canvas.fps))
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT revision FROM composition_projects WHERE id=?", (str(project_id),)).fetchone()
        revision = row["revision"] if row else 0
        if revision != data.expected_revision:
            raise Conflict("视频项目已被修改或删除，请重新读取后再保存")
        saved = VideoProject(
            **data.model_dump(exclude={"expected_revision", "clips"}), id=project_id,
            revision=revision + 1, clips=clips, updated_at=now(),
        )
        db.execute(
            "INSERT INTO composition_projects VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, updated_at=excluded.updated_at, data=excluded.data",
            (str(project_id), saved.revision, saved.updated_at.isoformat(), saved.model_dump_json(by_alias=True)),
        )
    return saved


def delete_project(store: Store, project_id: UUID, expected_revision: int) -> None:
    """Delete the selected revision, refusing to erase another editor's newer changes."""
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT revision FROM composition_projects WHERE id=?", (str(project_id),)).fetchone()
        if row is None:
            raise NotFound("视频项目不存在")
        if row["revision"] != expected_revision:
            raise Conflict("视频项目已被修改，请重新读取后再删除")
        db.execute("DELETE FROM composition_projects WHERE id=?", (str(project_id),))
