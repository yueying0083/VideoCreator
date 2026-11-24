import type {
  Asset,
  BudgetSummary,
  ChatMessage,
  Episode,
  ExportRecord,
  JobTask,
  Project,
  Settings,
  Shot,
  Take,
  VideoEngine,
} from "./types";

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      msg = body.detail || JSON.stringify(body);
    } catch {
      msg = await res.text();
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // Settings & Budget
  getSettings: () => req<Settings>("/api/settings"),
  updateSettings: (payload: Partial<Settings> & { gemini_api_key?: string }) =>
    req<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(payload) }),
  getBudget: () => req<BudgetSummary>("/api/settings/budget"),

  // Projects
  listProjects: () => req<Project[]>("/api/projects"),
  createProject: (payload: { name: string; description?: string; aspect_ratio?: string; style_prompt?: string }) =>
    req<Project>("/api/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (id: string, payload: Partial<Project>) =>
    req<Project>(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteProject: (id: string) => req<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),

  // Novel Import & Auto-Split
  listEpisodes: (pid: string) => req<Episode[]>(`/api/projects/${pid}/novel/episodes`),
  importNovelText: (
    pid: string,
    payload: {
      novel_title: string;
      text: string;
      split_mode: "auto_chapter" | "by_length";
      chars_per_episode: number;
      replace_existing: boolean;
    }
  ) => req<Episode[]>(`/api/projects/${pid}/novel/import-text`, { method: "POST", body: JSON.stringify(payload) }),
  importNovelFile: (
    pid: string,
    file: File,
    split_mode: "auto_chapter" | "by_length",
    chars_per_episode: number,
    replace_existing: boolean
  ) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("split_mode", split_mode);
    fd.append("chars_per_episode", String(chars_per_episode));
    fd.append("replace_existing", String(replace_existing));
    return req<Episode[]>(`/api/projects/${pid}/novel/import-file`, { method: "POST", body: fd });
  },
  updateEpisode: (pid: string, eid: string, payload: Partial<Episode>) =>
    req<Episode>(`/api/projects/${pid}/novel/episodes/${eid}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteEpisode: (pid: string, eid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/novel/episodes/${eid}`, { method: "DELETE" }),
  extractBookBible: (pid: string, max_episodes = 20) =>
    req<JobTask>(`/api/projects/${pid}/novel/extract-bible`, {
      method: "POST",
      body: JSON.stringify({ max_episodes }),
    }),
  breakdownEpisode: (pid: string, eid: string, target_shots: number, replace_existing = true) =>
    req<JobTask>(`/api/projects/${pid}/novel/episodes/${eid}/breakdown`, {
      method: "POST",
      body: JSON.stringify({ target_shots, replace_existing }),
    }),

  // Assets
  listAssets: (pid: string) => req<Asset[]>(`/api/projects/${pid}/assets`),
  createAsset: (pid: string, payload: { name: string; kind: string; description: string }) =>
    req<Asset>(`/api/projects/${pid}/assets`, { method: "POST", body: JSON.stringify(payload) }),
  updateAsset: (pid: string, aid: string, payload: Partial<Asset>) =>
    req<Asset>(`/api/projects/${pid}/assets/${aid}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteAsset: (pid: string, aid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/assets/${aid}`, { method: "DELETE" }),
  uploadAssetFile: (pid: string, aid: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<Asset>(`/api/projects/${pid}/assets/${aid}/upload`, { method: "POST", body: fd });
  },
  generateAssetImage: (pid: string, aid: string, prompt_override?: string) =>
    req<JobTask>(`/api/projects/${pid}/assets/${aid}/generate`, {
      method: "POST",
      body: JSON.stringify({ prompt_override }),
    }),
  generateAssetTurnaround: (pid: string, aid: string) =>
    req<JobTask>(`/api/projects/${pid}/assets/${aid}/turnaround`, { method: "POST" }),

  // Shots & Takes
  listShots: (pid: string) => req<Shot[]>(`/api/projects/${pid}/shots`),
  createShot: (pid: string, payload: Partial<Shot>) =>
    req<Shot>(`/api/projects/${pid}/shots`, { method: "POST", body: JSON.stringify(payload) }),
  updateShot: (pid: string, sid: string, payload: Partial<Shot>) =>
    req<Shot>(`/api/projects/${pid}/shots/${sid}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteShot: (pid: string, sid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/shots/${sid}`, { method: "DELETE" }),
  reorderShots: (pid: string, shotIds: string[]) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/shots/reorder`, {
      method: "POST",
      body: JSON.stringify(shotIds),
    }),
  generateKeyframe: (pid: string, sid: string, which: "start" | "end", prompt_override?: string) =>
    req<JobTask>(`/api/projects/${pid}/shots/${sid}/keyframe/generate`, {
      method: "POST",
      body: JSON.stringify({ which, prompt_override }),
    }),
  copyPrevShotEndFrame: (pid: string, sid: string) =>
    req<Shot>(`/api/projects/${pid}/shots/${sid}/keyframe/from-prev-end`, { method: "POST" }),
  generateVideo: (
    pid: string,
    sid: string,
    payload: { engine: VideoEngine; duration_sec: number; with_audio: boolean; use_end_frame: boolean }
  ) =>
    req<JobTask>(`/api/projects/${pid}/shots/${sid}/video/generate`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  importTake: (pid: string, sid: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<Take>(`/api/projects/${pid}/shots/${sid}/takes/import`, { method: "POST", body: fd });
  },
  runTakeQa: (pid: string, sid: string, tid: string) =>
    req<JobTask>(`/api/projects/${pid}/shots/${sid}/takes/${tid}/qa`, { method: "POST" }),

  // Director Chat
  listChat: (pid: string) => req<ChatMessage[]>(`/api/projects/${pid}/chat`),
  sendChat: (pid: string, content: string) =>
    req<ChatMessage>(`/api/projects/${pid}/chat`, { method: "POST", body: JSON.stringify({ content }) }),
  applyProposal: (pid: string, mid: string) =>
    req<{ ok: boolean; applied_shots: number; applied_assets: number }>(`/api/projects/${pid}/chat/${mid}/apply`, {
      method: "POST",
    }),

  // Audio & Subtitles
  generateBgm: (pid: string, prompt: string, mode: "clip" | "pro") =>
    req<JobTask>(`/api/projects/${pid}/audio/bgm/generate`, {
      method: "POST",
      body: JSON.stringify({ prompt, mode }),
    }),
  uploadBgm: (pid: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<{ bgm_url: string }>(`/api/projects/${pid}/audio/bgm/upload`, { method: "POST", body: fd });
  },
  autoSubtitles: (pid: string, episode_id?: string | null) =>
    req<{ subtitle_srt: string }>(
      `/api/projects/${pid}/audio/subtitles/auto-from-script${episode_id ? `?episode_id=${episode_id}` : ""}`,
      { method: "POST" }
    ),

  // Tasks & Exports
  listTasks: (pid?: string) => req<JobTask[]>(pid ? `/api/tasks?project_id=${pid}` : "/api/tasks"),
  listExports: (pid: string) => req<ExportRecord[]>(`/api/projects/${pid}/exports`),
  createExport: (
    pid: string,
    payload: { episode_id?: string | null; resolution: "720p" | "1080p"; include_bgm: boolean; burn_subtitles: boolean }
  ) => req<JobTask>(`/api/projects/${pid}/exports`, { method: "POST", body: JSON.stringify(payload) }),
};
