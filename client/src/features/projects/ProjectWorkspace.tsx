/** 项目编辑器：统一媒体、画布和时间轴，分别组合 IMS 效果模块与独立 Remotion 资产模块。 */
import { useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AppliedEffects, EffectAssets } from "@/features/templates/EffectAssets";
import { TemplateInspector, type InspectorTab } from "@/features/templates/TemplateInspector";
import { TemplatePreview } from "@/features/templates/TemplatePreview";
import { addTrack, previewDuration, removeTrack, setTrackRange, setTrackTiming, trackDraft, updateTrack } from "@/features/templates/tracks";
import { readCatalog } from "@/features/templates/sdk";
import { isTextTarget } from "@/features/templates/effects";
import type { Draft, TextRole } from "@/features/templates/model";
import { SpriteCatalog } from "@/features/sprites/SpriteCatalog";
import { SpriteOverlay, type SpriteOverlayHandle } from "@/features/sprites/SpriteOverlay";
import { resolveSpriteClips, spriteRows } from "@/features/sprites/timeline";
import type { SpriteAsset } from "@/features/sprites/model";
import { useProjects } from "./useProjects";
import "@/features/templates/template-workspace.css";

/** 项目隐藏时保留草稿；媒体选择同时影响两类内容，保存建立同一个版本基线。 */
export function ProjectWorkspace({ active = true }: { active?: boolean }) {
  const state = useProjects(active);
  const { draft: project, setDraft: setProject, busy } = state;
  const [catalog, setCatalog] = useState(readCatalog);
  const [assets, setAssets] = useState<SpriteAsset[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [textTarget, setTextTarget] = useState<TextRole>("title");
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("timing");
  const [editError, setEditError] = useState("");
  const overlay = useRef<SpriteOverlayHandle>(null);
  const form = useRef<HTMLFormElement>(null);
  const draft = useMemo<Draft | null>(() => project ? { name: project.name, description: project.description, tracks: project.tracks, transition_duration_seconds: 1 } : null, [project]);
  const duration = draft ? Math.max(0, previewDuration(draft, project?.media ?? undefined)) : 10;
  const clips = useMemo(() => resolveSpriteClips(project?.clips ?? [], assets, duration), [project?.clips, assets, duration]);
  const rows = useMemo(() => spriteRows(clips), [clips]);
  const track = project?.tracks.find((item) => item.id === selected);
  const sprite = project?.clips.find((item) => item.id === selected);
  const assetTrack = track ?? project?.tracks.find((item) => item.target === textTarget);

  /** IMS 编辑器只返回自己的轨道，保留同一项目内的媒体和 Remotion 片段。 */
  function edit(change: (draft: Draft) => Draft) {
    if (!draft || busy) return;
    try {
      const next = change(draft);
      setProject((current) => current && ({ ...current, tracks: next.tracks }));
      setEditError("");
    } catch (reason) { setEditError(reason instanceof Error ? reason.message : "轨道设置无效"); }
  }

  /** 时间表单合法时才保存；切换对话框复用相同校验，避免写入局部无效输入。 */
  function valid() {
    const inputs = form.current?.querySelectorAll<HTMLInputElement>('[aria-label="轨道时间设置"] input, [aria-label="项目名称"], [aria-label="Remotion 开始时间"]');
    if (inputs && [...inputs].some((input) => !input.checkValidity())) { setEditError("请检查项目名称和轨道时间设置。"); return false; }
    return true;
  }

  return <section aria-label="视频项目工作区" className="space-y-3">
    <header className="flex flex-wrap items-center justify-between gap-3 py-3"><div><h1 className="text-base font-semibold">视频项目</h1><p className="text-xs text-muted-foreground">在同一画布和时间轴中编排 IMS 效果与 Remotion 资产。</p></div><Button disabled={busy} onClick={() => state.request({ kind: "new" })}>新建项目</Button></header>
    <section aria-label="项目库" className="flex flex-wrap items-center gap-2 rounded-lg border p-3">
      <Button variant="ghost" size="sm" disabled={state.loading || busy} onClick={state.refresh}>刷新项目库</Button>
      {state.listError && <p role="alert" className="text-xs text-destructive">{state.listError}</p>}
      {state.items.map((item) => <Button key={item.id} variant={item.id === project?.id ? "secondary" : "outline"} size="sm" disabled={busy} aria-label={`打开项目：${item.name}`} onClick={() => state.request({ kind: "open", id: item.id })}>{item.name}</Button>)}
      {!state.loading && !state.items.length && <span className="text-xs text-muted-foreground">还没有保存的项目</span>}
    </section>
    {(state.error || editError) && <p role="alert" className="text-sm text-destructive">{state.error || editError}</p>}
    {!project || !draft ? <div className="rounded-xl border p-10 text-center text-sm text-muted-foreground">选择或新建项目开始编辑。</div> : <form ref={form} noValidate onSubmit={(event) => { event.preventDefault(); if (valid()) void state.save(); }} className="template-workspace overflow-hidden rounded-xl border bg-card">
      <fieldset disabled={busy} className="min-w-0 disabled:opacity-60">
        <div className="flex flex-wrap items-center gap-3 border-b p-4">
          <label className="flex min-w-44 flex-1 items-center gap-2 text-xs"><span className="shrink-0">项目名称</span><Input required maxLength={100} aria-label="项目名称" value={project.name} onChange={(event) => setProject({ ...project, name: event.target.value })} /></label>
          <span className="text-xs text-muted-foreground" aria-label="项目画布">{project.media ? `${project.media.width} × ${project.media.height}` : "随母版视频"} · {duration.toFixed(2)} 秒</span>
          <span role="status" className="text-xs">{state.dirty ? "有未保存的修改" : "已保存"}</span>
          <Button type="submit">{busy ? "正在保存…" : "保存项目"}</Button>
          <Button type="button" variant="ghost" onClick={() => state.request({ kind: "open", id: project.id })}>重新读取项目</Button>
          {project.revision > 0 && <Button type="button" variant="ghost" onClick={() => state.request({ kind: "delete" })}>删除项目</Button>}
        </div>
        <div className="grid min-w-0 xl:grid-cols-[230px_minmax(0,1fr)_270px]">
          <aside className="template-workspace-assets order-2 min-w-0 border-r xl:order-1">
            <EffectAssets catalog={catalog} editor={assetTrack?.editor} textEditor={assetTrack?.editor} textTarget={textTarget} onTextTarget={setTextTarget} onAsset={(asset, role) => edit((current) => {
              const result = addTrack(current, asset, role, selected ?? undefined); setSelected(result.id);
              const added = result.draft.tracks.find((item) => item.id === result.id)!;
              if (isTextTarget(added.target)) setTextTarget(added.target);
              return result.draft;
            })} />
            <SpriteCatalog active={active} disabled={busy || project.clips.length >= 100} onCatalog={setAssets} onAdd={(asset) => {
              const id = crypto.randomUUID();
              setProject((current) => current && ({ ...current, clips: [...current.clips, { id, sprite_id: asset.id, start: 0, duration: asset.seconds }] }));
              setSelected(id);
            }} />
          </aside>
          <main className="template-workspace-canvas order-1 min-w-0 xl:order-2">
            <TemplatePreview key={project.id} draft={draft} media={project.media ?? undefined} onMediaChange={(media) => setProject((current) => current && ({ ...current, media }))} videoInputKey={project.id} onCatalog={setCatalog}
              selectedId={selected} onSelect={setSelected} active={active && !busy} adoptDefaultMedia additionalRows={rows}
              onTimeChange={(time) => overlay.current?.setTime(time)}
              overlay={<SpriteOverlay ref={overlay} clips={clips} stageAspect={project.media ? project.media.width / project.media.height : 16 / 9} initialTime={0} />}
              onRangeChange={(id, start, end) => {
                if (project.clips.some((item) => item.id === id)) setProject((current) => current && ({ ...current, clips: current.clips.map((item) => item.id === id ? { ...item, start: Math.round(start * 30) / 30 } : item) }));
                else edit((current) => setTrackRange(current, id, start, end, project.media ?? undefined));
              }} />
          </main>
          <aside className="template-workspace-inspector order-3 min-w-0 border-l">
            <AppliedEffects draft={draft} catalog={catalog} duration={duration} selected={selected} onSelect={setSelected} />
            <section aria-label="Remotion 片段" className="space-y-2 border-t p-4"><h2 className="text-sm font-semibold">Remotion 片段</h2>
              {project.clips.map((item) => <Button key={item.id} type="button" className="w-full justify-start" variant={selected === item.id ? "secondary" : "ghost"} size="sm" aria-label={`编辑片段：${assets.find((asset) => asset.id === item.sprite_id)?.name ?? "Remotion 资产"}`} onClick={() => setSelected(item.id)}>{assets.find((asset) => asset.id === item.sprite_id)?.name ?? "Remotion 资产"} · {item.start.toFixed(2)} 秒</Button>)}
              {sprite && <div aria-label="Remotion 片段设置" className="space-y-2 text-xs">
                <label>开始 / 秒<Input aria-label="Remotion 开始时间" type="number" min={0} max={3600} step="any" value={sprite.start} onChange={(event) => {
                  const start = Number(event.target.value); if (!Number.isFinite(start) || start < 0 || start > 3600) return; setProject((current) => current && ({ ...current, clips: current.clips.map((item) => item.id === sprite.id ? { ...item, start } : item) }));
                }} /></label>
                <p>固定时长 {sprite.duration.toFixed(2)} 秒</p><Button type="button" variant="outline" size="sm" onClick={() => { setProject((current) => current && ({ ...current, clips: current.clips.filter((item) => item.id !== sprite.id) })); setSelected(null); }}>移除 Remotion 片段</Button>
              </div>}
            </section>
            {track && <TemplateInspector track={track} draft={trackDraft(draft, track)} catalog={catalog} duration={duration} tab={inspectorTab} onTabChange={setInspectorTab} onTimingChange={(timing) => edit((current) => setTrackTiming(current, track.id, timing))} onEffectChange={(next) => edit((current) => updateTrack(current, track.id, next))} onRemove={() => edit((current) => removeTrack(current, track.id))} onClose={() => setSelected(null)} />}
          </aside>
        </div>
      </fieldset>
    </form>}
    <Dialog open={!!state.navigation} onOpenChange={(open) => { if (!open) state.cancel(); }}><DialogContent showCloseButton={!busy}><DialogHeader><DialogTitle>{state.navigation?.kind === "delete" ? "删除项目？" : "保存当前修改？"}</DialogTitle><DialogDescription>{state.navigation?.kind === "delete" ? "项目中的媒体引用和轨道会被删除，已发布资产保留。" : "切换前可以保存当前项目，或放弃未保存修改。"}</DialogDescription></DialogHeader>
      {state.error && <p role="alert" className="text-sm text-destructive">{state.error}</p>}
      <DialogFooter><Button variant="outline" disabled={busy} onClick={state.cancel}>取消</Button><Button variant="outline" disabled={busy} onClick={() => void state.resolve(false)}>{state.navigation?.kind === "delete" ? "确认删除" : "放弃修改并切换"}</Button>{state.navigation?.kind !== "delete" && <Button disabled={busy} onClick={() => { if (valid()) void state.resolve(true); }}>保存并切换</Button>}</DialogFooter>
    </DialogContent></Dialog>
  </section>;
}
