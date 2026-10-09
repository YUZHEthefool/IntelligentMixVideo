/** 独立 Remotion 资产目录与选择器；项目层接收选择，目录不读写 IMS 模板或效果配置。 */
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { listSprites } from "./api";
import type { SpriteAsset } from "./model";

/** 激活页面或显式刷新时读取资产，卸载取消；资产只提供固定内容，不提供 IMS 效果选择。 */
export function SpriteCatalog({ active, disabled, onAdd, onCatalog }: {
  active: boolean; disabled: boolean; onAdd: (asset: SpriteAsset) => void; onCatalog: (assets: SpriteAsset[]) => void;
}) {
  const [assets, setAssets] = useState<SpriteAsset[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    setLoading(true); setError("");
    listSprites(controller.signal).then((values) => {
      if (!controller.signal.aborted) { setAssets(values); onCatalog(values); }
    }, (reason) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "资产库读取失败");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [active, attempt, onCatalog]);
  return <section aria-label="Remotion 资产库" className="space-y-2 border-t p-3">
    <div className="flex items-center justify-between"><h2 className="text-sm font-semibold">Remotion 资产</h2><Button type="button" size="sm" variant="ghost" disabled={loading} onClick={() => setAttempt((value) => value + 1)}>刷新资产库</Button></div>
    {loading && <p role="status" className="text-xs">正在读取 Remotion 资产…</p>}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    {!loading && !error && !assets.length && <p className="text-xs text-muted-foreground">在字效成功版本上选择「保存到资产」。</p>}
    <ul className="space-y-2">{assets.map((asset) => <li key={asset.id} className="rounded-lg border p-2 text-xs"><p className="truncate">{asset.name}</p><div className="mt-1 flex justify-between"><span>{asset.seconds.toFixed(2)} 秒</span><Button type="button" variant="outline" size="sm" disabled={disabled} aria-label={`添加 Remotion 资产：${asset.name}`} onClick={() => onAdd(asset)}>添加</Button></div></li>)}</ul>
  </section>;
}
