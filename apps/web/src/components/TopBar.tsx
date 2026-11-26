import React, { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Clapperboard,
  FolderPlus,
  History,
  KeyRound,
  Loader2,
  LogOut,
  Settings as SettingsIcon,
  Sparkles,
  Trash2,
} from "lucide-react";
import type { BudgetSummary, JobTask, Project, Settings } from "../types";

interface TopBarProps {
  projects: Project[];
  currentProject: Project | null;
  settings: Settings | null;
  budget: BudgetSummary | null;
  activeJobs: JobTask[];
  tasks?: JobTask[];
  authEnabled?: boolean;
  authUsername?: string | null;
  onSelectProject: (id: string) => void;
  onCreateProject: (name: string, aspectRatio: "16:9" | "9:16" | "1:1") => Promise<void>;
  onDeleteProject: (id: string) => Promise<void>;
  onOpenSettings: () => void;
  onOpenAccount?: () => void;
  onLogout?: () => void;
}

const KIND_LABELS: Record<string, string> = {
  video: "视频生成",
  batch_video: "批量拍片",
  image: "图片生成",
  turnaround: "角色三视图",
  bgm: "AI 配乐",
  qa: "视频审片",
  export: "成片导出",
  book_bible: "小说设定集",
  episode_breakdown: "分集拆镜",
};

export const TopBar: React.FC<TopBarProps> = ({
  projects,
  currentProject,
  settings,
  budget,
  activeJobs,
  tasks = [],
  authEnabled,
  authUsername,
  onSelectProject,
  onCreateProject,
  onDeleteProject,
  onOpenSettings,
  onOpenAccount,
  onLogout,
}) => {
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newRatio, setNewRatio] = useState<"16:9" | "9:16" | "1:1">("16:9");
  const [tasksOpen, setTasksOpen] = useState(false);

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
        {(activeJobs.length > 0 || tasks.length > 0) && (
          <div className="relative">
            {(() => {
              const failedCount = tasks.filter((t) => t.status === "failed").length;
              const hasFailedLatest = tasks[0]?.status === "failed";
              return (
                <button
                  type="button"
                  onClick={() => setTasksOpen((v) => !v)}
                  className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs transition ${
                    activeJobs.length > 0
                      ? "border-indigo-500/40 bg-indigo-500/10 text-indigo-300 hover:bg-indigo-500/20"
                      : hasFailedLatest
                      ? "border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20"
                      : "border-studio-border bg-studio-bg text-slate-300 hover:border-slate-600"
                  }`}
                  title="点击查看后台任务进度与失败日志"
                >
                  {activeJobs.length > 0 ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      <span className="max-w-[240px] truncate">
                        {activeJobs.length} 个任务 · {activeJobs[0].message} ({activeJobs[0].progress}%)
                      </span>
                    </>
                  ) : hasFailedLatest ? (
                    <>
                      <AlertTriangle className="h-3.5 w-3.5 text-rose-400" />
                      <span>任务失败 ({failedCount})</span>
                    </>
                  ) : (
                    <>
                      <History className="h-3.5 w-3.5 text-slate-400" />
                      <span>
                        任务记录 ({tasks.length}
                        {failedCount > 0 ? ` · ${failedCount}异常` : ""})
                      </span>
                    </>
                  )}
                  <ChevronDown className="h-3 w-3 opacity-70" />
                </button>
              );
            })()}

            {tasksOpen && (
              <div className="absolute right-0 top-10 z-50 w-96 max-w-[90vw] rounded-xl border border-studio-border bg-studio-panel p-3 shadow-2xl">
                <div className="mb-2 flex items-center justify-between border-b border-studio-border pb-2">
                  <span className="text-xs font-semibold text-white">最近后台任务记录</span>
                  <button
                    type="button"
                    className="text-[11px] text-slate-400 hover:text-white"
                    onClick={() => setTasksOpen(false)}
                  >
                    关闭
                  </button>
                </div>
                <div className="max-h-96 space-y-2 overflow-y-auto pr-1">
                  {tasks.slice(0, 12).map((t) => (
                    <div
                      key={t.id}
                      className="rounded-lg border border-studio-border/80 bg-studio-bg p-2.5 text-xs"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-slate-200">
                          {KIND_LABELS[t.kind] || t.kind}
                        </span>
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                            t.status === "completed"
                              ? "bg-emerald-500/15 text-emerald-300"
                              : t.status === "failed"
                              ? "bg-rose-500/15 text-rose-300"
                              : "bg-indigo-500/15 text-indigo-300"
                          }`}
                        >
                          {t.status === "completed" && <CheckCircle2 className="h-3 w-3" />}
                          {t.status === "failed" && <AlertTriangle className="h-3 w-3" />}
                          {(t.status === "running" || t.status === "queued") && (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          )}
                          {t.status === "completed"
                            ? "已完成"
                            : t.status === "failed"
                            ? "失败"
                            : `${t.progress}%`}
                        </span>
                      </div>
                      <p className="mt-1 text-[11px] text-slate-400">{t.message}</p>
                      {t.error && (
                        <pre className="mt-1.5 max-h-28 overflow-auto whitespace-pre-wrap break-all rounded border border-rose-500/30 bg-rose-950/50 p-2 font-mono text-[10px] text-rose-200 select-all">
                          {t.error}
                        </pre>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
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

        {authEnabled && authUsername && (
          <div className="flex items-center gap-1.5 border-l border-studio-border pl-2.5">
            {onOpenAccount && (
              <button
                className="studio-btn-ghost text-xs text-slate-300 hover:text-white"
                onClick={onOpenAccount}
                title="修改管理员密码"
              >
                <KeyRound className="h-3.5 w-3.5 text-indigo-400" />
                <span>{authUsername}</span>
              </button>
            )}
            {onLogout && (
              <button
                className="studio-btn-ghost text-xs text-slate-400 hover:text-rose-300"
                onClick={onLogout}
                title="退出登录"
              >
                <LogOut className="h-3.5 w-3.5" />
                <span>退出</span>
              </button>
            )}
          </div>
        )}
      </div>
    </header>
  );
};
