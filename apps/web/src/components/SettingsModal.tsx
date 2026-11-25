import React, { useEffect, useState } from "react";
import { CheckCircle2, KeyRound, Loader2, PlugZap, Save, X, XCircle } from "lucide-react";
import { api } from "../api";
import type { AppMode, ConnectionTestResult, Settings } from "../types";

interface SettingsModalProps {
  open: boolean;
  settings: Settings | null;
  onClose: () => void;
  onSave: (payload: Partial<Settings> & { gemini_api_key?: string }) => Promise<void>;
}

const GEMINI4_MODELS = [
  "gemini-4-hydrogen",
  "gemini-4-neon",
  "gemini-4-argon",
  "gemini-4-carbon",
  "gemini-3.5-flash-lite",
];

export const SettingsModal: React.FC<SettingsModalProps> = ({ open, settings, onClose, onSave }) => {
  const [appMode, setAppMode] = useState<AppMode>("auto");
  const [geminiKey, setGeminiKey] = useState("");
  const [vertexProject, setVertexProject] = useState("");
  const [vertexLocation, setVertexLocation] = useState("us-central1");
  const [credsPath, setCredsPath] = useState("");
  const [textModel, setTextModel] = useState("gemini-4-hydrogen");
  const [imageModel, setImageModel] = useState("gemini-nano-banana-2.1");
  const [omniModel, setOmniModel] = useState("gemini-omni-1.2-flash");
  const [veoLite, setVeoLite] = useState("veo-3.1-lite-generate-001");
  const [veoFast, setVeoFast] = useState("veo-3.1-fast-generate-001");
  const [veoStd, setVeoStd] = useState("veo-3.1-generate-001");
  const [musicModel, setMusicModel] = useState("lyria-3.5");
  const [maxConcurrent, setMaxConcurrent] = useState(3);
  const [reqTimeout, setReqTimeout] = useState(900);
  const [budget, setBudget] = useState(40);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);

  useEffect(() => {
    if (!settings) return;
    setAppMode(settings.app_mode);
    setGeminiKey(settings.gemini_api_key_masked || "");
    setVertexProject(settings.vertex_project_id || "");
    setVertexLocation(settings.vertex_location || "us-central1");
    setCredsPath(settings.google_application_credentials || "");
    setTextModel(settings.text_model);
    setImageModel(settings.image_model);
    setOmniModel(settings.omni_video_model);
    setVeoLite(settings.veo_lite_model);
    setVeoFast(settings.veo_fast_model);
    setVeoStd(settings.veo_standard_model);
    setMusicModel(settings.music_model);
    setMaxConcurrent(settings.max_concurrent_jobs || 3);
    setReqTimeout(settings.video_request_timeout || 900);
    setBudget(settings.monthly_budget_usd);
    setTestResult(null);
  }, [settings, open]);

  if (!open || !settings) return null;

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.testConnection(geminiKey);
      setTestResult(res);
    } catch (e) {
      setTestResult({
        ok: false,
        message: e instanceof Error ? e.message : "测试失败",
        checked_model: null,
      });
    } finally {
      setTesting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await onSave({
        app_mode: appMode,
        gemini_api_key: geminiKey,
        vertex_project_id: vertexProject,
        vertex_location: vertexLocation,
        google_application_credentials: credsPath,
        text_model: textModel,
        image_model: imageModel,
        omni_video_model: omniModel,
        veo_lite_model: veoLite,
        veo_fast_model: veoFast,
        veo_standard_model: veoStd,
        music_model: musicModel,
        max_concurrent_jobs: maxConcurrent,
        video_request_timeout: reqTimeout,
        monthly_budget_usd: budget,
      });
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-studio-border bg-studio-panel p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2 text-lg font-semibold text-white">
            <KeyRound className="h-5 w-5 text-indigo-400" />
            Google 全家桶配置（自动同步至 .env）
          </div>
          <button className="studio-btn-ghost" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-300">运行模式</label>
              <select
                className="studio-input"
                value={appMode}
                onChange={(e) => setAppMode(e.target.value as AppMode)}
              >
                <option value="auto">Auto（有 Key 走 Live，无 Key 走 Demo）</option>
                <option value="live">Live（强制调用真实 Google AI）</option>
                <option value="demo">Demo（强制本地免费演示）</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-300">
                月度预算警戒线（USD）
              </label>
              <div className="flex gap-2">
                <input
                  type="number"
                  step="5"
                  min="5"
                  className="studio-input"
                  value={budget}
                  onChange={(e) => setBudget(Number(e.target.value))}
                />
                <button
                  type="button"
                  className="studio-btn-secondary whitespace-nowrap"
                  onClick={() => setBudget(40)}
                >
                  Ultra 5x ($40)
                </button>
                <button
                  type="button"
                  className="studio-btn-secondary whitespace-nowrap"
                  onClick={() => setBudget(100)}
                >
                  20x ($100)
                </button>
              </div>
            </div>
          </div>

          <div className="space-y-3 rounded-xl border border-studio-border bg-studio-card p-4">
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold uppercase tracking-wider text-indigo-400">
                1. Gemini API（Google AI Studio · 推荐使用 Ultra 开发者额度）
              </div>
              <button
                type="button"
                className="studio-btn-secondary py-1 text-[11px]"
                onClick={handleTest}
                disabled={testing}
              >
                {testing ? <Loader2 className="h-3 w-3 animate-spin" /> : <PlugZap className="h-3 w-3 text-emerald-400" />}
                测试连通性
              </button>
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-300">GEMINI_API_KEY</label>
              <input
                type="password"
                className="studio-input font-mono"
                placeholder="AIzaSy...（可直接修改根目录 .env 或在此粘贴）"
                value={geminiKey}
                onChange={(e) => setGeminiKey(e.target.value)}
              />
              <p className="mt-1 text-[11px] text-slate-400">
                驱动：Gemini 4 导演/审片、Nano Banana 2.1 生图、Gemini Omni 1.2 视频、Lyria 3.5 配乐。
              </p>
            </div>
            {testResult && (
              <div
                className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
                  testResult.ok
                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
                    : "border-rose-500/30 bg-rose-500/10 text-rose-200"
                }`}
              >
                {testResult.ok ? (
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                ) : (
                  <XCircle className="h-4 w-4 shrink-0 text-rose-400" />
                )}
                <span>{testResult.message}</span>
              </div>
            )}
          </div>

          <div className="space-y-3 rounded-xl border border-studio-border bg-studio-card p-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-emerald-400">
              2. Vertex AI（可选 · 调用 Veo 3.1 Lite / Fast / Standard 正式版）
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs text-slate-300">VERTEX_PROJECT_ID</label>
                <input
                  className="studio-input font-mono"
                  placeholder="my-gcp-project-id"
                  value={vertexProject}
                  onChange={(e) => setVertexProject(e.target.value)}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-300">VERTEX_LOCATION</label>
                <input
                  className="studio-input font-mono"
                  value={vertexLocation}
                  onChange={(e) => setVertexLocation(e.target.value)}
                />
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-300">
                GOOGLE_APPLICATION_CREDENTIALS（服务账号 JSON 路径，如已配 gcloud ADC 可留空）
              </label>
              <input
                className="studio-input font-mono"
                placeholder="C:\path\to\service-account.json"
                value={credsPath}
                onChange={(e) => setCredsPath(e.target.value)}
              />
            </div>
          </div>

          <details className="rounded-xl border border-studio-border bg-studio-card p-4">
            <summary className="cursor-pointer text-xs font-semibold text-slate-300">
              高级选项：2026 Google 官方模型 ID 与并发超时设置
            </summary>
            <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
              <div>
                <label className="mb-1 block text-[11px] text-slate-400">导演/拆镜/审片模型 (Gemini 4)</label>
                <input
                  list="gemini4-models-list"
                  className="studio-input font-mono text-xs"
                  value={textModel}
                  onChange={(e) => setTextModel(e.target.value)}
                />
                <datalist id="gemini4-models-list">
                  {GEMINI4_MODELS.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-slate-400">生图模型 (Nano Banana 2.1)</label>
                <input className="studio-input font-mono text-xs" value={imageModel} onChange={(e) => setImageModel(e.target.value)} />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-slate-400">Omni 视频模型</label>
                <input className="studio-input font-mono text-xs" value={omniModel} onChange={(e) => setOmniModel(e.target.value)} />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-slate-400">配乐模型 (Lyria 3.5)</label>
                <input className="studio-input font-mono text-xs" value={musicModel} onChange={(e) => setMusicModel(e.target.value)} />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-slate-400">Veo 3.1 Lite</label>
                <input className="studio-input font-mono text-xs" value={veoLite} onChange={(e) => setVeoLite(e.target.value)} />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-slate-400">Veo 3.1 Fast</label>
                <input className="studio-input font-mono text-xs" value={veoFast} onChange={(e) => setVeoFast(e.target.value)} />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-slate-400">Veo 3.1 Standard</label>
                <input className="studio-input font-mono text-xs" value={veoStd} onChange={(e) => setVeoStd(e.target.value)} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">最大并发 (1-6)</label>
                  <input
                    type="number"
                    min={1}
                    max={6}
                    className="studio-input font-mono text-xs"
                    value={maxConcurrent}
                    onChange={(e) => setMaxConcurrent(Number(e.target.value) || 3)}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">请求超时(秒)</label>
                  <input
                    type="number"
                    min={120}
                    max={1800}
                    step={60}
                    className="studio-input font-mono text-xs"
                    value={reqTimeout}
                    onChange={(e) => setReqTimeout(Number(e.target.value) || 900)}
                  />
                </div>
              </div>
            </div>
          </details>

          <div className="flex items-center justify-between rounded-lg bg-studio-bg px-3 py-2 text-xs">
            <span className="flex items-center gap-1.5 text-slate-300">
              <CheckCircle2 className={`h-4 w-4 ${settings.ffmpeg_available ? "text-emerald-400" : "text-rose-400"}`} />
              FFmpeg：{settings.ffmpeg_available ? "就绪" : "未检测到"} · FFprobe：{settings.ffprobe_available ? "就绪" : "回退模式"}
            </span>
            <span className="max-w-xs truncate font-mono text-[11px] text-slate-500" title={settings.ffmpeg_path}>
              {settings.ffmpeg_path}
            </span>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="studio-btn-secondary" onClick={onClose}>
              取消
            </button>
            <button type="submit" className="studio-btn-primary" disabled={saving}>
              <Save className="h-3.5 w-3.5" />
              {saving ? "保存中..." : "保存配置"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
