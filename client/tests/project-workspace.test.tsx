/**项目回归：专属接口、首次保存失败重试、切换保护和时间轴编辑；bun run test。 */
import { expect, test } from "bun:test";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { create, toBinary } from "@bufbuild/protobuf";
import { ProjectWorkspace } from "@/features/projects/ProjectWorkspace";
import { ListSpritesResponseSchema, SpriteKind } from "@/generated/imv/sprite/v1/sprite_pb";
import type { VideoProject } from "@/features/projects/model";
import { fetchMock } from "./setup";
import HomePage from "@/pages/HomePage";
import { TemplateWorkspace } from "@/features/templates/TemplateWorkspace";

/** 仅提供项目 HTTP 模拟，任何 IMS 请求都直接使测试失败。 */
function backend(options: { delayFirstSave?: boolean } = {}) {
  const records = new Map<string, VideoProject>();
  const writes: { id: string; body: Record<string, unknown> }[] = [];
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  fetchMock.mockImplementation((async (input, init) => {
    const url = new URL(String(input));
    const path = url.pathname;
    if (path === "/api/sprites") return new Response(Uint8Array.from(toBinary(ListSpritesResponseSchema, create(ListSpritesResponseSchema, { sprites: [{ spriteId: "asset-1", name: "独立标题", kind: SpriteKind.VIDEO_OVERLAY, canvas: { width: 1080, height: 1920, fps: 30, previewFrames: 90 } }] }))));
    if (path === "/api/projects") return Response.json([...records.values()]);
    expect(path.startsWith("/api/projects/")).toBe(true);
    const id = path.split("/").at(-1)!;
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body));
      writes.push({ id, body });
      if (options.delayFirstSave && writes.length === 1) return pending;
      const saved = { id, name: body.name, description: body.description, media: body.media, tracks: body.tracks, revision: body.expected_revision + 1, clips: body.clips.map((clip: object) => ({ ...clip, duration: 3 })), updated_at: "2026-10-09T00:00:00Z" };
      records.set(id, saved);
      return Response.json(saved);
    }
    if (init?.method === "DELETE") { records.delete(id); return new Response(null, { status: 204 }); }
    return records.has(id) ? Response.json(records.get(id)) : Response.json({ detail: "项目不存在" }, { status: 404 });
  }) as typeof fetch);
  return { records, writes, finish };
}

/** 用户从独立库新建草稿并添加固定片段，不需要任何 IMS 效果。 */
async function createDraft() {
  fireEvent.click(screen.getByRole("button", { name: "新建项目" }));
  fireEvent.change(screen.getByLabelText("项目名称"), { target: { value: "纯 Remotion" } });
  fireEvent.click(await screen.findByRole("button", { name: "添加 Remotion 资产：独立标题" }));
}

// 场景：只含 Remotion 资产的模板以一个 PUT 原子保存，拖动起点保留资产固定时长，重新打开后恢复。
test("项目无需 IMS 即可保存时间轴并重新打开", async () => {
  const server = backend();
  const view = render(<ProjectWorkspace />);
  await createDraft();
  fireEvent.change(screen.getByLabelText("Remotion 开始时间"), { target: { value: "0.1" } });
  expect(screen.getByLabelText<HTMLInputElement>("Remotion 开始时间").value).toBe("0.1");
  fireEvent.submit(screen.getByRole("button", { name: "保存项目" }).closest("form")!);
  await screen.findByText("已保存");
  expect(server.writes).toHaveLength(1);
  expect(server.writes[0].body).toMatchObject({ name: "纯 Remotion", expected_revision: 0, clips: [{ sprite_id: "asset-1", start: 0.1 }] });
  expect(server.writes[0].body).not.toHaveProperty("effect_ids");
  expect((server.writes[0].body.clips as object[])[0]).not.toHaveProperty("duration");
  view.unmount();
  render(<ProjectWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: "打开项目：纯 Remotion" }));
  await screen.findByText("已保存");
  fireEvent.click(screen.getByRole("button", { name: "编辑片段：独立标题" }));
  expect(screen.getByLabelText<HTMLInputElement>("Remotion 开始时间").value).toBe("0.1");
  expect(screen.getByText("固定时长 3.00 秒")).toBeTruthy();
});

