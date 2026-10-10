/** 视频项目库状态：单次保存、失败保留草稿、切换保护和取消过期读取。 */
import { useEffect, useRef, useState } from "react";
import * as api from "./api";
import { newProject, type VideoProject } from "./model";

type Navigation = { kind: "new" } | { kind: "open"; id: string } | { kind: "delete" };

/** 只请求项目路由；项目 ID 从新草稿开始保持稳定，保存无第二阶段绑定请求。 */
export function useProjects(active: boolean) {
  const [items, setItems] = useState<VideoProject[]>([]);
  const [draft, setDraft] = useState<VideoProject | null>(null);
  const [baseline, setBaseline] = useState("");
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [navigation, setNavigation] = useState<Navigation | null>(null);
  const operation = useRef<AbortController | null>(null);
  const dirty = draft !== null && (draft.revision === 0 || JSON.stringify(draft) !== baseline);

  useEffect(() => () => { operation.current?.abort(); }, []);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    setLoading(true);
    setListError("");
    api.listProjects(controller.signal).then((values) => {
      if (!controller.signal.aborted) setItems(values);
    }, (reason) => {
      if (!controller.signal.aborted) setListError(reason instanceof Error ? reason.message : "项目库读取失败");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [active, attempt]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  /** 请求期间锁定编辑；清理后的回执不会更换基线或当前项目。 */
  async function perform(action: (signal: AbortSignal) => Promise<void>): Promise<boolean> {
    if (operation.current) return false;
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true);
    setError("");
    try {
      await action(controller.signal);
      return !controller.signal.aborted;
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "操作失败，请重试");
      return false;
    } finally {
      operation.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  /** 一次请求写入全部草稿；失败不改项目 ID、片段、revision 或脏状态。 */
  async function save(): Promise<boolean> {
    if (!draft) return false;
    return perform(async (signal) => {
      const saved = await api.saveProject(draft, signal);
      if (signal.aborted) return;
      setDraft(saved);
      setBaseline(JSON.stringify(saved));
      setAttempt((value) => value + 1);
    });
  }

  /** 读取成功后才替换草稿；新建与删除也仅作用于当前项目。 */
  async function navigate(next: Navigation) {
    if (next.kind === "new") {
      setDraft(newProject()); setBaseline(""); setNavigation(null); setError("");
      return;
    }
    const ok = await perform(async (signal) => {
      if (next.kind === "delete") {
        if (!draft) return;
        await api.deleteProject(draft, signal);
        if (signal.aborted) return;
        setDraft(null); setBaseline(""); setAttempt((value) => value + 1);
      } else {
        const loaded = await api.getProject(next.id, signal);
        if (signal.aborted) return;
        setDraft(loaded); setBaseline(JSON.stringify(loaded));
      }
    });
    if (ok) setNavigation(null);
  }

  /** 库选择与重新读取共用保存/放弃/取消保护，读取失败可再次选择重试。 */
  function request(next: Navigation) {
    if (operation.current) return;
    setError("");
    if (dirty || next.kind === "delete") setNavigation(next);
    else void navigate(next);
  }

  return {
    items, draft, setDraft, dirty, error, listError, busy, loading, navigation, save, request,
    refresh: () => setAttempt((value) => value + 1),
    cancel: () => { if (!operation.current) setNavigation(null); },
    resolve: async (saveFirst: boolean) => {
      if (!navigation || operation.current) return;
      if (!saveFirst || await save()) await navigate(navigation);
    },
  };
}
