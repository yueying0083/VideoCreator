import React, { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCopy,
  Eye,
  Film,
  Image as ImageIcon,
  LayoutGrid,
  Link2,
  Loader2,
  Plus,
  Repeat,
  Rocket,
  Send,
  Sparkles,
  Star,
  Table as TableIcon,
  Trash2,
  Upload,
  Wand2,
} from "lucide-react";
import { VIDEO_ENGINE_OPTIONS, estimateVideoUsd } from "../types";
import type { Asset, JobTask, Shot, StudioDraftInjection, VideoEngine, VideoResolution } from "../types";

interface StoryboardTabProps {
  shots: Shot[];
  assets: Asset[];
  tasks?: JobTask[];
  effectiveMode: "live" | "demo";
  onCreateShot: () => Promise<void>;
  onUpdateShot: (shotId: string, patch: Partial<Shot>) => Promise<void>;
  onDeleteShot: (shotId: string) => Promise<void>;
  onGenerateKeyframe: (shotId: string, which: "start" | "end") => Promise<void>;
  onCopyPrevEndFrame: (shotId: string) => Promise<void>;
  onGenerateVideo: (
    shotId: string,
    payload: {
      engine: VideoEngine;
      duration_sec: number;
      resolution: VideoResolution;
      with_audio: boolean;
      use_end_frame: boolean;
    }
  ) => Promise<void>;
  onBatchGenerate: (payload: {
    engine: VideoEngine;
    resolution: VideoResolution;
    with_audio: boolean;
    use_end_frame: boolean;
    only_pending: boolean;
    chain_last_frame: boolean;
  }) => Promise<void>;
  onIterateTake: (
    shotId: string,
    takeId: string,
    payload: {
      action: "edit" | "extend";
      prompt: string;
      duration_sec: number;
      resolution: VideoResolution;
      strip_audio: boolean;
      ref_asset_ids: string[];
    }
  ) => Promise<void>;
  onEnhanceShotPrompt: (shot: Shot) => Promise<void>;
  onImportTake: (shotId: string, file: File) => Promise<void>;
  onRunQa: (shotId: string, takeId: string) => Promise<void>;
  onSendToStudio: (draft: Omit<StudioDraftInjection, "nonce">) => void;
  onToast: (msg: string) => void;
}

const SHOT_TYPES = ["远景", "全景", "中景", "中近景", "近景", "特写"];
const CAMERA_MOVES = ["缓慢推进", "缓慢拉远", "横摇", "侧面跟拍", "俯拍航拍", "环绕运镜", "固定机位"];
const OMNI_DURATIONS = [3, 4, 5, 6, 8, 10, 12, 15];

