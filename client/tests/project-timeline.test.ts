/** 项目时间规则回归：Remotion 与 IMS 共用媒体和帧边界，转场后的成片时长决定所有轨道裁切。 */
import { expect, test } from "bun:test";
import { buildTimeline } from "@/features/templates/timeline";
import { previewDuration } from "@/features/templates/tracks";
import { readCatalog } from "@/features/templates/sdk";
import { defaultEditor, newDraft } from "@/features/templates/model";
import { resolveSpriteClips, spriteRows } from "@/features/sprites/timeline";

// 场景：同一媒体改变尺寸/时长后，IMS 画布与 Remotion 可见范围均使用新的项目媒体；固定资产长度不被改写。
test("IMS 和 Remotion 使用同一项目媒体和转场后时长", () => {
  const draft = newDraft();
  draft.tracks.push({ id: "transition", target: "transition", start_mode: "seconds", start: 2, duration: 1, editor: { ...defaultEditor, transition: "transition/normal/directional" } });
  const media = { url: "https://example.test/source.mp4", width: 1920, height: 1080, duration: 10 };
  const placement = { id: "sprite-a", sprite_id: "asset-a", start: 7.51, duration: 3 };
  const total = previewDuration(draft, media);
  const timeline = buildTimeline(draft, readCatalog(), media);
  expect(total).toBe(9);
  expect(timeline.FECanvas).toEqual({ Width: 1920, Height: 1080 });
  expect(timeline.VideoTracks[0].VideoTrackClips.at(-1)!.TimelineOut).toBe(total);
  const clips = resolveSpriteClips([placement], [], total);
  expect(clips[0]).toMatchObject({ start: 7.5, end: 9 });
  expect(spriteRows(clips)[0].actions[0]).toMatchObject({ flexible: false, start: 7.5, end: 9 });
  expect(placement.duration).toBe(3);
  const smaller = { ...media, width: 1080, height: 1920, duration: 6 };
  expect(buildTimeline(draft, readCatalog(), smaller).FECanvas).toEqual({ Width: 1080, Height: 1920 });
  expect(resolveSpriteClips([placement], [], previewDuration(draft, smaller))).toEqual([]);
});
