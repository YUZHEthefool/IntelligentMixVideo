/** Remotion Sprite 资产的客户端视图：发布目录条目与模板内的固定片段摆放；资产本身不可配置。 */
import { SpriteKind, SpriteTarget } from "@/generated/imv/sprite/v1/sprite_pb";

/** 公开目录条目；seconds 是资产自身的播放时长，片段摆放时直接使用。 */
export interface SpriteAsset {
  id: string;
  name: string;
  kind: SpriteKind;
  seconds: number;
  /** 发布画布宽高比，叠加预览按 Cover 方式铺满模板画面。 */
  aspect: number;
}

/** 模板内的一次摆放：只有起点（秒）；时长固定为资产自身长度，作用对象由资产类型决定。 */
export interface Placement {
  id: string;
  spriteId: string;
  target: SpriteTarget;
  start: number;
  duration: number;
}

/** 各发布类型对应的绑定作用对象，与服务端校验一致。 */
const kindTarget: Partial<Record<SpriteKind, SpriteTarget>> = {
  [SpriteKind.TEXT]: SpriteTarget.TITLE,
  [SpriteKind.FILTER_OVERLAY]: SpriteTarget.FILTER,
  [SpriteKind.VIDEO_OVERLAY]: SpriteTarget.VIDEO_EFFECT,
  [SpriteKind.TRANSITION_OVERLAY]: SpriteTarget.TRANSITION,
};

/** 从目录条目创建摆放：从模板开头播放，持续整个资产长度。 */
export function newPlacement(asset: SpriteAsset): Placement {
  const target = kindTarget[asset.kind];
  if (target === undefined) throw new Error("资产类型无效");
  return { id: `sprite-${crypto.randomUUID()}`, spriteId: asset.id, target, start: 0, duration: asset.seconds };
}
