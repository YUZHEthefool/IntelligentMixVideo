/** 独立 Remotion 资产与模板的数据视图，不使用 IMS 效果、模板 ID 或轨道契约。 */
import type { SpriteKind } from "@/generated/imv/sprite/v1/sprite_pb";

/** 发布资产是固定画布和时长的不可变片段。 */
export interface SpriteAsset {
  id: string;
  name: string;
  kind: SpriteKind;
  seconds: number;
  aspect: number;
}

/** 模板内的独立片段；时长由服务端从发布资产读取，用户仅调整开始位置。 */
export interface SpritePlacement {
  id: string;
  sprite_id: string;
  start: number;
  duration: number;
}

/** 预览消费的可见片段，独立于持久化时间与资产元数据。 */
export interface SpriteClip {
  id: string;
  spriteId: string;
  aspect: number;
  name: string;
  start: number;
  end: number;
}
