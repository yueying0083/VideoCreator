import React, { useState } from "react";
import { Clapperboard, FolderPlus, Loader2, Settings as SettingsIcon, Sparkles, Trash2 } from "lucide-react";
import type { BudgetSummary, JobTask, Project, Settings } from "../types";

interface TopBarProps {
  projects: Project[];
  currentProject: Project | null;
  settings: Settings | null;
  budget: BudgetSummary | null;
  activeJobs: JobTask[];
  onSelectProject: (id: string) => void;
  onCreateProject: (name: string, aspectRatio: "16:9" | "9:16" | "1:1") => Promise<void>;
  onDeleteProject: (id: string) => Promise<void>;
  onOpenSettings: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  projects,
  currentProject,
  settings,
  budget,
  activeJobs,
  onSelectProject,
  onCreateProject,
  onDeleteProject,
  onOpenSettings,
}) => {
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newRatio, setNewRatio] = useState<"16:9" | "9:16" | "1:1">("16:9");

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    await onCreateProject(newName.trim(), newRatio);
    setNewName("");
    setCreating(false);
  };

  const pct = budget?.percent_used ?? 0;
  const barColor = pct >= 90 ? "bg-rose-500" : pct >= 70 ? "bg-amber-500" : "bg-emerald-500";

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-studio-border bg-studio-panel px-4">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 font-semibold text-white">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600/20 text-indigo-400 ring-1 ring-indigo-500/40">
            <Clapperboard className="h-4 w-4" />
          </div>
          <span className="tracking-tight">Video Creator Studio</span>
        </div>

        <div className="h-5 w-px bg-studio-border" />

        {!creating ? (
          <div className="flex items-center gap-2">
            <select
              className="rounded-lg border border-studio-border bg-studio-bg px-3 py-1.5 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
              value={currentProject?.id || ""}
              onChange={(e) => onSelectProject(e.target.value)}
            >
              {projects.length === 0 && <option value="">暂无项目</option>}
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.aspect_ratio})
                </option>
              ))}
            </select>
            <button
              className="studio-btn-secondary"
              onClick={() => setCreating(true)}
              title="新建视频项目"
            >
              <FolderPlus className="h-3.5 w-3.5" />
              新建项目
            </button>
            {currentProject && projects.length > 1 && (
              <button
                className="studio-btn-ghost text-rose-400 hover:text-rose-300"
                onClick={() => {
                  if (confirm(`确定删除项目「${currentProject.name}」及其所有本地素材？`)) {
                    onDeleteProject(currentProject.id);
                  }
                }}
                title="删除当前项目"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        ) : (
          <form onSubmit={handleCreate} className="flex items-center gap-2">
            <input
              autoFocus
              className="w-48 rounded-lg border border-indigo-500 bg-studio-bg px-2.5 py-1 text-sm text-white focus:outline-none"
              placeholder="输入项目名称..."
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <select
              className="rounded-lg border border-studio-border bg-studio-bg px-2 py-1 text-xs text-slate-200"
              value={newRatio}
              onChange={(e) => setNewRatio(e.target.value as "16:9" | "9:16" | "1:1")}
            >
              <option value="16:9">16:9 横屏</option>
              <option value="9:16">9:16 竖屏</option>
              <option value="1:1">1:1 方屏</option>
            </select>
            <button type="submit" className="studio-btn-primary">
              创建
            </button>
            <button type="button" className="studio-btn-ghost" onClick={() => setCreating(false)}>
              取消
            </button>
          </form>
        )}
      </div>

      <div className="flex items-center gap-3">
        {activeJobs.length > 0 && (
          <div className="flex items-center gap-2 rounded-full border border-indigo-500/40 bg-indigo-500/10 px-3 py-1 text-xs text-indigo-300">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            <span>
              {activeJobs.length} 个后台任务 · {activeJobs[0].message} ({activeJobs[0].progress}%)
            </span>
          </div>
        )}

        {budget && (
          <div
            className="hidden items-center gap-2.5 rounded-lg border border-studio-border bg-studio-bg px-3 py-1.5 text-xs md:flex"
            title={`本月真实预估花费 $${budget.spent_usd.toFixed(2)} / 预算 $${budget.monthly_budget_usd.toFixed(0)}（Demo 模拟节省 $${budget.demo_simulated_usd.toFixed(2)}）`}
          >
            <span className="text-slate-400">本月额度</span>
            <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-800">
              <div className={`h-full ${barColor}`} style={{ width: `${Math.min(100, pct)}%` }} />
            </div>
            <span className="font-mono text-slate-200">
              ${budget.spent_usd.toFixed(2)} / ${budget.monthly_budget_usd.toFixed(0)}
            </span>
          </div>
        )}

        {settings && (
          <button
            onClick={onOpenSettings}
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 transition ${
              settings.effective_mode === "live"
                ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30 hover:bg-emerald-500/20"
                : "bg-amber-500/10 text-amber-300 ring-amber-500/30 hover:bg-amber-500/20"
            }`}
            title="点击配置 API Key 或切换运行模式"
          >
            <Sparkles className="h-3 w-3" />
            {settings.effective_mode === "live" ? "LIVE · Google AI" : "DEMO 本地演示"}
          </button>
        )}

        <button className="studio-btn-secondary" onClick={onOpenSettings}>
          <SettingsIcon className="h-3.5 w-3.5" />
          设置
        </button>
      </div>
    </header>
  );
};
