/** 新会话的固定初始画布与成功版本配置展示；最终时长采用服务端组合结果。 */
import type { Composition } from "./model";

/** 首次创建显式携带固定规格；五秒只作为开始规划前的初始时长。 */
export function defaultComposition(): Composition {
  return { width: 1080, height: 1920, fps: 30, duration_in_frames: 150 };
}

/** 展示成功版本真实的整帧时长，包括历史版本原有的画布规格。 */
export function compositionSummary(value: Composition): string {
  const seconds = Number((value.duration_in_frames / value.fps).toFixed(3));
  return `${value.width}×${value.height} · ${value.fps} FPS · ${seconds} 秒（${value.duration_in_frames} 帧）`;
}
