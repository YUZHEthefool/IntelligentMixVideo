/** 说明新组合的固定画布；实例内容、布局和最终时长由聊天需求与组合结果确定。 */

/** 新会话不提供与服务端固定规格冲突的画布或类型选项。 */
export function CompositionSettings() {
  return (
    <section
      aria-label="生成配置"
      className="space-y-2 rounded-xl border bg-muted/30 p-3"
    >
      <p className="text-sm font-medium">竖屏 1080×1920 · 30 FPS</p>
      <p className="text-xs text-muted-foreground">
        描述你需要的内容、布局和动画。最终时长由各实例的时间编排确定。
      </p>
    </section>
  );
}
