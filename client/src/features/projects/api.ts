/** 项目聚合 API：一次保存共用媒体、IMS 效果与 Remotion 片段，不先创建任何 IMS 模板。 */
import { apiBase } from "@/lib/api-base";
import type { VideoProject } from "./model";

/** 有界 JSON 请求；失败不重发写入，取消时忽略迟到结果。 */
async function request<T>(path: string, method = "GET", signal?: AbortSignal, body?: object): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, 20_000);
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  try {
    const response = await fetch(`${apiBase()}/api/projects${path}`, {
      method, signal: controller.signal, headers: { Accept: "application/json", ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      const { detail } = await response.json().catch(() => ({}));
      throw new Error(typeof detail === "string" ? detail : Array.isArray(detail) ? "项目字段无效，请检查媒体和轨道设置。" : `请求失败（HTTP ${response.status}）`);
    }
    return response.status === 204 ? undefined as T : await response.json() as T;
  } catch (error) {
    if (timedOut) throw new Error("请求超时，项目草稿已保留；请重新读取确认保存结果。");
    throw error;
  } finally {
    clearTimeout(timer); signal?.removeEventListener("abort", abort);
  }
}

/** 查询项目库，列表与 IMS 模板库互不混用。 */
export const listProjects = (signal?: AbortSignal) => request<VideoProject[]>("", "GET", signal);
/** 读取该项目的统一媒体与时间轴。 */
export const getProject = (id: string, signal?: AbortSignal) => request<VideoProject>(`/${encodeURIComponent(id)}`, "GET", signal);
/** 同一次写入保存全部轨道；片段时长从发布资产推导。 */
export function saveProject(project: VideoProject, signal?: AbortSignal) {
  const { name, description, media, tracks, clips, revision } = project;
  return request<VideoProject>(`/${encodeURIComponent(project.id)}`, "PUT", signal, {
    name, description, media, tracks, expected_revision: revision,
    clips: clips.map(({ id, sprite_id, start }) => ({ id, sprite_id, start })),
  });
}
/** 只删除读取到的 revision，不删除任何发布资产或 IMS 模板。 */
export const deleteProject = (project: VideoProject, signal?: AbortSignal) => request<void>(`/${encodeURIComponent(project.id)}?expected_revision=${project.revision}`, "DELETE", signal);
