import React, { useState } from "react";
import { Image as ImageIcon, Layers, Plus, Sparkles, Trash2, Upload } from "lucide-react";
import type { Asset, Project } from "../types";

interface AssetHubProps {
  project: Project;
  assets: Asset[];
  onUpdateProject: (patch: Partial<Project>) => Promise<void>;
  onCreateAsset: (payload: { name: string; kind: string; description: string }) => Promise<void>;
  onUpdateAsset: (id: string, patch: Partial<Asset>) => Promise<void>;
  onDeleteAsset: (id: string) => Promise<void>;
  onUploadAsset: (id: string, file: File) => Promise<void>;
  onGenerateImage: (id: string) => Promise<void>;
  onGenerateTurnaround: (id: string) => Promise<void>;
}

const KIND_LABELS: Record<string, string> = {
  character: "角色",
  scene: "场景",
  prop: "道具",
  audio: "音频",
};

export const AssetHub: React.FC<AssetHubProps> = ({
  project,
  assets,
  onUpdateProject,
  onCreateAsset,
  onUpdateAsset,
  onDeleteAsset,
  onUploadAsset,
  onGenerateImage,
  onGenerateTurnaround,
}) => {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"character" | "scene" | "prop">("character");
  const [desc, setDesc] = useState("");
  const [styleDraft, setStyleDraft] = useState(project.style_prompt);

  React.useEffect(() => {
    setStyleDraft(project.style_prompt);
  }, [project.id, project.style_prompt]);

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

      {/* Add new asset */}
      <form onSubmit={handleAdd} className="rounded-xl border border-studio-border bg-studio-card p-4">
        <div className="mb-3 text-xs font-semibold text-slate-200">新增一致性资产（角色 / 场景 / 道具）</div>
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

      {/* Asset Grid */}
      {assets.length === 0 ? (
        <div className="rounded-xl border border-dashed border-studio-border p-10 text-center text-sm text-slate-500">
          暂无项目资产。你可以在上方手动添加，或者在左侧让导演 Agent 根据创意自动拆解角色与场景！
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {assets.map((asset) => (
            <div
              key={asset.id}
              className="flex flex-col justify-between rounded-xl border border-studio-border bg-studio-card p-4"
            >
              <div>
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-indigo-500/20 px-2 py-0.5 text-[11px] font-medium text-indigo-300">
                      {KIND_LABELS[asset.kind] || asset.kind}
                    </span>
                    <h3 className="text-sm font-semibold text-white">@{asset.name}</h3>
                  </div>
                  <button
                    className="studio-btn-ghost text-rose-400 hover:text-rose-300"
                    onClick={() => onDeleteAsset(asset.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>

                {/* Image previews */}
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

              <div className="flex flex-wrap items-center gap-2">
                <button className="studio-btn-primary" onClick={() => onGenerateImage(asset.id)}>
                  <Sparkles className="h-3.5 w-3.5" />
                  Nano Banana 定妆 (~$0.06)
                </button>
                {asset.kind === "character" && (
                  <button className="studio-btn-secondary" onClick={() => onGenerateTurnaround(asset.id)}>
                    <Layers className="h-3.5 w-3.5" />
                    生成三视图 (~$0.07)
                  </button>
                )}
                <label className="studio-btn-secondary cursor-pointer">
                  <Upload className="h-3.5 w-3.5" />
                  上传参考图
                  <input
                    type="file"
                    accept="image/*"
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
          ))}
        </div>
      )}
    </div>
  );
};
