import React, { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Camera,
  CheckSquare,
  Film,
  Image as ImageIcon,
  Layers,
  Loader2,
  Plus,
  RefreshCw,
  Scissors,
  Send,
  Sparkles,
  Square,
  Trash2,
  Upload,
  VolumeX,
} from "lucide-react";
import { formatBytes, formatDuration } from "../api";
import type { Asset, JobTask, Project, Settings, StudioDraftInjection } from "../types";

interface AssetHubProps {
  project: Project;
  assets: Asset[];
  settings?: Settings | null;
  tasks?: JobTask[];
  onUpdateProject: (patch: Partial<Project>) => Promise<void>;
  onCreateAsset: (payload: { name: string; kind: string; description: string }) => Promise<void>;
  onUploadMediaFiles: (files: FileList) => Promise<void>;
  onUpdateAsset: (id: string, patch: Partial<Asset>) => Promise<void>;
  onDeleteAsset: (id: string) => Promise<void>;
  onUploadAsset: (id: string, file: File) => Promise<void>;
  onPrepAsset: (
    id: string,
    payload: { start_seconds?: number; duration?: number; strip_audio?: boolean; max_edge?: number }
  ) => Promise<void>;
  onExtractFrame: (id: string, position: "first" | "last") => Promise<void>;
  onGenerateImage: (id: string) => Promise<void>;
  onGenerateTurnaround: (id: string) => Promise<void>;
  onBatchGenerateAssets: (payload: {
    asset_ids: string[];
    target: "portrait" | "turnaround" | "both";
    regenerate: boolean;
  }) => Promise<void>;
  onSendToStudio: (draft: Omit<StudioDraftInjection, "nonce">) => void;
}

const KIND_LABELS: Record<string, string> = {
  character: "角色",
  scene: "场景",
  prop: "道具",
  audio: "音频",
  video: "视频素材",
};

