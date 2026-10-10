/** 项目拥有共用的母版画布和时间轴，IMS 效果与 Remotion 片段分别存储各自内容。 */
import type { EffectTrack, MasterVideo } from "@/features/templates/model";
import type { SpritePlacement } from "@/features/sprites/model";

/** 一份项目快照：媒体决定画布与源时长，全部轨道在同一事务中保存。 */
export interface VideoProject {
  id: string;
  name: string;
  description: string;
  media: MasterVideo | null;
  tracks: EffectTrack[];
  clips: SpritePlacement[];
  revision: number;
  updated_at?: string;
}

/** UUID 在首次保存前建立，失败重试不会创建另一个项目。 */
export function newProject(): VideoProject {
  return { id: crypto.randomUUID(), name: "未命名项目", description: "", media: null, tracks: [], clips: [], revision: 0 };
}
