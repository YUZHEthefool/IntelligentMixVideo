/** IMS 与 Remotion 共用的项目区间转换：秒数取整到帧，末帧裁到同一个成片边界。 */
export function frameRange(start: number, end: number, duration: number, fps = 30) {
  if (![start, end, duration, fps].every(Number.isFinite) || start < 0 || duration <= 0 || !Number.isInteger(fps) || fps <= 0)
    throw new Error("视频时间区间或帧率无效");
  const first = Math.round(start * fps);
  const last = Math.min(Math.floor(duration * fps + 1e-8), Math.round(end * fps));
  return { first, last: Math.max(first, last) };
}