export const AssetHub: React.FC<AssetHubProps> = ({
  project,
  assets,
  settings,
  tasks = [],
  onUpdateProject,
  onCreateAsset,
  onUploadMediaFiles,
  onUpdateAsset,
  onDeleteAsset,
  onUploadAsset,
  onPrepAsset,
  onExtractFrame,
  onGenerateImage,
  onGenerateTurnaround,
  onBatchGenerateAssets,
  onSendToStudio,
}) => {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"character" | "scene" | "prop">("character");
  const [desc, setDesc] = useState("");
  const [styleDraft, setStyleDraft] = useState(project.style_prompt);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchSubmitting, setBatchSubmitting] = useState(false);

  useEffect(() => {
    setStyleDraft(project.style_prompt);
  }, [project.id, project.style_prompt]);

  const imageAssets = useMemo(
    () => assets.filter((a) => a.media_type !== "video" && a.kind !== "video"),
    [assets]
  );

  // Prune deleted asset IDs automatically
  useEffect(() => {
    const valid = new Set(imageAssets.map((a) => a.id));
    setSelectedIds((prev) => {
      const next = new Set(Array.from(prev).filter((id) => valid.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [imageAssets]);

  const missingPortraitIds = useMemo(
    () => imageAssets.filter((a) => !a.file_url).map((a) => a.id),
    [imageAssets]
  );
  const missingTurnaroundIds = useMemo(
    () => imageAssets.filter((a) => !a.turnaround_url).map((a) => a.id),
    [imageAssets]
  );

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const runBatch = async (target: "portrait" | "turnaround" | "both", regenerate: boolean) => {
    if (selectedIds.size === 0) return;
    setBatchSubmitting(true);
    try {
      await onBatchGenerateAssets({
        asset_ids: Array.from(selectedIds),
        target,
        regenerate,
      });
    } finally {
      setBatchSubmitting(false);
    }
  };

  const useGptForAssets =
    settings?.image_provider === "openai_assets" || settings?.image_provider === "openai_all";
  const engineBadge = useGptForAssets
    ? `GPT (${settings?.openai_image_model || "gpt-image-1"}) · 并发上限 ${settings?.openai_max_concurrent || 2}`
    : `Gemini (${settings?.image_model || "gemini-nano-banana-2.1"})`;

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    await onCreateAsset({ name: name.trim(), kind, description: desc.trim() });
    setName("");
    setDesc("");
  };

  return (
    <div className="space-y-5 p-5">
      {/* Global project visual style */}
      <div className="rounded-xl border border-studio-border bg-studio-card p-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-200">全片视觉基调（自动注入所有关键帧与资产生成）</span>
          <span className="rounded bg-studio-bg px-2 py-0.5 font-mono text-[11px] text-indigo-300">
            画幅 {project.aspect_ratio}
          </span>
        </div>
        <div className="flex gap-2">
          <input
            className="studio-input text-xs"
            value={styleDraft}
            onChange={(e) => setStyleDraft(e.target.value)}
            placeholder="例如：35mm 胶片质感、青橙色调、自然体积光..."
          />
          <button
            className="studio-btn-secondary shrink-0"
            onClick={() => onUpdateProject({ style_prompt: styleDraft })}
          >
            保存风格
          </button>
        </div>
      </div>

      {/* Add new asset + Batch Media Upload */}
      <form onSubmit={handleAdd} className="rounded-xl border border-studio-border bg-studio-card p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-semibold text-slate-200">
            新增一致性资产（角色 / 场景 / 道具）或批量上传图片/视频素材
          </span>
          <label className="studio-btn-secondary cursor-pointer text-xs">
            <Upload className="h-3.5 w-3.5 text-cyan-400" />
            批量上传图片 / 视频 (MP4/MOV/PNG/JPG)
            <input
              type="file"
              multiple
              accept="image/*,video/*"
              className="hidden"
              onChange={(e) => {
                if (e.target.files && e.target.files.length > 0) {
                  onUploadMediaFiles(e.target.files);
                }
                e.target.value = "";
              }}
            />
          </label>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-12">
          <input
            className="studio-input md:col-span-3"
            placeholder="资产名称（如：主角林澈）"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <select
            className="studio-input md:col-span-2"
            value={kind}
            onChange={(e) => setKind(e.target.value as "character" | "scene" | "prop")}
          >
            <option value="character">角色</option>
            <option value="scene">场景</option>
            <option value="prop">道具</option>
          </select>
          <input
            className="studio-input md:col-span-5"
            placeholder="特征档案 Character Bible（发型、服装、材质、时代感，越具体跨镜头越稳）"
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
          />
          <button type="submit" className="studio-btn-primary md:col-span-2">
            <Plus className="h-3.5 w-3.5" />
            添加资产
          </button>
        </div>
      </form>

      {/* Multi-Select Batch Action Bar */}
      {imageAssets.length > 0 && (
        <div className="flex flex-col gap-3 rounded-xl border border-indigo-500/30 bg-indigo-950/20 p-3.5">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-indigo-200">
                批量多选生图（已选 {selectedIds.size} / {imageAssets.length}）
              </span>
              <button
                type="button"
                className="studio-btn-secondary py-1 text-[11px]"
                onClick={() => setSelectedIds(new Set(imageAssets.map((a) => a.id)))}
              >
                全选 ({imageAssets.length})
              </button>
              <button
                type="button"
                className="studio-btn-secondary py-1 text-[11px]"
                onClick={() => setSelectedIds(new Set(missingPortraitIds))}
              >
                选未定妆 ({missingPortraitIds.length})
              </button>
              <button
                type="button"
                className="studio-btn-secondary py-1 text-[11px]"
                onClick={() => setSelectedIds(new Set(missingTurnaroundIds))}
              >
                选缺三视图 ({missingTurnaroundIds.length})
              </button>
              {selectedIds.size > 0 && (
                <button
                  type="button"
                  className="studio-btn-ghost py-1 text-[11px] text-slate-400"
                  onClick={() => setSelectedIds(new Set())}
                >
                  清空
                </button>
              )}
            </div>

            <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 font-mono text-[11px] text-emerald-300">
              当前引擎：{engineBadge}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={selectedIds.size === 0 || batchSubmitting}
              className="studio-btn-primary py-1.5 text-xs"
              onClick={() => runBatch("portrait", false)}
              title="仅对选中的未生成资产执行定妆"
            >
              <Sparkles className="h-3.5 w-3.5" />
              一键生成定妆照
            </button>
            <button
              type="button"
              disabled={selectedIds.size === 0 || batchSubmitting}
              className="studio-btn-secondary py-1.5 text-xs"
              onClick={() => runBatch("portrait", true)}
              title="强制重新生成选中资产的定妆照并覆盖旧图"
            >
              <RefreshCw className="h-3.5 w-3.5 text-amber-400" />
              重新生成定妆照
            </button>
            <button
              type="button"
              disabled={selectedIds.size === 0 || batchSubmitting}
              className="studio-btn-primary py-1.5 text-xs"
              onClick={() => runBatch("turnaround", false)}
              title="仅对选中的缺失三视图资产生成正/侧/背三视图"
            >
              <Layers className="h-3.5 w-3.5" />
              一键生成三视图
            </button>
            <button
              type="button"
              disabled={selectedIds.size === 0 || batchSubmitting}
              className="studio-btn-secondary py-1.5 text-xs"
              onClick={() => runBatch("turnaround", true)}
              title="强制重新生成选中资产的三视图"
            >
              <RefreshCw className="h-3.5 w-3.5 text-amber-400" />
              重新生成三视图
            </button>
            <button
              type="button"
              disabled={selectedIds.size === 0 || batchSubmitting}
              className="studio-btn-secondary border-indigo-500/40 py-1.5 text-xs text-indigo-200"
              onClick={() => runBatch("both", false)}
              title="先生成缺失定妆照，再以定妆照为参考生成三视图"
            >
              <Sparkles className="h-3.5 w-3.5 text-indigo-400" />
              定妆 + 三视图连出
            </button>
          </div>
        </div>
      )}

      {/* Asset Grid */}
      {assets.length === 0 ? (
        <div className="rounded-xl border border-dashed border-studio-border p-10 text-center text-sm text-slate-500">
          暂无项目资产。你可以在上方手动添加/批量上传，或者在左侧让导演 Agent 根据创意自动拆解角色与场景！
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {assets.map((asset) => {
            const isVideo = asset.media_type === "video" || asset.kind === "video";
            const isSelected = selectedIds.has(asset.id);
            const latestAssetTask = tasks.find((t) => t.asset_id === asset.id) || null;
            const isRunning =
              latestAssetTask &&
              (latestAssetTask.status === "queued" || latestAssetTask.status === "running");

            return (
              <div
                key={asset.id}
                className={`flex flex-col justify-between rounded-xl border bg-studio-card p-4 transition ${
                  isSelected
                    ? "border-indigo-500 ring-1 ring-indigo-500/40"
                    : "border-studio-border"
                }`}
              >
                <div>
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      {!isVideo && (
                        <button
                          type="button"
                          onClick={() => toggleSelect(asset.id)}
                          className="text-slate-400 hover:text-indigo-300"
                          title={isSelected ? "取消选中" : "选中加入批量操作"}
                        >
                          {isSelected ? (
                            <CheckSquare className="h-4 w-4 text-indigo-400" />
                          ) : (
                            <Square className="h-4 w-4" />
                          )}
                        </button>
                      )}
                      <span
                        className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                          isVideo ? "bg-cyan-500/20 text-cyan-300" : "bg-indigo-500/20 text-indigo-300"
                        }`}
                      >
                        {KIND_LABELS[asset.kind] || asset.kind}
                      </span>
                      <h3 className="text-sm font-semibold text-white">@{asset.name}</h3>
                      {(asset.width || asset.duration_sec) && (
                        <span className="font-mono text-[10px] text-slate-400">
                          {asset.width && asset.height ? `${asset.width}x${asset.height}` : ""}
                          {asset.duration_sec ? ` · ${formatDuration(asset.duration_sec)}` : ""}
                          {asset.fps ? ` · ${asset.fps}` : ""}
                          {isVideo ? (asset.has_audio ? " · 含音轨" : " · 无音轨") : ""}
                          {asset.size_bytes ? ` · ${formatBytes(asset.size_bytes)}` : ""}
                        </span>
                      )}
                    </div>
                    <button
                      className="studio-btn-ghost text-rose-400 hover:text-rose-300"
                      onClick={() => onDeleteAsset(asset.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>

                  {/* Per-asset live queue/progress/error status */}
                  {isRunning && latestAssetTask && (
                    <div className="mb-3 rounded-lg border border-indigo-500/30 bg-indigo-950/30 px-3 py-2 text-xs text-indigo-200">
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-1.5">
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-400" />
                          <span>{latestAssetTask.message}</span>
                        </span>
                        <span className="font-mono text-[11px]">{latestAssetTask.progress}%</span>
                      </div>
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800">
                        <div
                          className="h-full bg-indigo-500 transition-all duration-300"
                          style={{ width: `${Math.max(5, latestAssetTask.progress)}%` }}
                        />
                      </div>
                    </div>
                  )}
                  {latestAssetTask && latestAssetTask.status === "failed" && (
                    <div className="mb-3 flex items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-950/40 px-3 py-2 text-xs text-rose-200">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-400" />
                      <div className="min-w-0 flex-1 break-all">
                        <span className="font-medium">上次生图失败：</span>
                        <span>{latestAssetTask.error || latestAssetTask.message}</span>
                      </div>
                    </div>
                  )}

                  {/* Previews */}
                  {isVideo ? (
                    <div className="relative mb-3 aspect-video overflow-hidden rounded-lg border border-studio-border bg-black">
                      {asset.file_url ? (
                        <video src={asset.file_url} controls className="h-full w-full" />
                      ) : (
                        <div className="flex h-full flex-col items-center justify-center gap-1 text-xs text-slate-600">
                          <Film className="h-6 w-6" />
                          <span>待上传视频</span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="mb-3 grid grid-cols-2 gap-2">
                      <div className="relative aspect-video overflow-hidden rounded-lg border border-studio-border bg-studio-bg">
                        {asset.file_url ? (
                          <img src={asset.file_url} alt={asset.name} className="h-full w-full object-cover" />
                        ) : (
                          <div className="flex h-full flex-col items-center justify-center gap-1 text-xs text-slate-600">
                            <ImageIcon className="h-6 w-6" />
                            <span>待定妆</span>
                          </div>
                        )}
                        <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-slate-300">
                          主参考图
                        </span>
                      </div>

                      <div className="relative aspect-video overflow-hidden rounded-lg border border-studio-border bg-studio-bg">
                        {asset.turnaround_url ? (
                          <img
                            src={asset.turnaround_url}
                            alt={`${asset.name} turnaround`}
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <div className="flex h-full flex-col items-center justify-center gap-1 text-xs text-slate-600">
                            <Layers className="h-6 w-6" />
                            <span>三视图（可选）</span>
                          </div>
                        )}
                        <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-slate-300">
                          三视图 Skill
                        </span>
                      </div>
                    </div>
                  )}

                  <textarea
                    rows={2}
                    className="studio-input mb-3 text-xs"
                    defaultValue={asset.description}
                    onBlur={(e) => {
                      if (e.target.value !== asset.description) {
                        onUpdateAsset(asset.id, { description: e.target.value });
                      }
                    }}
                  />
                </div>

                {/* Actions */}
                <div className="flex flex-wrap items-center gap-2">
                  {!isVideo && (
                    <>
                      <button className="studio-btn-primary" onClick={() => onGenerateImage(asset.id)}>
                        {asset.file_url ? (
                          <RefreshCw className="h-3.5 w-3.5" />
                        ) : (
                          <Sparkles className="h-3.5 w-3.5" />
                        )}
                        {asset.file_url ? "重新生成定妆" : "生成定妆照"}
                      </button>
                      <button className="studio-btn-secondary" onClick={() => onGenerateTurnaround(asset.id)}>
                        {asset.turnaround_url ? (
                          <RefreshCw className="h-3.5 w-3.5" />
                        ) : (
                          <Layers className="h-3.5 w-3.5" />
                        )}
                        {asset.turnaround_url ? "重新生成三视图" : "生成三视图"}
                      </button>
                      {asset.file_url && (
                        <>
                          <button
                            className="studio-btn-secondary text-[11px]"
                            onClick={() => onSendToStudio({ tabMode: "keyframes", firstFrameAssetId: asset.id })}
                            title="发送该图至全模态自由创作台作为首帧"
                          >
                            <Send className="h-3 w-3 text-indigo-400" />
                            作首帧
                          </button>
                          <button
                            className="studio-btn-secondary text-[11px]"
                            onClick={() => onSendToStudio({ tabMode: "create", addRefImageAssetId: asset.id })}
                            title="加入全模态自由创作台 R2V 参考图"
                          >
                            <Plus className="h-3 w-3 text-cyan-400" />
                            作参考图
                          </button>
                        </>
                      )}
                    </>
                  )}

                  {isVideo && asset.file_url && (
                    <>
                      <button
                        className="studio-btn-secondary text-[11px]"
                        onClick={() => onPrepAsset(asset.id, { start_seconds: 0, duration: 3, max_edge: 1280 })}
                        title="FFmpeg 裁剪 3 秒参考片段（适合 R2V 视频参考）"
                      >
                        <Scissors className="h-3 w-3 text-cyan-400" />
                        3s R2V 裁剪
                      </button>
                      <button
                        className="studio-btn-secondary text-[11px]"
                        onClick={() => onPrepAsset(asset.id, { start_seconds: 0, duration: 10, max_edge: 1280 })}
                        title="FFmpeg 优化为 10s 720p（适合 V2V 编辑/续写）"
                      >
                        <Scissors className="h-3 w-3 text-indigo-400" />
                        10s 编辑优化
                      </button>
                      <button
                        className="studio-btn-secondary text-[11px]"
                        onClick={() =>
                          onPrepAsset(asset.id, { start_seconds: 0, duration: 10, strip_audio: true, max_edge: 1280 })
                        }
                        title="裁剪 10s 并剥离原音轨，让 Omni 重配全套声音"
                      >
                        <VolumeX className="h-3 w-3 text-amber-400" />
                        10s 剥音裁剪
                      </button>
                      <button
                        className="studio-btn-secondary text-[11px]"
                        onClick={() => onExtractFrame(asset.id, "first")}
                      >
                        <Camera className="h-3 w-3" />
                        抽首帧
                      </button>
                      <button
                        className="studio-btn-secondary text-[11px]"
                        onClick={() => onExtractFrame(asset.id, "last")}
                      >
                        <Camera className="h-3 w-3" />
                        抽尾帧
                      </button>
                      <button
                        className="studio-btn-primary text-[11px]"
                        onClick={() => onSendToStudio({ tabMode: "edit", sourceVideoAssetId: asset.id })}
                      >
                        <Send className="h-3 w-3" />
                        去 V2V 改片
                      </button>
                    </>
                  )}

                  <label className="studio-btn-secondary cursor-pointer text-[11px]">
                    <Upload className="h-3.5 w-3.5" />
                    替换文件
                    <input
                      type="file"
                      accept={isVideo ? "video/*" : "image/*"}
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) onUploadAsset(asset.id, f);
                        e.target.value = "";
                      }}
                    />
                  </label>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
