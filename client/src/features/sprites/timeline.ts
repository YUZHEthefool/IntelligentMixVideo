/** 将 Remotion 固定片段加入项目共用时间轴；区间按 IMS 的 30 FPS 帧边界与项目成片时长裁切。 */
import { frameRange } from "@/features/timeline/frames";
import type { PreviewClip } from "@/features/templates/timeline";
import type { TimelineRow } from "@xzdarcy/timeline-engine";
import type { SpriteAsset, SpritePlacement, SpriteClip } from "./model";

/** 母版媒体与 IMS 转场得到唯一成片时长，Remotion 内容仅在这个范围内显示。 */
export function resolveSpriteClips(placements: SpritePlacement[], assets: SpriteAsset[], duration: number): SpriteClip[] {
  if (duration <= 0) return [];
  return placements.map((clip) => {
    const asset = assets.find((item) => item.id === clip.sprite_id);
    const range = frameRange(clip.start, clip.start + clip.duration, duration);
    const start = range.first / 30;
    const end = range.last / 30;
    return { id: clip.id, spriteId: clip.sprite_id, name: asset?.name ?? "Remotion 资产", aspect: asset?.aspect ?? 9 / 16, start, end };
  }).filter((clip) => clip.end > clip.start);
}

/** 同一时间轴上每项独占一行，原始资产时长不随显示截断而变化。 */
export function spriteRows(clips: SpriteClip[]): (Omit<TimelineRow, "actions"> & { actions: PreviewClip[] })[] {
  return clips.map((clip) => ({ id: `row-${clip.id}`, actions: [{
    id: clip.id, effectId: "remotion", start: clip.start, end: clip.end, movable: true, flexible: false,
    label: clip.name, url: "", sourceIn: 0, sourceOut: 0, targetId: clip.id,
  }] }));
}
