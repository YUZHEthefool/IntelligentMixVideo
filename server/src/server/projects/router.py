"""Project aggregate JSON routes: one canvas/source and timeline for independent IMS and Remotion content."""

from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from ..remotion_templates.sprite_router import sprite_runtime
from ..remotion_templates.runtime import Runtime
from . import store

router = APIRouter(prefix="/api/projects", tags=["视频项目"])
Service = Annotated[Runtime, Depends(sprite_runtime)]


@router.get("", response_model=list[store.VideoProject])
async def list_projects(service: Service):
    """List project aggregates from the local project table."""
    return await run_in_threadpool(store.list_projects, service.store)


@router.get("/{project_id}", response_model=store.VideoProject)
async def get_project(project_id: UUID, service: Service):
    """Read shared media and both content types from the same revision."""
    return await run_in_threadpool(store.get_project, service.store, project_id)


@router.put("/{project_id}", response_model=store.VideoProject)
async def save_project(project_id: UUID, data: store.SaveProject, service: Service):
    """Atomically save a project; no IMS template or separate binding write occurs."""
    return await run_in_threadpool(store.save_project, service.store, project_id, data)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: UUID, expected_revision: Annotated[int, Query(ge=1)], service: Service):
    """Delete only the selected revision; independently published content remains available."""
    await run_in_threadpool(store.delete_project, service.store, project_id, expected_revision)
