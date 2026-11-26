import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, BookOpen, Film, Layers, Loader2, Scissors, Sparkles, X } from "lucide-react";
import { api, setUnauthorizedHandler } from "./api";
import { AccountModal } from "./components/AccountModal";
import { AssetHub } from "./components/AssetHub";
import { AuthScreen } from "./components/AuthScreen";
import { DirectorChat } from "./components/DirectorChat";
import { NovelTab } from "./components/NovelTab";
import { SettingsModal } from "./components/SettingsModal";
import { StoryboardTab } from "./components/StoryboardTab";
import { StudioTab } from "./components/StudioTab";
import { TimelineTab } from "./components/TimelineTab";
import { TopBar } from "./components/TopBar";
import type {
  Asset,
  AuthStatus,
  BudgetSummary,
  ChatMessage,
  Episode,
  ExportRecord,
  JobTask,
  Project,
  Settings,
  Shot,
  StudioDraftInjection,
  StudioJob,
} from "./types";

type ActiveTab = "novel" | "assets" | "storyboard" | "timeline" | "studio";

export default function App() {
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [accountOpen, setAccountOpen] = useState(false);

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
  const [studioJobs, setStudioJobs] = useState<StudioJob[]>([]);
  const [draftInjection, setDraftInjection] = useState<StudioDraftInjection | null>(null);

  const [activeTab, setActiveTab] = useState<ActiveTab>("storyboard");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sendingChat, setSendingChat] = useState(false);
  const [toast, setToast] = useState<{ kind: "info" | "error"; text: string } | null>(null);

  const showToast = useCallback((text: string, kind: "info" | "error" = "info") => {
    setToast({ kind, text });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const ms = toast.kind === "error" ? 12000 : 5000;
    const t = setTimeout(() => setToast(null), ms);
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
    const [a, ep, sh, ch, tk, ex, sj, b, ps] = await Promise.all([
      api.listAssets(pid),
      api.listEpisodes(pid),
      api.listShots(pid),
      api.listChat(pid),
      api.listTasks(pid),
      api.listExports(pid),
      api.listStudioJobs(pid),
      api.getBudget(),
      api.listProjects(),
    ]);
    setAssets(a);
    setEpisodes(ep);
    setShots(sh);
    setMessages(ch);
    setTasks(tk);
    setExportsList(ex);
    setStudioJobs(sj);
    setBudget(b);
    setProjects(ps);
  }, []);

  const filteredShots = useMemo(() => {
    if (selectedEpisodeFilter === "all") return shots;
    return shots.filter((s) => s.episode_id === selectedEpisodeFilter);
  }, [shots, selectedEpisodeFilter]);

  const isAuthorized = Boolean(
    authStatus && (!authStatus.auth_enabled || authStatus.authenticated)
  );

  const refreshAuth = useCallback(async () => {
    try {
      const s = await api.getAuthStatus();
      setAuthStatus(s);
    } catch (err) {
      showToast(`检查登录状态失败：${(err as Error).message}`, "error");
    } finally {
      setAuthLoading(false);
    }
  }, [showToast]);

  const handleLogout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // ignore network error during logout
    }
    setCurrentProjectId(null);
    setProjects([]);
    setAssets([]);
    setEpisodes([]);
    setShots([]);
    setMessages([]);
    setTasks([]);
    setExportsList([]);
    setStudioJobs([]);
    setSettings(null);
    setBudget(null);
    setAccountOpen(false);
    setSettingsOpen(false);
    await refreshAuth();
  }, [refreshAuth]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setAuthStatus((prev) => (prev ? { ...prev, authenticated: false } : prev));
    });
    refreshAuth();
    return () => setUnauthorizedHandler(null);
  }, [refreshAuth]);

  useEffect(() => {
    if (!isAuthorized) return;
    (async () => {
      try {
        const ps = await refreshGlobal();
        if (ps.length > 0) {
          setCurrentProjectId((prev) => prev || ps[0].id);
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
  }, [isAuthorized, refreshGlobal, showToast]);

  useEffect(() => {
    if (isAuthorized && currentProjectId) {
      refreshProjectData(currentProjectId).catch((err) => showToast((err as Error).message, "error"));
    }
  }, [isAuthorized, currentProjectId, refreshProjectData, showToast]);

  // Live SSE stream for instant Task & StudioJob updates
  useEffect(() => {
    if (!isAuthorized || !currentProjectId) return;
    const es = new EventSource("/api/tasks/events");
    es.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === "task_update" && msg.data?.id) {
          const updated = msg.data as JobTask;
          if (updated.project_id !== currentProjectId) return;
          setTasks((prev) => {
            const exists = prev.some((x) => x.id === updated.id);
            return exists ? prev.map((x) => (x.id === updated.id ? updated : x)) : [updated, ...prev];
          });
          if (updated.status === "completed") {
            showToast("后台生成任务已完成！");
            refreshProjectData(currentProjectId).catch(() => {});
          } else if (updated.status === "failed") {
            showToast(`任务失败：${updated.error || "未知错误"}`, "error");
            refreshProjectData(currentProjectId).catch(() => {});
          }
        } else if (msg.type === "studio_job_update" && msg.data?.id) {
          const updated = msg.data as StudioJob;
          if (updated.project_id !== currentProjectId) return;
          setStudioJobs((prev) => {
            const exists = prev.some((x) => x.id === updated.id);
            return exists ? prev.map((x) => (x.id === updated.id ? updated : x)) : [updated, ...prev];
          });
          if (updated.status === "completed") {
            showToast(`Omni 创作完成（${updated.resolution.toUpperCase()}）`);
            api.getBudget().then(setBudget).catch(() => {});
          } else if (updated.status === "failed") {
            showToast(updated.error_message || "Omni 创作任务失败", "error");
          }
        }
      } catch {
        // ignore keepalive / non-json
      }
    };
    return () => {
      es.close();
    };
  }, [currentProjectId, refreshProjectData, showToast]);

  // Fallback polling while background tasks are active
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
          await refreshProjectData(currentProjectId);
        }
      } catch {
        // ignore transient poll errors
      }
    }, 2500);
    return () => clearInterval(timer);
  }, [currentProjectId, activeJobs, refreshProjectData]);

  const wrap = async (fn: () => Promise<void>) => {
    try {
      await fn();
    } catch (err) {
      showToast((err as Error).message, "error");
    }
  };

  const handleSendToStudio = useCallback((draft: Omit<StudioDraftInjection, "nonce">) => {
    setDraftInjection({ ...draft, nonce: Date.now() });
    setActiveTab("studio");
  }, []);

  if (authLoading || !authStatus) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-2 bg-studio-bg text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin text-indigo-400" />
        <span>正在检查登录状态...</span>
      </div>
    );
  }

  if (!isAuthorized) {
    return (
      <AuthScreen
        status={authStatus}
        onAuthenticated={(next) => {
          setAuthStatus(next);
        }}
      />
    );
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-studio-bg text-slate-100">
      <TopBar
        projects={projects}
        currentProject={currentProject}
        settings={settings}
        budget={budget}
        activeJobs={activeJobs}
        tasks={tasks}
        authEnabled={authStatus.auth_enabled}
        authUsername={authStatus.username}
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
        onOpenAccount={() => setAccountOpen(true)}
        onLogout={handleLogout}
      />

      {toast && (
        <div
          className={`fixed bottom-4 right-4 z-50 flex max-w-lg items-start gap-2 rounded-xl border px-4 py-3 text-xs shadow-xl ${
            toast.kind === "error"
              ? "border-rose-500/40 bg-rose-950/95 text-rose-200"
              : "border-indigo-500/40 bg-studio-panel/95 text-slate-100"
          }`}
        >
          {toast.kind === "error" && <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-400" />}
          <span className="flex-1 break-all">{toast.text}</span>
          <button
            type="button"
            onClick={() => setToast(null)}
            className="shrink-0 opacity-70 hover:opacity-100"
            title="关闭提示"
          >
            <X className="h-3.5 w-3.5" />
          </button>
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

          {/* Right Workspace: 5 Focused Tabs */}
          <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-studio-border bg-studio-panel/60 px-5">
              <div className="flex flex-wrap gap-1">
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
                <button
                  onClick={() => setActiveTab("studio")}
                  className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-medium transition ${
                    activeTab === "studio"
                      ? "border-indigo-500 text-white"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Sparkles className="h-3.5 w-3.5 text-cyan-300" />
                  4. 全模态自由创作 / V2V ({studioJobs.length})
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
                  onUploadMediaFiles={(files) =>
                    wrap(async () => {
                      for (const file of Array.from(files)) {
                        await api.uploadMediaAsset(currentProject.id, file);
                      }
                      await refreshProjectData(currentProject.id);
                      showToast(`已上传 ${files.length} 个媒体素材`);
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
                      showToast("参考文件已上传");
                    })
                  }
                  onPrepAsset={(id, payload) =>
                    wrap(async () => {
                      const created = await api.prepAsset(currentProject.id, id, payload);
                      await refreshProjectData(currentProject.id);
                      showToast(`FFmpeg 预处理完成：${created.name}`);
                    })
                  }
                  onExtractFrame={(id, position) =>
                    wrap(async () => {
                      const created = await api.extractAssetFrame(currentProject.id, id, position);
                      await refreshProjectData(currentProject.id);
                      showToast(`已抽取关键帧存入资产库：${created.name}`);
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
                  onSendToStudio={handleSendToStudio}
                />
              )}

              {activeTab === "storyboard" && (
                <StoryboardTab
                  shots={filteredShots}
                  assets={assets}
                  tasks={tasks}
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
                  onBatchGenerate={(payload) =>
                    wrap(async () => {
                      const res = await api.batchGenerateShots(currentProject.id, {
                        ...payload,
                        episode_id: selectedEpisodeFilter === "all" ? null : selectedEpisodeFilter,
                      });
                      if (res.tasks.length > 0) {
                        setTasks((prev) => [...res.tasks, ...prev]);
                      }
                      showToast(
                        payload.chain_last_frame
                          ? "已启动尾帧接力批量拍片（依次拍片并自动传递尾帧）"
                          : `已提交 ${res.submitted_count} 个并行拍片任务`
                      );
                    })
                  }
                  onIterateTake={(sid, tid, payload) =>
                    wrap(async () => {
                      const job = await api.iterateTake(currentProject.id, sid, tid, payload);
                      setTasks((prev) => [job, ...prev]);
                      showToast(`已提交 Omni ${payload.action === "extend" ? "续写" : "多轮改片"}任务`);
                    })
                  }
                  onEnhanceShotPrompt={(shot) =>
                    wrap(async () => {
                      const enhanced = await api.enhancePrompt(currentProject.id, {
                        prompt: shot.visual_prompt_zh || shot.video_prompt_en || shot.title,
                        mode: shot.start_frame_url ? "first_frame" : "text_to_video",
                        duration_seconds: Math.max(3, Math.min(15, shot.duration_sec || 6)),
                        aspect_ratio: currentProject.aspect_ratio === "9:16" ? "9:16" : "16:9",
                        single_scene: true,
                        style_hint: currentProject.style_prompt,
                        audio_preference: shot.sfx_prompt || undefined,
                        has_first_frame: Boolean(shot.start_frame_url),
                        has_last_frame: Boolean(shot.end_frame_url),
                        ref_image_count: shot.asset_ids.length,
                      });
                      await api.updateShot(currentProject.id, shot.id, {
                        video_prompt_en: enhanced.enhanced_prompt_en,
                      });
                      await refreshProjectData(currentProject.id);
                      showToast("Gemini 4 已完成该镜英文提示词扩写并保存！");
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
                  onSendToStudio={handleSendToStudio}
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

              {activeTab === "studio" && (
                <StudioTab
                  project={currentProject}
                  assets={assets}
                  shots={filteredShots}
                  studioJobs={studioJobs}
                  settings={settings}
                  draftInjection={draftInjection}
                  onRefreshAssets={() => refreshProjectData(currentProject.id)}
                  onRefreshStudioJobs={() => refreshProjectData(currentProject.id)}
                  onRefreshShots={() => refreshProjectData(currentProject.id)}
                  onStudioJobCreated={(job) =>
                    setStudioJobs((prev) => [job, ...prev.filter((x) => x.id !== job.id)])
                  }
                  onOpenSettings={() => setSettingsOpen(true)}
                  onToast={showToast}
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

      <AccountModal
        open={accountOpen}
        username={authStatus.username || "admin"}
        onClose={() => setAccountOpen(false)}
        onSuccess={(msg) => showToast(msg)}
      />
    </div>
  );
}
