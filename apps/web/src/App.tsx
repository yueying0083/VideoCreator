import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, BookOpen, Film, Layers, Scissors } from "lucide-react";
import { api } from "./api";
import { AssetHub } from "./components/AssetHub";
import { DirectorChat } from "./components/DirectorChat";
import { NovelTab } from "./components/NovelTab";
import { SettingsModal } from "./components/SettingsModal";
import { StoryboardTab } from "./components/StoryboardTab";
import { TimelineTab } from "./components/TimelineTab";
import { TopBar } from "./components/TopBar";
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
} from "./types";

type ActiveTab = "novel" | "assets" | "storyboard" | "timeline";

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [budget, setBudget] = useState<BudgetSummary | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);

  const [assets, setAssets] = useState<Asset[]>([]);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [selectedEpisodeFilter, setSelectedEpisodeFilter] = useState<string>("all");
  const [shots, setShots] = useState<Shot[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [tasks, setTasks] = useState<JobTask[]>([]);
  const [exportsList, setExportsList] = useState<ExportRecord[]>([]);

  const [activeTab, setActiveTab] = useState<ActiveTab>("storyboard");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sendingChat, setSendingChat] = useState(false);
  const [toast, setToast] = useState<{ kind: "info" | "error"; text: string } | null>(null);

  const showToast = useCallback((text: string, kind: "info" | "error" = "info") => {
    setToast({ kind, text });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(t);
  }, [toast]);

  const currentProject = useMemo(
    () => projects.find((p) => p.id === currentProjectId) || null,
    [projects, currentProjectId]
  );

  const activeJobs = useMemo(
    () => tasks.filter((t) => t.status === "queued" || t.status === "running"),
    [tasks]
  );

  const refreshGlobal = useCallback(async () => {
    const [s, b, ps] = await Promise.all([api.getSettings(), api.getBudget(), api.listProjects()]);
    setSettings(s);
    setBudget(b);
    setProjects(ps);
    return ps;
  }, []);

  const refreshProjectData = useCallback(async (pid: string) => {
    const [a, ep, sh, ch, tk, ex, b, ps] = await Promise.all([
      api.listAssets(pid),
      api.listEpisodes(pid),
      api.listShots(pid),
      api.listChat(pid),
      api.listTasks(pid),
      api.listExports(pid),
      api.getBudget(),
      api.listProjects(),
    ]);
    setAssets(a);
    setEpisodes(ep);
    setShots(sh);
    setMessages(ch);
    setTasks(tk);
    setExportsList(ex);
    setBudget(b);
    setProjects(ps);
  }, []);

  const filteredShots = useMemo(() => {
    if (selectedEpisodeFilter === "all") return shots;
    return shots.filter((s) => s.episode_id === selectedEpisodeFilter);
  }, [shots, selectedEpisodeFilter]);

  // Initial bootstrap: create a starter project automatically on first launch
  useEffect(() => {
    (async () => {
      try {
        const ps = await refreshGlobal();
        if (ps.length > 0) {
          setCurrentProjectId(ps[0].id);
        } else {
          const starter = await api.createProject({
            name: "我的第一条 AI 短片",
            aspect_ratio: "16:9",
            style_prompt: "电影质感，自然光影，35mm 胶片细节",
          });
          setProjects([starter]);
          setCurrentProjectId(starter.id);
        }
      } catch (err) {
        showToast(`初始化失败：${(err as Error).message}`, "error");
      }
    })();
  }, [refreshGlobal, showToast]);

  useEffect(() => {
    if (currentProjectId) {
      refreshProjectData(currentProjectId).catch((err) => showToast((err as Error).message, "error"));
    }
  }, [currentProjectId, refreshProjectData, showToast]);

  // Poll active background tasks automatically & reload project when jobs finish
  const prevActiveCountRef = useRef(0);
  useEffect(() => {
    if (!currentProjectId || activeJobs.length === 0) {
      prevActiveCountRef.current = 0;
      return;
    }
    prevActiveCountRef.current = activeJobs.length;
    const timer = setInterval(async () => {
      try {
        const latest = await api.listTasks(currentProjectId);
        setTasks(latest);
        const stillRunning = latest.filter((t) => t.status === "queued" || t.status === "running");
        if (stillRunning.length < prevActiveCountRef.current) {
          const failed = latest.find(
            (t) => t.status === "failed" && activeJobs.some((old) => old.id === t.id)
          );
          if (failed?.error) {
            showToast(`任务失败：${failed.error}`, "error");
          } else {
            showToast("后台生成任务已完成！");
          }
          await refreshProjectData(currentProjectId);
        }
      } catch {
        // ignore transient poll errors
      }
    }, 1500);
    return () => clearInterval(timer);
  }, [currentProjectId, activeJobs, refreshProjectData, showToast]);

  const wrap = async (fn: () => Promise<void>) => {
    try {
      await fn();
    } catch (err) {
      showToast((err as Error).message, "error");
    }
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-studio-bg text-slate-100">
      <TopBar
        projects={projects}
        currentProject={currentProject}
        settings={settings}
        budget={budget}
        activeJobs={activeJobs}
        onSelectProject={(id) => setCurrentProjectId(id)}
        onCreateProject={(name, aspect_ratio) =>
          wrap(async () => {
            const created = await api.createProject({ name, aspect_ratio });
            await refreshGlobal();
            setCurrentProjectId(created.id);
            showToast(`已创建项目「${created.name}」`);
          })
        }
        onDeleteProject={(id) =>
          wrap(async () => {
            await api.deleteProject(id);
            const ps = await refreshGlobal();
            setCurrentProjectId(ps[0]?.id || null);
            showToast("项目已删除");
          })
        }
        onOpenSettings={() => setSettingsOpen(true)}
      />

      {toast && (
        <div
          className={`fixed bottom-4 right-4 z-50 flex max-w-md items-center gap-2 rounded-xl border px-4 py-3 text-xs shadow-xl ${
            toast.kind === "error"
              ? "border-rose-500/40 bg-rose-950/90 text-rose-200"
              : "border-indigo-500/40 bg-studio-panel/95 text-slate-100"
          }`}
        >
          {toast.kind === "error" && <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />}
          <span>{toast.text}</span>
        </div>
      )}

      {currentProject ? (
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {/* Left Pane: AI Director Chat */}
          <DirectorChat
            messages={messages}
            assets={assets}
            sending={sendingChat}
            onSend={(text) =>
              wrap(async () => {
                setSendingChat(true);
                try {
                  await api.sendChat(currentProject.id, text);
                  await refreshProjectData(currentProject.id);
                } finally {
                  setSendingChat(false);
                }
              })
            }
            onApplyProposal={(mid) =>
              wrap(async () => {
                const res = await api.applyProposal(currentProject.id, mid);
                await refreshProjectData(currentProject.id);
                setActiveTab("storyboard");
                showToast(`已应用导演提案：新增 ${res.applied_assets} 个资产、${res.applied_shots} 个分镜！`);
              })
            }
          />

          {/* Right Workspace: 4 Focused Tabs */}
          <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-studio-border bg-studio-panel/60 px-5">
              <div className="flex gap-1">
                <button
                  onClick={() => setActiveTab("novel")}
                  className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-medium transition ${
                    activeTab === "novel"
                      ? "border-indigo-500 text-white"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <BookOpen className="h-3.5 w-3.5" />
                  0. 小说拆集 ({episodes.length})
                </button>
                <button
                  onClick={() => setActiveTab("assets")}
                  className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-medium transition ${
                    activeTab === "assets"
                      ? "border-indigo-500 text-white"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Layers className="h-3.5 w-3.5" />
                  1. 资产定妆库 ({assets.length})
                </button>
                <button
                  onClick={() => setActiveTab("storyboard")}
                  className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-medium transition ${
                    activeTab === "storyboard"
                      ? "border-indigo-500 text-white"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Film className="h-3.5 w-3.5" />
                  2. 分镜故事板 ({filteredShots.length})
                </button>
                <button
                  onClick={() => setActiveTab("timeline")}
                  className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-medium transition ${
                    activeTab === "timeline"
                      ? "border-indigo-500 text-white"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Scissors className="h-3.5 w-3.5" />
                  3. 多轨时间线与导出 ({exportsList.length})
                </button>
              </div>

              {episodes.length > 0 && (activeTab === "storyboard" || activeTab === "timeline") && (
                <div className="flex items-center gap-2 py-1.5 text-xs">
                  <span className="text-slate-400">当前分集:</span>
                  <select
                    className="rounded-lg border border-studio-border bg-studio-bg px-2.5 py-1 text-xs text-indigo-300"
                    value={selectedEpisodeFilter}
                    onChange={(e) => setSelectedEpisodeFilter(e.target.value)}
                  >
                    <option value="all">全部镜头 ({shots.length})</option>
                    {episodes.map((ep, i) => (
                      <option key={ep.id} value={ep.id}>
                        第 {i + 1} 集 · {ep.title} ({ep.shot_count} 镜)
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            <div className="flex-1 overflow-y-auto">
              {activeTab === "novel" && (
                <NovelTab
                  project={currentProject}
                  episodes={episodes}
                  onImportFile={(file, splitMode, charsPerEp, replaceExisting) =>
                    wrap(async () => {
                      const eps = await api.importNovelFile(
                        currentProject.id,
                        file,
                        splitMode,
                        charsPerEp,
                        replaceExisting
                      );
                      await refreshProjectData(currentProject.id);
                      showToast(`导入成功！已自动拆分为 ${eps.length} 集。`);
                    })
                  }
                  onImportText={(payload) =>
                    wrap(async () => {
                      const eps = await api.importNovelText(currentProject.id, payload);
                      await refreshProjectData(currentProject.id);
                      showToast(`导入成功！已自动拆分为 ${eps.length} 集。`);
                    })
                  }
                  onUpdateEpisode={(eid, patch) =>
                    wrap(async () => {
                      await api.updateEpisode(currentProject.id, eid, patch);
                      await refreshProjectData(currentProject.id);
                    })
                  }
                  onDeleteEpisode={(eid) =>
                    wrap(async () => {
                      await api.deleteEpisode(currentProject.id, eid);
                      if (selectedEpisodeFilter === eid) setSelectedEpisodeFilter("all");
                      await refreshProjectData(currentProject.id);
                      showToast("分集已删除");
                    })
                  }
                  onExtractBible={(maxEpisodes) =>
                    wrap(async () => {
                      const job = await api.extractBookBible(currentProject.id, maxEpisodes);
                      setTasks((prev) => [job, ...prev]);
                    })
                  }
                  onBreakdownEpisode={(eid, targetShots, replaceExisting) =>
                    wrap(async () => {
                      const job = await api.breakdownEpisode(currentProject.id, eid, targetShots, replaceExisting);
                      setTasks((prev) => [job, ...prev]);
                    })
                  }
                  onOpenEpisodeStoryboard={(eid) => {
                    setSelectedEpisodeFilter(eid);
                    setActiveTab("storyboard");
                  }}
                />
              )}

              {activeTab === "assets" && (
                <AssetHub
                  project={currentProject}
                  assets={assets}
                  onUpdateProject={(patch) =>
                    wrap(async () => {
                      await api.updateProject(currentProject.id, patch);
                      await refreshProjectData(currentProject.id);
                      showToast("项目风格已更新");
                    })
                  }
                  onCreateAsset={(payload) =>
                    wrap(async () => {
                      await api.createAsset(currentProject.id, payload);
                      await refreshProjectData(currentProject.id);
                    })
                  }
                  onUpdateAsset={(id, patch) =>
                    wrap(async () => {
                      await api.updateAsset(currentProject.id, id, patch);
                      await refreshProjectData(currentProject.id);
                    })
                  }
                  onDeleteAsset={(id) =>
                    wrap(async () => {
                      await api.deleteAsset(currentProject.id, id);
                      await refreshProjectData(currentProject.id);
                    })
                  }
                  onUploadAsset={(id, file) =>
                    wrap(async () => {
                      await api.uploadAssetFile(currentProject.id, id, file);
                      await refreshProjectData(currentProject.id);
                      showToast("参考图已上传");
                    })
                  }
                  onGenerateImage={(id) =>
                    wrap(async () => {
                      const job = await api.generateAssetImage(currentProject.id, id);
                      setTasks((prev) => [job, ...prev]);
                    })
                  }
                  onGenerateTurnaround={(id) =>
                    wrap(async () => {
                      const job = await api.generateAssetTurnaround(currentProject.id, id);
                      setTasks((prev) => [job, ...prev]);
                    })
                  }
                />
              )}

              {activeTab === "storyboard" && (
                <StoryboardTab
                  shots={filteredShots}
                  assets={assets}
                  effectiveMode={settings?.effective_mode || "demo"}
                  onCreateShot={() =>
                    wrap(async () => {
                      await api.createShot(currentProject.id, {
                        episode_id: selectedEpisodeFilter === "all" ? null : selectedEpisodeFilter,
                        title: `镜头 ${filteredShots.length + 1}`,
                      });
                      await refreshProjectData(currentProject.id);
                    })
                  }
                  onUpdateShot={(sid, patch) =>
                    wrap(async () => {
                      await api.updateShot(currentProject.id, sid, patch);
                      await refreshProjectData(currentProject.id);
                    })
                  }
                  onDeleteShot={(sid) =>
                    wrap(async () => {
                      await api.deleteShot(currentProject.id, sid);
                      await refreshProjectData(currentProject.id);
                    })
                  }
                  onGenerateKeyframe={(sid, which) =>
                    wrap(async () => {
                      const job = await api.generateKeyframe(currentProject.id, sid, which);
                      setTasks((prev) => [job, ...prev]);
                    })
                  }
                  onCopyPrevEndFrame={(sid) =>
                    wrap(async () => {
                      await api.copyPrevShotEndFrame(currentProject.id, sid);
                      await refreshProjectData(currentProject.id);
                      showToast("已提取上一镜尾帧作为本镜首帧！");
                    })
                  }
                  onGenerateVideo={(sid, payload) =>
                    wrap(async () => {
                      const job = await api.generateVideo(currentProject.id, sid, payload);
                      setTasks((prev) => [job, ...prev]);
                    })
                  }
                  onImportTake={(sid, file) =>
                    wrap(async () => {
                      await api.importTake(currentProject.id, sid, file);
                      await refreshProjectData(currentProject.id);
                      showToast("外部视频已导入为新 Take 并自动锁定！");
                    })
                  }
                  onRunQa={(sid, tid) =>
                    wrap(async () => {
                      const job = await api.runTakeQa(currentProject.id, sid, tid);
                      setTasks((prev) => [job, ...prev]);
                    })
                  }
                  onToast={(msg) => showToast(msg)}
                />
              )}

              {activeTab === "timeline" && (
                <TimelineTab
                  project={currentProject}
                  shots={filteredShots}
                  exportsList={exportsList}
                  onUpdateProject={(patch) =>
                    wrap(async () => {
                      await api.updateProject(currentProject.id, patch);
                      await refreshProjectData(currentProject.id);
                    })
                  }
                  onUpdateShot={(sid, patch) =>
                    wrap(async () => {
                      await api.updateShot(currentProject.id, sid, patch);
                      await refreshProjectData(currentProject.id);
                    })
                  }
                  onGenerateBgm={(prompt, mode) =>
                    wrap(async () => {
                      const job = await api.generateBgm(currentProject.id, prompt, mode);
                      setTasks((prev) => [job, ...prev]);
                    })
                  }
                  onUploadBgm={(file) =>
                    wrap(async () => {
                      await api.uploadBgm(currentProject.id, file);
                      await refreshProjectData(currentProject.id);
                      showToast("BGM 已上传");
                    })
                  }
                  onAutoSubtitles={() =>
                    wrap(async () => {
                      await api.autoSubtitles(
                        currentProject.id,
                        selectedEpisodeFilter === "all" ? null : selectedEpisodeFilter
                      );
                      await refreshProjectData(currentProject.id);
                      showToast("已从当前分镜台词自动生成 SRT 字幕");
                    })
                  }
                  onExport={(payload) =>
                    wrap(async () => {
                      const job = await api.createExport(currentProject.id, {
                        ...payload,
                        episode_id: selectedEpisodeFilter === "all" ? null : selectedEpisodeFilter,
                      });
                      setTasks((prev) => [job, ...prev]);
                    })
                  }
                />
              )}
            </div>
          </main>
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center text-sm text-slate-500">正在加载工作台...</div>
      )}

      <SettingsModal
        open={settingsOpen}
        settings={settings}
        onClose={() => setSettingsOpen(false)}
        onSave={(payload) =>
          wrap(async () => {
            const updated = await api.updateSettings(payload);
            setSettings(updated);
            setBudget(await api.getBudget());
            showToast(`配置已保存至 .env（当前模式: ${updated.effective_mode.toUpperCase()}）`);
          })
        }
      />
    </div>
  );
}
