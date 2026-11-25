import React, { useEffect, useMemo, useState } from "react";
import {
  Camera,
  CheckCircle2,
  Clock,
  Film,
  GitBranch,
  Image as ImageIcon,
  Layers,
  Loader2,
  Repeat,
  Save,
  Send,
  Sparkles,
  Trash2,
  Upload,
  Video,
  VolumeX,
  Wand2,
  X,
} from "lucide-react";
import { api, formatBytes, formatDuration } from "../api";
import { estimateVideoUsd } from "../types";
import type {
  Asset,
  EnhancedPromptResult,
  Project,
  Settings,
  Shot,
  StudioDraftInjection,
  StudioJob,
  VideoResolution,
} from "../types";

type TabMode = "create" | "keyframes" | "edit" | "extend";

interface StudioTabProps {
  project: Project;
  assets: Asset[];
  shots: Shot[];
  studioJobs: StudioJob[];
  settings: Settings | null;
  draftInjection: StudioDraftInjection | null;
  onRefreshAssets: () => Promise<void>;
  onRefreshStudioJobs: () => Promise<void>;
  onRefreshShots: () => Promise<void>;
  onStudioJobCreated: (job: StudioJob) => void;
  onOpenSettings: () => void;
  onToast: (text: string, kind?: "info" | "error") => void;
}

const MODE_META: Record<TabMode, { label: string; badge: string; desc: string }> = {
  create: {
    label: "文生 / 参考 R2V",
    badge: "3–15s",
    desc: "纯文字或挂载最多 6 张参考图 + 3 段参考视频，锁定角色、画风与运镜动作",
  },
  keyframes: {
    label: "首尾帧过渡",
    badge: "图生 / 循环",
    desc: "单首帧生视频（3–15s）或首尾双帧平滑过渡/无缝循环（3–10s）",
  },
  edit: {
    label: "视频编辑 V2V",
    badge: "改片 / 换音",
    desc: "对 15s 内视频或已有作品发起自然语言修改，支持参考图注入与重配全套声音",
  },
  extend: {
    label: "视频续写",
    badge: "累计 30s",
    desc: "基于视频结尾无缝延展 3–10s（单轮），支持多轮对话续写与新角色参考图引入",
  },
};