// 回归：首次写入延迟失败时，名称、片段和脏状态不变；显式重试仍使用同一 ID 和 revision。
test("首次保存失败保留独立草稿并以同一 ID 重试", async () => {
  const server = backend({ delayFirstSave: true });
  render(<ProjectWorkspace />);
  await createDraft();
  fireEvent.submit(screen.getByRole("button", { name: "保存项目" }).closest("form")!);
  await waitFor(() => expect(server.writes).toHaveLength(1));
  expect(screen.getByRole("button", { name: "编辑片段：独立标题" })).toBeTruthy();
  await act(async () => server.finish(Response.json({ detail: "临时保存失败" }, { status: 503 })));
  await screen.findByText("临时保存失败");
  expect(screen.getByText("有未保存的修改")).toBeTruthy();
  expect(screen.getByLabelText<HTMLInputElement>("项目名称").value).toBe("纯 Remotion");
  expect(screen.getByRole("button", { name: "编辑片段：独立标题" })).toBeTruthy();
  fireEvent.submit(screen.getByRole("button", { name: "保存项目" }).closest("form")!);
  await screen.findByText("已保存");
  expect(server.writes).toHaveLength(2);
  expect(server.writes[1]).toEqual(server.writes[0]);
  expect(server.records.size).toBe(1);
});

// 场景：未保存新建、取消、保存并切换均保留准确状态；删除确认仅调用项目接口。
test("项目切换保护与删除", async () => {
  const server = backend();
  render(<ProjectWorkspace />);
  await createDraft();
  fireEvent.click(screen.getByRole("button", { name: "新建项目" }));
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "取消" }));
  expect(screen.getByRole("button", { name: "编辑片段：独立标题" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "新建项目" }));
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "保存并切换" }));
  await waitFor(() => expect(screen.getByLabelText<HTMLInputElement>("项目名称").value).toBe("未命名项目"));
  fireEvent.click(await screen.findByRole("button", { name: "打开项目：纯 Remotion" }));
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "放弃修改并切换" }));
  await screen.findByText("已保存");
  fireEvent.click(screen.getByRole("button", { name: "删除项目" }));
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "确认删除" }));
  await screen.findByText("选择或新建项目开始编辑。");
  expect(server.records.size).toBe(0);
});

// 场景：IMS 编辑器没有 Remotion 资产入口、不请求 Remotion；侧栏提供项目入口。
test("IMS 编辑器与项目入口完全分开", async () => {
  backend();
  const view = render(<TemplateWorkspace selection={{ environment: "cloud", templateId: null, name: "IMS", description: "" }} onHome={() => {}} />);
  await screen.findByText("新模板 · 尚未保存");
  expect(screen.queryByRole("region", { name: "Remotion 资产" })).toBeNull();
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/sprites"))).toBe(false);
  view.unmount();
  const handler = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation((async (url, init) => new URL(String(url)).pathname === "/template" ? new Response(new Uint8Array()) : handler(url, init)) as typeof fetch);
  render(<HomePage />);
  fireEvent.mouseDown(screen.getByRole("tab", { name: "视频项目" }), { button: 0, ctrlKey: false });
  expect(await screen.findByRole("region", { name: "视频项目工作区" })).toBeTruthy();
});

// 场景：IMS 效果与 Remotion 素材在同一个项目中只产生一次保存，复用同一个预览和时间轴。
test("同一项目同时保存 IMS 轨道与 Remotion 片段", async () => {
  const server = backend();
  render(<ProjectWorkspace />);
  await createDraft();
  const effects = screen.getByRole("region", { name: "特效资产" });
  fireEvent.click(within(effects).getAllByRole("button", { name: /^应用花字：/ })[0]);
  expect(screen.getAllByRole("region", { name: "实时预览" })).toHaveLength(1);
  expect(screen.getAllByRole("group", { name: "视频轨道" })).toHaveLength(1);
  expect(screen.getByLabelText("时间轴轨道标签").textContent).toContain("独立标题");
  fireEvent.submit(screen.getByRole("button", { name: "保存项目" }).closest("form")!);
  await screen.findByText("已保存");
  expect(server.writes).toHaveLength(1);
  expect(server.writes[0].body.tracks).toHaveLength(1);
  expect(server.writes[0].body.clips).toHaveLength(1);
});