export const StoryboardTab: React.FC<StoryboardTabProps> = ({
  shots,
  assets,
  tasks = [],
  effectiveMode,
  onCreateShot,
  onUpdateShot,
  onDeleteShot,
  onGenerateKeyframe,
  onCopyPrevEndFrame,
  onGenerateVideo,
  onBatchGenerate,
  onIterateTake,
  onEnhanceShotPrompt,
  onImportTake,
  onRunQa,
  onSendToStudio,
  onToast,
}) => {
  const [viewMode, setViewMode] = useState<"cards" | "table">("cards");
  const [engine, setEngine] = useState<VideoEngine>("omni_flash");
  const [resolution, setResolution] = useState<VideoResolution>("720p");
  const [withAudio, setWithAudio] = useState(true);
  const [useEndFrame, setUseEndFrame] = useState(false);
  const [chainLastFrame, setChainLastFrame] = useState(true);
  const [enhancingShotId, setEnhancingShotId] = useState<string | null>(null);

  // Per-take inline Edit/Extend panel state
  const [iteratePanel, setIteratePanel] = useState<{
    shotId: string;
    takeId: string;
    action: "edit" | "extend";
    prompt: string;
    duration_sec: number;
    strip_audio: boolean;
    ref_asset_ids: string[];
  } | null>(null);

  const toggleAssetLink = (shot: Shot, assetId: string) => {
    const exists = shot.asset_ids.includes(assetId);
    const next = exists ? shot.asset_ids.filter((id) => id !== assetId) : [...shot.asset_ids, assetId];
    onUpdateShot(shot.id, { asset_ids: next });
  };

  const handleCopyFlowPack = async (shot: Shot) => {
    const prompt = shot.video_prompt_en || shot.visual_prompt_zh;
    const bundle = [
      `# Shot ${shot.order_index + 1}: ${shot.title}`,
      `Prompt: ${prompt}`,
      shot.sfx_prompt ? `Audio/SFX: ${shot.sfx_prompt}` : "",
      shot.start_frame_local_path ? `Start Frame Local Path: ${shot.start_frame_local_path}` : "",
      shot.end_frame_local_path ? `End Frame Local Path: ${shot.end_frame_local_path}` : "",
    ]
      .filter(Boolean)
      .join("\n");
    await navigator.clipboard.writeText(bundle);
    onToast("已复制 Flow 创作包（英文提示词 + 本地首帧路径）！在 Google Flow 生成后可直接导入 Take。");
  };

  const handleGenerateVideoWithConfirm = (shot: Shot) => {
    const est = estimateVideoUsd(engine, shot.duration_sec, resolution);
    if (effectiveMode === "live") {
      const ok = confirm(
        `确认调用 ${engine} (${resolution}) 生成「${shot.title}」(${shot.duration_sec}s)？\n预估消耗约 $${est} USD（将从你的 Google 开发者额度抵扣）。`
      );
      if (!ok) return;
    }
    onGenerateVideo(shot.id, {
      engine,
      duration_sec: shot.duration_sec,
      resolution,
      with_audio: withAudio,
      use_end_frame: useEndFrame && Boolean(shot.end_frame_url),
    });
  };

  const handleBatchShoot = () => {
    const pendingShots = shots.filter((s) => s.takes.length === 0);
    if (pendingShots.length === 0) {
      onToast("当前分镜均已有视频 Take（如需重拍请点击单镜生成或删除旧 Take）。");
      return;
    }
    const estTotal = pendingShots
      .reduce((acc, s) => acc + Number(estimateVideoUsd(engine, s.duration_sec, resolution)), 0)
      .toFixed(2);
    if (effectiveMode === "live") {
      const ok = confirm(
        `确认批量拍摄 ${pendingShots.length} 个待拍镜头（${chainLastFrame ? "尾帧自动接力顺序拍" : "高速并行拍"} · ${engine} ${resolution}）？\n预估总消耗约 $${estTotal} USD。`
      );
      if (!ok) return;
    }
    onBatchGenerate({
      engine,
      resolution,
      with_audio: withAudio,
      use_end_frame: useEndFrame,
      only_pending: true,
      chain_last_frame: chainLastFrame,
    });
  };

  const handleEnhancePrompt = async (shot: Shot) => {
    setEnhancingShotId(shot.id);
    try {
      await onEnhanceShotPrompt(shot);
    } finally {
      setEnhancingShotId(null);
    }
  };

  const durationChoices = OMNI_DURATIONS;

  return (
    <div className="space-y-4 p-5">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-studio-border bg-studio-card p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border border-studio-border bg-studio-bg p-0.5">
            <button
              className={`studio-btn py-1 ${viewMode === "cards" ? "bg-indigo-600 text-white" : "text-slate-400"}`}
              onClick={() => setViewMode("cards")}
            >
              <LayoutGrid className="h-3.5 w-3.5" /> 卡片视图
            </button>
            <button
              className={`studio-btn py-1 ${viewMode === "table" ? "bg-indigo-600 text-white" : "text-slate-400"}`}
              onClick={() => setViewMode("table")}
            >
              <TableIcon className="h-3.5 w-3.5" /> 表格视图
            </button>
          </div>

          <button className="studio-btn-primary" onClick={onCreateShot}>
            <Plus className="h-3.5 w-3.5" /> 新增镜头
          </button>

          {shots.length > 0 && (
            <div className="flex items-center gap-2 rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-1">
              <label
                className="flex cursor-pointer items-center gap-1.5 text-[11px] text-indigo-200"
                title="开启后按顺序自动抽取上一镜尾帧作为下一镜首帧，保证动作连贯"
              >
                <input
                  type="checkbox"
                  checked={chainLastFrame}
                  onChange={(e) => setChainLastFrame(e.target.checked)}
                  className="rounded border-studio-border bg-studio-bg text-indigo-500"
                />
                尾帧接力
              </label>
              <button
                className="studio-btn-primary py-1 text-[11px]"
                onClick={handleBatchShoot}
              >
                <Rocket className="h-3 w-3" />
                一键批量拍片
              </button>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="text-slate-400">视频引擎:</span>
            <select
              className="rounded-lg border border-studio-border bg-studio-bg px-2.5 py-1 text-xs text-slate-100"
              value={engine}
              onChange={(e) => setEngine(e.target.value as VideoEngine)}
            >
              {VIDEO_ENGINE_OPTIONS.map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.label} · {opt.desc}
                </option>
              ))}
            </select>
          </div>

          {engine === "omni_flash" && (
            <div className="flex items-center gap-1.5">
              <span className="text-slate-400">清晰度:</span>
              <select
                className="rounded-lg border border-studio-border bg-studio-bg px-2 py-1 text-xs text-slate-100"
                value={resolution}
                onChange={(e) => setResolution(e.target.value as VideoResolution)}
              >
                <option value="360p">360p</option>
                <option value="720p">720p</option>
                <option value="1080p">1080p</option>
                <option value="4k">4K</option>
              </select>
            </div>
          )}

          <label className="flex cursor-pointer items-center gap-1.5 text-slate-300">
            <input
              type="checkbox"
              checked={withAudio}
              onChange={(e) => setWithAudio(e.target.checked)}
              className="rounded border-studio-border bg-studio-bg text-indigo-500"
            />
            原生同期声
          </label>

          <label className="flex cursor-pointer items-center gap-1.5 text-slate-300">
            <input
              type="checkbox"
              checked={useEndFrame}
              onChange={(e) => setUseEndFrame(e.target.checked)}
              className="rounded border-studio-border bg-studio-bg text-indigo-500"
            />
            启用首尾帧过渡
          </label>
        </div>
      </div>

      {shots.length === 0 ? (
        <div className="rounded-xl border border-dashed border-studio-border p-12 text-center text-sm text-slate-500">
          分镜板还是空的。可以在左侧与 AI 导演对话一键生成结构化分镜，或点击上方「新增镜头」。
        </div>
      ) : viewMode === "table" ? (
        <div className="overflow-x-auto rounded-xl border border-studio-border bg-studio-card">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-studio-border bg-studio-bg text-slate-400">
              <tr>
                <th className="p-3">#</th>
                <th className="p-3">镜头标题 / 景别 / 运镜</th>
                <th className="p-3">中文画面描述</th>
                <th className="p-3">台词 / 音效</th>
                <th className="p-3">时长</th>
                <th className="p-3">状态</th>
                <th className="p-3">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-studio-border">
              {shots.map((shot, idx) => (
                <tr key={shot.id} className="hover:bg-slate-800/40">
                  <td className="p-3 font-mono text-slate-400">{idx + 1}</td>
                  <td className="p-3">
                    <div className="font-medium text-white">{shot.title}</div>
                    <div className="text-[11px] text-slate-400">
                      {shot.shot_type} · {shot.camera_movement}
                    </div>
                  </td>
                  <td className="max-w-xs p-3 text-slate-300">{shot.visual_prompt_zh || "-"}</td>
                  <td className="max-w-xs p-3 text-slate-400">
                    {shot.dialogue && <div>“{shot.dialogue}”</div>}
                    {shot.sfx_prompt && <div className="text-[11px] text-slate-500">SFX: {shot.sfx_prompt}</div>}
                  </td>
                  <td className="p-3 font-mono">{shot.duration_sec}s</td>
                  <td className="p-3">
                    <div className="flex flex-col gap-1 text-[11px]">
                      <span className={shot.start_frame_url ? "text-emerald-400" : "text-slate-500"}>
                        {shot.start_frame_url ? "✓ 已有首帧" : "○ 待首帧"}
                      </span>
                      <span className={shot.takes.length > 0 ? "text-indigo-300" : "text-slate-500"}>
                        {shot.takes.length > 0 ? `✓ ${shot.takes.length} 个 Take` : "○ 待视频"}
                      </span>
                    </div>
                  </td>
                  <td className="p-3">
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        className="studio-btn-secondary py-1 text-[11px]"
                        onClick={() => onGenerateKeyframe(shot.id, "start")}
                      >
                        首帧
                      </button>
                      <button
                        className="studio-btn-primary py-1 text-[11px]"
                        onClick={() => handleGenerateVideoWithConfirm(shot)}
                      >
                        出视频 (${estimateVideoUsd(engine, shot.duration_sec, resolution)})
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="space-y-4">
          {shots.map((shot, idx) => {
            const selectedTake =
              shot.takes.find((t) => t.id === shot.selected_take_id) || shot.takes[0] || null;
            const isIterOpen = iteratePanel && iteratePanel.shotId === shot.id && selectedTake?.id === iteratePanel.takeId;
            const latestShotTask = tasks.find((t) => t.shot_id === shot.id) || null;

            return (
              <div
                key={shot.id}
                className="rounded-xl border border-studio-border bg-studio-card p-4 shadow-sm"
              >
                {/* Shot Header */}
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-studio-border/60 pb-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-md bg-indigo-600/20 font-mono text-xs font-bold text-indigo-300">
                      {idx + 1}
                    </span>
                    <input
                      className="w-48 rounded border border-transparent bg-transparent px-1.5 py-0.5 text-sm font-semibold text-white hover:border-studio-border focus:border-indigo-500 focus:bg-studio-bg focus:outline-none"
                      defaultValue={shot.title}
                      onBlur={(e) => {
                        if (e.target.value !== shot.title) onUpdateShot(shot.id, { title: e.target.value });
                      }}
                    />
                    <select
                      className="rounded border border-studio-border bg-studio-bg px-2 py-1 text-xs text-slate-200"
                      value={shot.shot_type}
                      onChange={(e) => onUpdateShot(shot.id, { shot_type: e.target.value })}
                    >
                      {SHOT_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                    <select
                      className="rounded border border-studio-border bg-studio-bg px-2 py-1 text-xs text-slate-200"
                      value={shot.camera_movement}
                      onChange={(e) => onUpdateShot(shot.id, { camera_movement: e.target.value })}
                    >
                      {CAMERA_MOVES.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                    <select
                      className="rounded border border-studio-border bg-studio-bg px-2 py-1 font-mono text-xs text-slate-200"
                      value={shot.duration_sec}
                      onChange={(e) => onUpdateShot(shot.id, { duration_sec: Number(e.target.value) })}
                    >
                      {!durationChoices.includes(shot.duration_sec) && (
                        <option value={shot.duration_sec}>{shot.duration_sec}s</option>
                      )}
                      {durationChoices.map((sec) => (
                        <option key={sec} value={sec}>
                          {sec}s
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <button
                      className="studio-btn-secondary text-[11px]"
                      onClick={() =>
                        onSendToStudio({
                          tabMode: "create",
                          prompt: shot.visual_prompt_zh || shot.video_prompt_en,
                          enhancedPrompt: shot.video_prompt_en,
                          addRefImageAssetId: shot.asset_ids[0],
                        })
                      }
                      title="发送本镜头提示词与参考资产到「全模态自由创作台」精修"
                    >
                      <Send className="h-3.5 w-3.5 text-indigo-400" />
                      去自由创作台
                    </button>
                    <button
                      className="studio-btn-secondary text-[11px]"
                      onClick={() => handleCopyFlowPack(shot)}
                      title="一键复制英文提示词 + 首帧路径，方便去 Google Flow 用 25,000 Ultra 积分免费生成"
                    >
                      <ClipboardCopy className="h-3.5 w-3.5 text-emerald-400" />
                      复制 Flow 创作包
                    </button>
                    <label
                      className="studio-btn-secondary cursor-pointer text-[11px]"
                      title="将外部（如 Google Flow）生成的 MP4 拖入或选择导入作为新 Take"
                    >
                      <Upload className="h-3.5 w-3.5 text-sky-400" />
                      导入外部 Take
                      <input
                        type="file"
                        accept="video/*"
                        className="hidden"
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f) onImportTake(shot.id, f);
                          e.target.value = "";
                        }}
                      />
                    </label>
                    <button
                      className="studio-btn-ghost text-rose-400 hover:text-rose-300"
                      onClick={() => onDeleteShot(shot.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>

                {/* Inline task progress / last failure for this shot */}
                {latestShotTask && (latestShotTask.status === "queued" || latestShotTask.status === "running") && (
                  <div className="mb-3 rounded-lg border border-indigo-500/30 bg-indigo-950/30 px-3 py-2 text-xs text-indigo-200">
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5">
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-400" />
                        <span>{latestShotTask.message}</span>
                      </span>
                      <span className="font-mono text-[11px]">{latestShotTask.progress}%</span>
                    </div>
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800">
                      <div
                        className="h-full bg-indigo-500 transition-all duration-300"
                        style={{ width: `${Math.max(4, latestShotTask.progress)}%` }}
                      />
                    </div>
                  </div>
                )}
                {latestShotTask && latestShotTask.status === "failed" && (
                  <div className="mb-3 flex items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-950/40 px-3 py-2 text-xs text-rose-200">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-400" />
                    <div className="min-w-0 flex-1 break-all">
                      <span className="font-medium">上次生成失败：</span>
                      <span>{latestShotTask.error || latestShotTask.message}</span>
                    </div>
                  </div>
                )}

                {/* Body: Left prompts & assets | Right keyframes & video player */}
                <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
                  {/* Prompts Column */}
                  <div className="space-y-2.5 xl:col-span-6">
                    {assets.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-[11px] text-slate-400">绑定一致性资产:</span>
                        {assets.map((a) => {
                          const active = shot.asset_ids.includes(a.id);
                          return (
                            <button
                              key={a.id}
                              type="button"
                              onClick={() => toggleAssetLink(shot, a.id)}
                              className={`rounded-full px-2 py-0.5 text-[11px] transition ${
                                active
                                  ? "bg-indigo-600 text-white"
                                  : "border border-studio-border bg-studio-bg text-slate-400 hover:text-slate-200"
                              }`}
                            >
                              @{a.name}
                            </button>
                          );
                        })}
                      </div>
                    )}

                    <div>
                      <label className="mb-1 block text-[11px] text-slate-400">中文画面描述</label>
                      <textarea
                        rows={2}
                        className="studio-input text-xs"
                        defaultValue={shot.visual_prompt_zh}
                        key={shot.id + "_zh_" + shot.visual_prompt_zh}
                        onBlur={(e) => {
                          if (e.target.value !== shot.visual_prompt_zh) {
                            onUpdateShot(shot.id, { visual_prompt_zh: e.target.value });
                          }
                        }}
                      />
                    </div>

                    <div>
                      <div className="mb-1 flex items-center justify-between">
                        <label className="text-[11px] text-slate-400">
                          电影级英文提示词（用于 Gemini Omni 1.2 / 关键帧 / Flow）
                        </label>
                        <button
                          type="button"
                          disabled={enhancingShotId === shot.id}
                          onClick={() => handleEnhancePrompt(shot)}
                          className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] text-indigo-300 hover:bg-indigo-500/15"
                        >
                          <Wand2 className="h-3 w-3" />
                          {enhancingShotId === shot.id ? "Gemini 4 扩写中..." : "AI 扩写"}
                        </button>
                      </div>
                      <textarea
                        rows={2}
                        className="studio-input font-mono text-[11px]"
                        defaultValue={shot.video_prompt_en}
                        key={shot.id + "_en_" + shot.video_prompt_en}
                        onBlur={(e) => {
                          if (e.target.value !== shot.video_prompt_en) {
                            onUpdateShot(shot.id, { video_prompt_en: e.target.value });
                          }
                        }}
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">对白 / 旁白（可转字幕）</label>
                        <input
                          className="studio-input text-xs"
                          defaultValue={shot.dialogue}
                          placeholder="留空则无对白"
                          onBlur={(e) => {
                            if (e.target.value !== shot.dialogue) {
                              onUpdateShot(shot.id, { dialogue: e.target.value });
                            }
                          }}
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">同期声 / 音效 SFX</label>
                        <input
                          className="studio-input text-xs"
                          defaultValue={shot.sfx_prompt}
                          placeholder="如：细雨声、脚步声"
                          onBlur={(e) => {
                            if (e.target.value !== shot.sfx_prompt) {
                              onUpdateShot(shot.id, { sfx_prompt: e.target.value });
                            }
                          }}
                        />
                      </div>
                    </div>
                  </div>

                  {/* Media Column */}
                  <div className="space-y-3 xl:col-span-6">
                    {/* Start / End Frames */}
                    <div className="grid grid-cols-2 gap-2">
                      <div className="space-y-1.5">
                        <div className="relative aspect-video overflow-hidden rounded-lg border border-studio-border bg-studio-bg">
                          {shot.start_frame_url ? (
                            <img src={shot.start_frame_url} alt="start frame" className="h-full w-full object-cover" />
                          ) : (
                            <div className="flex h-full flex-col items-center justify-center gap-1 text-[11px] text-slate-600">
                              <ImageIcon className="h-5 w-5" />
                              首帧关键帧
                            </div>
                          )}
                          <span className="absolute left-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-slate-200">
                            首帧
                          </span>
                        </div>
                        <div className="flex gap-1">
                          <button
                            className="studio-btn-secondary flex-1 py-1 text-[11px]"
                            onClick={() => onGenerateKeyframe(shot.id, "start")}
                          >
                            <Sparkles className="h-3 w-3 text-indigo-400" />
                            合成首帧 ($0.06)
                          </button>
                          {idx > 0 && (
                            <button
                              className="studio-btn-secondary px-2 py-1 text-[11px]"
                              onClick={() => onCopyPrevEndFrame(shot.id)}
                              title="提取上一镜头的尾帧作为本镜首帧，确保丝滑连贯"
                            >
                              <Link2 className="h-3 w-3 text-emerald-400" />
                            </button>
                          )}
                        </div>
                      </div>

                      <div className="space-y-1.5">
                        <div className="relative aspect-video overflow-hidden rounded-lg border border-studio-border bg-studio-bg">
                          {shot.end_frame_url ? (
                            <img src={shot.end_frame_url} alt="end frame" className="h-full w-full object-cover" />
                          ) : (
                            <div className="flex h-full flex-col items-center justify-center gap-1 text-[11px] text-slate-600">
                              <ImageIcon className="h-5 w-5" />
                              尾帧（可选过渡）
                            </div>
                          )}
                          <span className="absolute left-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-slate-200">
                            尾帧
                          </span>
                        </div>
                        <button
                          className="studio-btn-secondary w-full py-1 text-[11px]"
                          onClick={() => onGenerateKeyframe(shot.id, "end")}
                        >
                          <Sparkles className="h-3 w-3 text-slate-400" />
                          合成尾帧 ($0.06)
                        </button>
                      </div>
                    </div>

                    {/* Video Take Player & Controls */}
                    <div className="rounded-lg border border-studio-border bg-studio-bg p-2.5">
                      {selectedTake ? (
                        <div className="space-y-2">
                          <video
                            key={selectedTake.id}
                            src={selectedTake.file_url}
                            controls
                            className="aspect-video w-full rounded bg-black"
                          />
                          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
                            <div className="flex flex-wrap items-center gap-1">
                              {shot.takes.map((t, tIdx) => {
                                const isSel = t.id === selectedTake.id;
                                return (
                                  <button
                                    key={t.id}
                                    onClick={() => onUpdateShot(shot.id, { selected_take_id: t.id })}
                                    className={`inline-flex items-center gap-1 rounded px-2 py-0.5 ${
                                      isSel
                                        ? "bg-emerald-600/25 text-emerald-300 ring-1 ring-emerald-500/40"
                                        : "bg-studio-card text-slate-400 hover:text-white"
                                    }`}
                                  >
                                    {isSel && <CheckCircle2 className="h-3 w-3" />}
                                    Take {shot.takes.length - tIdx} ({t.engine}
                                    {t.mode && t.mode !== "generate" ? `·${t.mode}` : ""})
                                    {t.qa_score !== null && (
                                      <span className="ml-0.5 text-amber-300">★{t.qa_score}</span>
                                    )}
                                  </button>
                                );
                              })}
                            </div>

                            <div className="flex flex-wrap items-center gap-1">
                              <button
                                className="studio-btn-secondary py-1 text-[11px]"
                                onClick={() =>
                                  setIteratePanel(
                                    isIterOpen && iteratePanel?.action === "edit"
                                      ? null
                                      : {
                                          shotId: shot.id,
                                          takeId: selectedTake.id,
                                          action: "edit",
                                          prompt: "Make lighting more dramatic, keep everything else the same.",
                                          duration_sec: Math.min(15, Math.max(3, Math.round(selectedTake.duration_sec || 6))),
                                          strip_audio: false,
                                          ref_asset_ids: [],
                                        }
                                  )
                                }
                              >
                                <Wand2 className="h-3 w-3 text-indigo-400" />
                                多轮改片
                              </button>
                              <button
                                className="studio-btn-secondary py-1 text-[11px]"
                                onClick={() =>
                                  setIteratePanel(
                                    isIterOpen && iteratePanel?.action === "extend"
                                      ? null
                                      : {
                                          shotId: shot.id,
                                          takeId: selectedTake.id,
                                          action: "extend",
                                          prompt: "Extend this video seamlessly as the camera pushes forward.",
                                          duration_sec: 6,
                                          strip_audio: false,
                                          ref_asset_ids: [],
                                        }
                                  )
                                }
                              >
                                <Repeat className="h-3 w-3 text-cyan-400" />
                                续写
                              </button>
                              <button
                                className="studio-btn-secondary py-1 text-[11px]"
                                onClick={() => onRunQa(shot.id, selectedTake.id)}
                              >
                                <Eye className="h-3 w-3 text-amber-400" />
                                Gemini 4 审片
                              </button>
                            </div>
                          </div>

                          {/* Inline Edit / Extend Panel */}
                          {isIterOpen && iteratePanel && (
                            <div className="space-y-2 rounded-lg border border-indigo-500/35 bg-studio-card p-2.5 text-xs">
                              <div className="flex items-center justify-between">
                                <span className="font-semibold text-indigo-300">
                                  Omni 1.2 Flash · {iteratePanel.action === "extend" ? "视频续写 (3–10s)" : "自然语言改片"}
                                  {selectedTake.interaction_id ? "（支持无损状态迭代）" : "（自动上传视频源改片）"}
                                </span>
                                <button
                                  className="text-[11px] text-slate-400 hover:text-white"
                                  onClick={() => setIteratePanel(null)}
                                >
                                  收起
                                </button>
                              </div>
                              <textarea
                                rows={2}
                                className="studio-input text-xs"
                                value={iteratePanel.prompt}
                                onChange={(e) =>
                                  setIteratePanel({ ...iteratePanel, prompt: e.target.value })
                                }
                                placeholder={
                                  iteratePanel.action === "extend"
                                    ? "输入续写剧情（例如：Extend this video: the character turns and walks toward the neon doorway.）"
                                    : "输入修改指令（例如：Change lighting to golden sunset, keep everything else the same.）"
                                }
                              />
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-300">
                                  <label className="flex items-center gap-1">
                                    时长:
                                    <select
                                      className="rounded border border-studio-border bg-studio-bg px-1.5 py-0.5"
                                      value={iteratePanel.duration_sec}
                                      onChange={(e) =>
                                        setIteratePanel({
                                          ...iteratePanel,
                                          duration_sec: Number(e.target.value),
                                        })
                                      }
                                    >
                                      {(iteratePanel.action === "extend" ? [4, 6, 8, 10] : [4, 6, 8, 10, 12, 15]).map(
                                        (sec) => (
                                          <option key={sec} value={sec}>
                                            {sec}s
                                          </option>
                                        )
                                      )}
                                    </select>
                                  </label>
                                  <label className="flex cursor-pointer items-center gap-1">
                                    <input
                                      type="checkbox"
                                      checked={iteratePanel.strip_audio}
                                      onChange={(e) =>
                                        setIteratePanel({
                                          ...iteratePanel,
                                          strip_audio: e.target.checked,
                                        })
                                      }
                                    />
                                    剥离原声重配
                                  </label>
                                </div>
                                <button
                                  className="studio-btn-primary py-1 text-[11px]"
                                  onClick={async () => {
                                    await onIterateTake(shot.id, selectedTake.id, {
                                      action: iteratePanel.action,
                                      prompt: iteratePanel.prompt,
                                      duration_sec: iteratePanel.duration_sec,
                                      resolution,
                                      strip_audio: iteratePanel.strip_audio,
                                      ref_asset_ids: iteratePanel.ref_asset_ids,
                                    });
                                    setIteratePanel(null);
                                  }}
                                >
                                  提交{iteratePanel.action === "extend" ? "续写" : "改片"}
                                </button>
                              </div>
                            </div>
                          )}

                          {selectedTake.qa_feedback && (
                            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2 text-[11px] leading-relaxed text-amber-200">
                              <div className="mb-0.5 flex items-center gap-1 font-semibold">
                                <Star className="h-3 w-3 fill-amber-400 text-amber-400" />
                                AI 审片评分：{selectedTake.qa_score}/10
                              </div>
                              <div className="whitespace-pre-wrap">{selectedTake.qa_feedback}</div>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="flex h-28 flex-col items-center justify-center gap-1 text-xs text-slate-500">
                          <Film className="h-6 w-6" />
                          <span>尚无视频 Take（建议先合成首帧，再用 Omni 1.2 或 Flow 生成）</span>
                        </div>
                      )}

                      <div className="mt-2.5 flex items-center justify-between gap-2">
                        <span className="text-[11px] text-slate-400">
                          当前引擎: <strong className="text-slate-200">{engine}</strong>
                          {engine === "omni_flash" && ` · ${resolution}`}
                        </span>
                        <button
                          className="studio-btn-primary"
                          onClick={() => handleGenerateVideoWithConfirm(shot)}
                        >
                          <Film className="h-3.5 w-3.5" />
                          生成视频 ({shot.duration_sec}s · ~${estimateVideoUsd(engine, shot.duration_sec, resolution)})
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