function statusLabel(status: StudioJob["status"]): { text: string; cls: string } {
  switch (status) {
    case "queued":
      return { text: "排队中", cls: "bg-amber-500/15 text-amber-300 border-amber-500/30" };
    case "uploading":
      return { text: "上传素材", cls: "bg-sky-500/15 text-sky-300 border-sky-500/30" };
    case "generating":
      return { text: "Omni 渲染中", cls: "bg-indigo-500/20 text-indigo-300 border-indigo-400/40" };
    case "downloading":
      return { text: "下载封装", cls: "bg-cyan-500/15 text-cyan-300 border-cyan-500/30" };
    case "completed":
      return { text: "已完成", cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30" };
    case "failed":
      return { text: "失败", cls: "bg-rose-500/15 text-rose-300 border-rose-500/30" };
    default:
      return { text: status, cls: "bg-slate-800 text-slate-300 border-studio-border" };
  }
}

export const StudioTab: React.FC<StudioTabProps> = ({
  project,
  assets,
  shots,
  studioJobs,
  settings,
  draftInjection,
  onRefreshAssets,
  onRefreshStudioJobs,
  onRefreshShots,
  onStudioJobCreated,
  onOpenSettings,
  onToast,
}) => {
  const [tabMode, setTabMode] = useState<TabMode>("create");
  const [prompt, setPrompt] = useState("");
  const [aspectRatio, setAspectRatio] = useState<"16:9" | "9:16">(
    project.aspect_ratio === "9:16" ? "9:16" : "16:9"
  );
  const [duration, setDuration] = useState<number>(10);
  const [resolution, setResolution] = useState<VideoResolution>("720p");
  const [stripAudio, setStripAudio] = useState(false);

  const [firstFrameId, setFirstFrameId] = useState<string | null>(null);
  const [lastFrameId, setLastFrameId] = useState<string | null>(null);
  const [loopSameFrame, setLoopSameFrame] = useState(false);
  const [sourceVideoId, setSourceVideoId] = useState<string | null>(null);
  const [refImageIds, setRefImageIds] = useState<string[]>([]);
  const [refVideoIds, setRefVideoIds] = useState<string[]>([]);
  const [parentJob, setParentJob] = useState<StudioJob | null>(null);

  // Prompt enhancer state
  const [singleScene, setSingleScene] = useState(true);
  const [includeTimecodes, setIncludeTimecodes] = useState(false);
  const [audioPref, setAudioPref] = useState("");
  const [enhancing, setEnhancing] = useState(false);
  const [enhancedResult, setEnhancedResult] = useState<EnhancedPromptResult | null>(null);
  const [enhancedPromptDraft, setEnhancedPromptDraft] = useState("");
  const [useEnhancedPrompt, setUseEnhancedPrompt] = useState(true);

  const [submitting, setSubmitting] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [lineage, setLineage] = useState<StudioJob[]>([]);
  const [targetShotId, setTargetShotId] = useState<string>("");
  const [busyAction, setBusyAction] = useState<string | null>(null);

  const imageAssets = useMemo(
    () => assets.filter((a) => (a.media_type || "image") === "image" && Boolean(a.file_url)),
    [assets]
  );
  const videoAssets = useMemo(
    () => assets.filter((a) => (a.media_type === "video" || a.kind === "video") && Boolean(a.file_url)),
    [assets]
  );
  const assetMap = useMemo(() => new Map(assets.map((a) => [a.id, a])), [assets]);

  useEffect(() => {
    setAspectRatio(project.aspect_ratio === "9:16" ? "9:16" : "16:9");
  }, [project.id, project.aspect_ratio]);

  useEffect(() => {
    if (!targetShotId && shots.length > 0) {
      setTargetShotId(shots[0].id);
    }
  }, [shots, targetShotId]);

  useEffect(() => {
    if (!selectedJobId && studioJobs.length > 0) {
      setSelectedJobId(studioJobs[0].id);
    }
  }, [studioJobs, selectedJobId]);

  const activeJob = useMemo(
    () => studioJobs.find((j) => j.id === selectedJobId) || studioJobs[0] || null,
    [studioJobs, selectedJobId]
  );

  useEffect(() => {
    if (!activeJob) {
      setLineage([]);
      return;
    }
    let cancelled = false;
    api
      .getStudioJobLineage(project.id, activeJob.id)
      .then((chain) => {
        if (!cancelled) setLineage(chain);
      })
      .catch(() => {
        if (!cancelled) setLineage([]);
      });
    return () => {
      cancelled = true;
    };
  }, [project.id, activeJob?.id, activeJob?.status]);

  useEffect(() => {
    if (!draftInjection) return;
    if (draftInjection.tabMode) setTabMode(draftInjection.tabMode);
    if (draftInjection.prompt !== undefined) setPrompt(draftInjection.prompt);
    if (draftInjection.enhancedPrompt !== undefined) {
      setEnhancedPromptDraft(draftInjection.enhancedPrompt);
      setUseEnhancedPrompt(Boolean(draftInjection.enhancedPrompt));
    }
    if (draftInjection.firstFrameAssetId !== undefined) {
      setFirstFrameId(draftInjection.firstFrameAssetId);
    }
    if (draftInjection.lastFrameAssetId !== undefined) {
      setLastFrameId(draftInjection.lastFrameAssetId);
    }
    if (draftInjection.sourceVideoAssetId !== undefined) {
      setSourceVideoId(draftInjection.sourceVideoAssetId);
      setParentJob(null);
    }
    if (draftInjection.addRefImageAssetId) {
      setRefImageIds((prev) =>
        prev.includes(draftInjection.addRefImageAssetId!)
          ? prev
          : [...prev, draftInjection.addRefImageAssetId!].slice(0, 6)
      );
    }
  }, [draftInjection]);

  // Enforce Gemini Omni 1.2 duration caps automatically
  const maxDuration = useMemo(() => {
    if (tabMode === "extend") return 10;
    if (tabMode === "keyframes" && firstFrameId && (lastFrameId || loopSameFrame)) return 10;
    return 15;
  }, [tabMode, firstFrameId, lastFrameId, loopSameFrame]);

  useEffect(() => {
    if (duration > maxDuration) setDuration(maxDuration);
  }, [duration, maxDuration]);

  const maxRefVideos = duration > 10 ? 1 : 3;
  useEffect(() => {
    if (refVideoIds.length > maxRefVideos) {
      setRefVideoIds((prev) => prev.slice(0, maxRefVideos));
    }
  }, [maxRefVideos, refVideoIds.length]);

  const uploadAndBind = async (
    file: File,
    target: "first" | "last" | "source" | "refImg" | "refVid"
  ) => {
    try {
      const uploaded = await api.uploadMediaAsset(project.id, file);
      await onRefreshAssets();
      if (target === "first") setFirstFrameId(uploaded.id);
      else if (target === "last") setLastFrameId(uploaded.id);
      else if (target === "source") {
        setSourceVideoId(uploaded.id);
        setParentJob(null);
      } else if (target === "refImg") {
        setRefImageIds((prev) => (prev.includes(uploaded.id) ? prev : [...prev, uploaded.id].slice(0, 6)));
      } else if (target === "refVid") {
        setRefVideoIds((prev) => (prev.includes(uploaded.id) ? prev : [...prev, uploaded.id].slice(0, maxRefVideos)));
      }
      onToast(`已上传「${uploaded.name}」并自动挂载`);
    } catch (e) {
      onToast(e instanceof Error ? e.message : "上传素材失败", "error");
    }
  };

  const resolveSubmissionMode = () => {
    if (tabMode === "edit") return "edit";
    if (tabMode === "extend") return "extend";
    if (tabMode === "keyframes") {
      return firstFrameId && (lastFrameId || loopSameFrame) ? "first_last_frame" : "first_frame";
    }
    if (refImageIds.length > 0 || refVideoIds.length > 0) return "reference_to_video";
    return "text_to_video";
  };

  const handleEnhance = async () => {
    if (!prompt.trim()) {
      onToast("请先输入基础画面描述", "error");
      return;
    }
    setEnhancing(true);
    try {
      const res = await api.enhancePrompt(project.id, {
        prompt: prompt.trim(),
        mode: resolveSubmissionMode(),
        duration_seconds: duration,
        aspect_ratio: aspectRatio,
        single_scene: singleScene,
        include_timecodes: includeTimecodes,
        audio_preference: audioPref.trim() || undefined,
        style_hint: project.style_prompt || undefined,
        has_first_frame: tabMode === "keyframes" && Boolean(firstFrameId),
        has_last_frame: tabMode === "keyframes" && Boolean(lastFrameId || loopSameFrame),
        ref_image_count: refImageIds.length,
        ref_video_count: tabMode === "create" ? refVideoIds.length : 0,
      });
      setEnhancedResult(res);
      setEnhancedPromptDraft(res.enhanced_prompt_en);
      setUseEnhancedPrompt(true);
      onToast("Gemini 4 已完成 Omni 专属提示词扩写！");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "提示词优化失败", "error");
    } finally {
      setEnhancing(false);
    }
  };

  const handleSubmit = async () => {
    if (!prompt.trim()) {
      onToast("请输入视频生成提示词", "error");
      return;
    }
    if (tabMode === "keyframes" && !firstFrameId) {
      onToast("首尾帧模式请先选择或上传首帧图片", "error");
      return;
    }
    if ((tabMode === "edit" || tabMode === "extend") && !sourceVideoId && !parentJob) {
      onToast("编辑或续写模式请选择一个源视频素材，或基于已有作品发起多轮迭代", "error");
      return;
    }

    const mode = resolveSubmissionMode();
    const est = estimateVideoUsd("omni_flash", duration, resolution);
    if (settings?.effective_mode === "live") {
      const ok = confirm(
        `确认提交 Omni 1.2 Flash 创作任务 (${duration}s · ${resolution.toUpperCase()} · ${aspectRatio})？\n预估消耗约 $${est} USD。`
      );
      if (!ok) return;
    }

    setSubmitting(true);
    try {
      const job = await api.createStudioJob(project.id, {
        mode,
        prompt: prompt.trim(),
        enhanced_prompt: useEnhancedPrompt && enhancedPromptDraft.trim() ? enhancedPromptDraft.trim() : undefined,
        aspect_ratio: aspectRatio,
        duration_seconds: duration,
        resolution,
        strip_audio: tabMode === "edit" ? stripAudio : false,
        first_frame_asset_id: tabMode === "keyframes" ? firstFrameId : null,
        last_frame_asset_id:
          tabMode === "keyframes" ? (loopSameFrame ? firstFrameId : lastFrameId) : null,
        source_video_asset_id:
          (tabMode === "edit" || tabMode === "extend") && !parentJob ? sourceVideoId : null,
        ref_image_asset_ids: refImageIds,
        ref_video_asset_ids: tabMode === "create" ? refVideoIds : [],
        parent_job_id: (tabMode === "edit" || tabMode === "extend") && parentJob ? parentJob.id : null,
        previous_interaction_id:
          (tabMode === "edit" || tabMode === "extend") && parentJob ? parentJob.interaction_id : null,
      });
      onStudioJobCreated(job);
      setSelectedJobId(job.id);
      onToast("已提交 Omni 1.2 Flash 生成任务");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "提交失败", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleStartFollowUp = (job: StudioJob, nextMode: "edit" | "extend") => {
    setTabMode(nextMode);
    setParentJob(job);
    setSourceVideoId(null);
    setEnhancedResult(null);
    setEnhancedPromptDraft("");
    setPrompt(
      nextMode === "edit"
        ? "Change lighting to dramatic golden hour, keep everything else the same."
        : "Extend this video seamlessly as the camera keeps moving forward."
    );
    onToast(`已基于作品 #${job.id.slice(0, 6)} 开启多轮${nextMode === "edit" ? "改片" : "续写"}`);
  };

  const runJobAction = async (key: string, fn: () => Promise<void>) => {
    setBusyAction(key);
    try {
      await fn();
    } catch (e) {
      onToast(e instanceof Error ? e.message : "操作失败", "error");
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-5 p-5 xl:grid-cols-12">
      {/* LEFT: Omni 1.2 Controls */}
      <div className="space-y-4 xl:col-span-5">
        {/* Mode Switcher */}
        <div className="grid grid-cols-2 gap-2 rounded-xl border border-studio-border bg-studio-card p-2">
          {(Object.keys(MODE_META) as TabMode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setTabMode(m)}
              className={`rounded-lg border px-3 py-2 text-left transition ${
                tabMode === m
                  ? "border-indigo-500/60 bg-indigo-600/20 text-white"
                  : "border-transparent bg-studio-bg text-slate-400 hover:text-slate-200"
              }`}
            >
              <div className="flex items-center justify-between text-xs font-semibold">
                <span>{MODE_META[m].label}</span>
                <span className="rounded bg-black/30 px-1.5 py-0.5 text-[10px] text-indigo-300">
                  {MODE_META[m].badge}
                </span>
              </div>
            </button>
          ))}
        </div>
        <p className="px-1 text-[11px] text-slate-400">{MODE_META[tabMode].desc}</p>

        {/* Active parent job banner for multi-turn edit/extend */}
        {(tabMode === "edit" || tabMode === "extend") && parentJob && (
          <div className="flex items-center justify-between rounded-xl border border-indigo-500/40 bg-indigo-500/10 p-3 text-xs">
            <div>
              <div className="font-semibold text-indigo-200">
                多轮状态迭代中 · 基于 #{parentJob.id.slice(0, 6)}
              </div>
              <div className="text-[11px] text-slate-400">
                Interaction ID: <span className="font-mono">{parentJob.interaction_id || "local"}</span>
              </div>
            </div>
            <button className="studio-btn-ghost text-xs" onClick={() => setParentJob(null)}>
              <X className="h-3.5 w-3.5" /> 解除绑定
            </button>
          </div>
        )}

        {/* Prompt & Gemini 4 Enhancer */}
        <div className="space-y-3 rounded-xl border border-studio-border bg-studio-card p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-200">视频创意 / 修改指令</span>
            <button
              type="button"
              disabled={enhancing}
              onClick={handleEnhance}
              className="studio-btn-secondary py-1 text-[11px]"
            >
              {enhancing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wand2 className="h-3 w-3 text-indigo-400" />}
              Gemini 4 AI 扩写
            </button>
          </div>
          <textarea
            rows={4}
            className="studio-input text-xs"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="支持中文直接输入，点击「AI 扩写」可自动转换为 Omni 1.2 Flash 电影级英文提示词..."
          />

          <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-300">
            <label className="flex cursor-pointer items-center gap-1.5">
              <input type="checkbox" checked={singleScene} onChange={(e) => setSingleScene(e.target.checked)} />
              一镜到底（防切镜）
            </label>
            <label className="flex cursor-pointer items-center gap-1.5">
              <input
                type="checkbox"
                checked={includeTimecodes}
                onChange={(e) => setIncludeTimecodes(e.target.checked)}
              />
              [0-Xs] 时间码分拍
            </label>
            <input
              className="studio-input flex-1 py-1 text-[11px]"
              value={audioPref}
              onChange={(e) => setAudioPref(e.target.value)}
              placeholder="音效偏好（可选，如：细雨声、无对白）"
            />
          </div>

          {enhancedPromptDraft && (
            <div className="space-y-2 rounded-lg border border-indigo-500/30 bg-studio-bg p-3 text-xs">
              <div className="flex items-center justify-between">
                <label className="flex cursor-pointer items-center gap-1.5 font-semibold text-indigo-300">
                  <input
                    type="checkbox"
                    checked={useEnhancedPrompt}
                    onChange={(e) => setUseEnhancedPrompt(e.target.checked)}
                  />
                  使用 Gemini 4 扩写英文提示词生成
                </label>
                {enhancedResult?.summary_zh && (
                  <span className="text-[10px] text-slate-400">{enhancedResult.summary_zh}</span>
                )}
              </div>
              <textarea
                rows={3}
                className="studio-input font-mono text-[11px]"
                value={enhancedPromptDraft}
                onChange={(e) => setEnhancedPromptDraft(e.target.value)}
              />
            </div>
          )}
        </div>

        {/* Media Slots */}
        <div className="space-y-3 rounded-xl border border-studio-border bg-studio-card p-4 text-xs">
          {tabMode === "keyframes" && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label className="block text-[11px] font-medium text-slate-300">首帧图像（必选）</label>
                  <select
                    className="studio-input py-1.5 text-xs"
                    value={firstFrameId || ""}
                    onChange={(e) => setFirstFrameId(e.target.value || null)}
                  >
                    <option value="">-- 选择图像资产 --</option>
                    {imageAssets.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                  <label className="studio-btn-secondary w-full cursor-pointer py-1 text-[11px]">
                    <Upload className="h-3 w-3" /> 上传首帧
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) uploadAndBind(f, "first");
                        e.target.value = "";
                      }}
                    />
                  </label>
                </div>

                <div className="space-y-1.5">
                  <label className="block text-[11px] font-medium text-slate-300">尾帧图像（可选）</label>
                  <select
                    className="studio-input py-1.5 text-xs"
                    disabled={loopSameFrame}
                    value={loopSameFrame ? firstFrameId || "" : lastFrameId || ""}
                    onChange={(e) => setLastFrameId(e.target.value || null)}
                  >
                    <option value="">-- 不指定尾帧 --</option>
                    {imageAssets.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                  <label className="studio-btn-secondary w-full cursor-pointer py-1 text-[11px]">
                    <Upload className="h-3 w-3" /> 上传尾帧
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) {
                          setLoopSameFrame(false);
                          uploadAndBind(f, "last");
                        }
                        e.target.value = "";
                      }}
                    />
                  </label>
                </div>
              </div>
              <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-indigo-300">
                <input
                  type="checkbox"
                  checked={loopSameFrame}
                  onChange={(e) => setLoopSameFrame(e.target.checked)}
                />
                首尾同图无缝循环（Seamless Loop，上限 10s）
              </label>
            </div>
          )}

          {(tabMode === "edit" || tabMode === "extend") && !parentJob && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-medium text-slate-300">源视频素材（≤15s）</label>
                <label className="cursor-pointer text-[11px] text-cyan-300 hover:underline">
                  + 上传 MP4
                  <input
                    type="file"
                    accept="video/*"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) uploadAndBind(f, "source");
                      e.target.value = "";
                    }}
                  />
                </label>
              </div>
              <select
                className="studio-input py-1.5 text-xs"
                value={sourceVideoId || ""}
                onChange={(e) => setSourceVideoId(e.target.value || null)}
              >
                <option value="">-- 选择资产库视频 --</option>
                {videoAssets.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} {a.duration_sec ? `(${formatDuration(a.duration_sec)})` : ""}
                  </option>
                ))}
              </select>
              {tabMode === "edit" && (
                <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-amber-300">
                  <input
                    type="checkbox"
                    checked={stripAudio}
                    onChange={(e) => setStripAudio(e.target.checked)}
                  />
                  <VolumeX className="h-3.5 w-3.5" />
                  自动剥离原音轨，让模型重配全套声音
                </label>
              )}
            </div>
          )}

          {/* Reference Images (max 6 across modes) */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium text-slate-300">
                参考图（{refImageIds.length}/6 · 角色/画风参考）
              </span>
              <label className="cursor-pointer text-[11px] text-indigo-300 hover:underline">
                + 上传参考图
                <input
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) uploadAndBind(f, "refImg");
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
            {imageAssets.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {imageAssets.map((a) => {
                  const active = refImageIds.includes(a.id);
                  return (
                    <button
                      key={a.id}
                      type="button"
                      onClick={() =>
                        setRefImageIds((prev) =>
                          active ? prev.filter((x) => x !== a.id) : [...prev, a.id].slice(0, 6)
                        )
                      }
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
          </div>

          {/* Reference Videos (R2V only, max 3 for <=10s, 1 for 11-15s) */}
          {tabMode === "create" && (
            <div className="space-y-2 border-t border-studio-border/60 pt-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-medium text-slate-300">
                  参考视频 R2V（{refVideoIds.length}/{maxRefVideos} · 运镜/动作风格参考）
                </span>
                <label className="cursor-pointer text-[11px] text-cyan-300 hover:underline">
                  + 上传参考视频
                  <input
                    type="file"
                    accept="video/*"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) uploadAndBind(f, "refVid");
                      e.target.value = "";
                    }}
                  />
                </label>
              </div>
              {videoAssets.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {videoAssets.map((a) => {
                    const active = refVideoIds.includes(a.id);
                    return (
                      <button
                        key={a.id}
                        type="button"
                        onClick={() =>
                          setRefVideoIds((prev) =>
                            active ? prev.filter((x) => x !== a.id) : [...prev, a.id].slice(0, maxRefVideos)
                          )
                        }
                        className={`rounded-full px-2 py-0.5 text-[11px] transition ${
                          active
                            ? "bg-cyan-600 text-white"
                            : "border border-studio-border bg-studio-bg text-slate-400 hover:text-slate-200"
                        }`}
                      >
                        <Video className="mr-1 inline h-3 w-3" />
                        {a.name}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Output Parameters & Submit */}
        <div className="space-y-3 rounded-xl border border-studio-border bg-studio-card p-4 text-xs">
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="mb-1 block text-[11px] text-slate-400">清晰度</label>
              <select
                className="studio-input py-1.5 text-xs"
                value={resolution}
                onChange={(e) => setResolution(e.target.value as VideoResolution)}
              >
                <option value="360p">360p</option>
                <option value="720p">720p</option>
                <option value="1080p">1080p</option>
                <option value="4k">4K</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-slate-400">画幅</label>
              <select
                className="studio-input py-1.5 text-xs"
                value={aspectRatio}
                onChange={(e) => setAspectRatio(e.target.value as "16:9" | "9:16")}
              >
                <option value="16:9">16:9 横屏</option>
                <option value="9:16">9:16 竖屏</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-slate-400">时长: {duration}s (上限 {maxDuration}s)</label>
              <input
                type="range"
                min={3}
                max={maxDuration}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className="mt-2 w-full accent-indigo-500"
              />
            </div>
          </div>

          <button
            type="button"
            disabled={submitting}
            onClick={handleSubmit}
            className="studio-btn-primary w-full py-2.5 text-xs"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            生成 Omni 1.2 Flash 视频 ({duration}s · {resolution.toUpperCase()} · ~${estimateVideoUsd("omni_flash", duration, resolution)})
          </button>
        </div>
      </div>

      {/* RIGHT: Preview Player, Lineage & History */}
      <div className="space-y-4 xl:col-span-7">
        {activeJob ? (
          <div className="space-y-3 rounded-xl border border-studio-border bg-studio-card p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-full border px-2 py-0.5 text-[11px] ${
                    statusLabel(activeJob.status).cls
                  }`}
                >
                  {statusLabel(activeJob.status).text}
                </span>
                <span className="font-mono text-xs text-slate-400">
                  #{activeJob.id.slice(0, 8)} · {activeJob.mode} · {activeJob.duration_seconds}s · {activeJob.resolution}
                </span>
              </div>
              <button
                className="studio-btn-ghost text-rose-400 hover:text-rose-300"
                onClick={() =>
                  runJobAction("del", async () => {
                    await api.deleteStudioJob(project.id, activeJob.id);
                    await onRefreshStudioJobs();
                    setSelectedJobId(null);
                    onToast("已删除创作记录");
                  })
                }
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>

            {activeJob.status === "completed" && activeJob.output_url ? (
              <video
                key={activeJob.id}
                src={activeJob.output_url}
                controls
                className="aspect-video w-full rounded-lg bg-black"
              />
            ) : activeJob.status === "failed" ? (
              <div className="rounded-lg border border-rose-500/30 bg-rose-950/30 p-6 text-xs text-rose-200">
                生成失败：{activeJob.error_message || "未知错误"}
              </div>
            ) : (
              <div className="flex aspect-video flex-col items-center justify-center gap-2 rounded-lg border border-studio-border bg-studio-bg text-xs text-slate-400">
                <Loader2 className="h-7 w-7 animate-spin text-indigo-400" />
                <span>{activeJob.progress_message || "正在渲染..."}</span>
                <div className="h-1.5 w-48 overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full bg-indigo-500 transition-all"
                    style={{ width: `${Math.max(8, activeJob.progress)}%` }}
                  />
                </div>
              </div>
            )}

            <p className="text-xs text-slate-300">{activeJob.enhanced_prompt || activeJob.prompt}</p>

            {activeJob.status === "completed" && activeJob.output_url && (
              <div className="flex flex-wrap items-center gap-2 border-t border-studio-border/60 pt-3">
                <button
                  className="studio-btn-primary text-[11px]"
                  onClick={() => handleStartFollowUp(activeJob, "edit")}
                >
                  <Wand2 className="h-3 w-3" /> 多轮改片
                </button>
                <button
                  className="studio-btn-secondary text-[11px]"
                  onClick={() => handleStartFollowUp(activeJob, "extend")}
                >
                  <Repeat className="h-3 w-3 text-cyan-400" /> 继续续写
                </button>
                <button
                  className="studio-btn-secondary text-[11px]"
                  disabled={busyAction !== null}
                  onClick={() =>
                    runJobAction("first", async () => {
                      await api.extractStudioJobFrame(project.id, activeJob.id, "first");
                      await onRefreshAssets();
                      onToast("已提取首帧存入资产库");
                    })
                  }
                >
                  <Camera className="h-3 w-3" /> 抽首帧入库
                </button>
                <button
                  className="studio-btn-secondary text-[11px]"
                  disabled={busyAction !== null}
                  onClick={() =>
                    runJobAction("last", async () => {
                      await api.extractStudioJobFrame(project.id, activeJob.id, "last");
                      await onRefreshAssets();
                      onToast("已提取尾帧存入资产库");
                    })
                  }
                >
                  <Camera className="h-3 w-3" /> 抽尾帧入库
                </button>
                <button
                  className="studio-btn-secondary text-[11px]"
                  disabled={busyAction !== null}
                  onClick={() =>
                    runJobAction("saveAsset", async () => {
                      await api.saveStudioJobAsAsset(project.id, activeJob.id);
                      await onRefreshAssets();
                      onToast("已保存为项目视频资产");
                    })
                  }
                >
                  <Save className="h-3 w-3 text-emerald-400" /> 存为视频素材
                </button>

                {shots.length > 0 && (
                  <div className="flex items-center gap-1 rounded-lg border border-studio-border bg-studio-bg px-2 py-1">
                    <select
                      className="bg-transparent text-[11px] text-slate-200 focus:outline-none"
                      value={targetShotId}
                      onChange={(e) => setTargetShotId(e.target.value)}
                    >
                      {shots.map((s, i) => (
                        <option key={s.id} value={s.id} className="bg-studio-panel">
                          #{i + 1} {s.title}
                        </option>
                      ))}
                    </select>
                    <button
                      className="text-[11px] font-medium text-indigo-300 hover:text-indigo-200"
                      disabled={busyAction !== null || !targetShotId}
                      onClick={() =>
                        runJobAction("toShot", async () => {
                          await api.sendStudioJobToShot(project.id, activeJob.id, targetShotId);
                          await onRefreshShots();
                          onToast("已导入到目标分镜并设为锁定 Take！");
                        })
                      }
                    >
                      <Send className="mr-1 inline h-3 w-3" />
                      导入分镜
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Lineage chain */}
            {lineage.length > 1 && (
              <div className="space-y-1.5 border-t border-studio-border/60 pt-3">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-300">
                  <GitBranch className="h-3.5 w-3.5 text-indigo-400" />
                  版本迭代谱系树（{lineage.length} 轮）
                </div>
                <div className="flex flex-wrap gap-2">
                  {lineage.map((node, idx) => (
                    <button
                      key={node.id}
                      onClick={() => setSelectedJobId(node.id)}
                      className={`rounded-lg border px-2.5 py-1 text-[11px] transition ${
                        node.id === activeJob.id
                          ? "border-indigo-500 bg-indigo-600/20 text-white"
                          : "border-studio-border bg-studio-bg text-slate-400 hover:text-white"
                      }`}
                    >
                      v{idx + 1} · {node.mode} ({node.duration_seconds}s)
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="flex h-64 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-studio-border text-xs text-slate-500">
            <Film className="h-8 w-8" />
            <span>在左侧输入提示词并生成，即可在此实时预览、多轮改片、抽帧或一键导入分镜板</span>
          </div>
        )}

        {/* History List */}
        {studioJobs.length > 0 && (
          <div className="space-y-2 rounded-xl border border-studio-border bg-studio-card p-4">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
              <Clock className="h-3.5 w-3.5 text-slate-400" />
              自由创作历史（{studioJobs.length}）
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {studioJobs.map((j) => {
                const st = statusLabel(j.status);
                const isSel = activeJob?.id === j.id;
                return (
                  <button
                    key={j.id}
                    onClick={() => setSelectedJobId(j.id)}
                    className={`flex items-center gap-3 rounded-lg border p-2 text-left transition ${
                      isSel
                        ? "border-indigo-500/60 bg-indigo-600/15"
                        : "border-studio-border bg-studio-bg hover:border-slate-600"
                    }`}
                  >
                    <div className="h-12 w-20 shrink-0 overflow-hidden rounded bg-black">
                      {j.output_thumb_url ? (
                        <img src={j.output_thumb_url} alt={j.id} className="h-full w-full object-cover" />
                      ) : (
                        <div className="flex h-full items-center justify-center text-slate-600">
                          <Film className="h-4 w-4" />
                        </div>
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-1">
                        <span className={`rounded border px-1.5 py-0.5 text-[10px] ${st.cls}`}>{st.text}</span>
                        <span className="font-mono text-[10px] text-slate-400">
                          {j.duration_seconds}s · {j.resolution}
                        </span>
                      </div>
                      <p className="mt-1 truncate text-[11px] text-slate-200">{j.prompt}</p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
