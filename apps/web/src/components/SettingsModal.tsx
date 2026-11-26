import React, { useEffect, useState } from "react";
import { CheckCircle2, Image as ImageIcon, KeyRound, Loader2, PlugZap, Save, X, XCircle } from "lucide-react";
import { api } from "../api";
import type { AppMode, ConnectionTestResult, ImageProvider, Settings } from "../types";

interface SettingsModalProps {
  open: boolean;
  settings: Settings | null;
  onClose: () => void;
  onSave: (payload: Partial<Settings> & { gemini_api_key?: string; openai_api_key?: string }) => Promise<void>;
}

const GEMINI4_MODELS = [
  "gemini-4-hydrogen",
  "gemini-4-neon",
  "gemini-4-argon",
  "gemini-4-carbon",
  "gemini-3.5-flash-lite",
];

const OPENAI_IMAGE_MODELS = [
  "gpt-image-1",
  "gpt-image-1.5",
  "gpt-image-1-mini",
  "dall-e-3",
];

export const SettingsModal: React.FC<SettingsModalProps> = ({ open, settings, onClose, onSave }) => {
  const [appMode, setAppMode] = useState<AppMode>("auto");
  const [geminiKey, setGeminiKey] = useState("");
  const [imageProvider, setImageProvider] = useState<ImageProvider>("gemini");
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState("https://api.openai.com/v1");
  const [openaiApiKey, setOpenaiApiKey] = useState("");
  const [openaiImageModel, setOpenaiImageModel] = useState("gpt-image-1");
  const [openaiMaxConcurrent, setOpenaiMaxConcurrent] = useState(2);
  const [textModel, setTextModel] = useState("gemini-4-hydrogen");
  const [imageModel, setImageModel] = useState("gemini-nano-banana-2.1");
  const [omniModel, setOmniModel] = useState("gemini-omni-1.2-flash");
  const [musicModel, setMusicModel] = useState("lyria-3.5");
  const [maxConcurrent, setMaxConcurrent] = useState(3);
  const [reqTimeout, setReqTimeout] = useState(900);
  const [budget, setBudget] = useState(40);
  const [saving, setSaving] = useState(false);

  const [testingGemini, setTestingGemini] = useState(false);
  const [geminiTestResult, setGeminiTestResult] = useState<ConnectionTestResult | null>(null);

  const [testingOpenai, setTestingOpenai] = useState(false);
  const [openaiTestResult, setOpenaiTestResult] = useState<ConnectionTestResult | null>(null);

  useEffect(() => {
    if (!settings) return;
    setAppMode(settings.app_mode);
    setGeminiKey(settings.gemini_api_key_masked || "");
    setImageProvider(settings.image_provider || "gemini");
    setOpenaiBaseUrl(settings.openai_base_url || "https://api.openai.com/v1");
    setOpenaiApiKey(settings.openai_api_key_masked || "");
    setOpenaiImageModel(settings.openai_image_model || "gpt-image-1");
    setOpenaiMaxConcurrent(settings.openai_max_concurrent || 2);
    setTextModel(settings.text_model);
    setImageModel(settings.image_model);
    setOmniModel(settings.omni_video_model);
    setMusicModel(settings.music_model);
    setMaxConcurrent(settings.max_concurrent_jobs || 3);
    setReqTimeout(settings.video_request_timeout || 900);
    setBudget(settings.monthly_budget_usd);
    setGeminiTestResult(null);
    setOpenaiTestResult(null);
  }, [settings, open]);

  if (!open || !settings) return null;

  const handleTestGemini = async () => {
    setTestingGemini(true);
    setGeminiTestResult(null);
    try {
      const res = await api.testConnection(geminiKey);
      setGeminiTestResult(res);
    } catch (e) {
      setGeminiTestResult({
        ok: false,
        message: e instanceof Error ? e.message : "测试失败",
        checked_model: null,
      });
    } finally {
      setTestingGemini(false);
    }
  };

  const handleTestOpenai = async () => {
    setTestingOpenai(true);
    setOpenaiTestResult(null);
    try {
      const res = await api.testOpenAIConnection({
        openai_base_url: openaiBaseUrl,
        openai_api_key: openaiApiKey,
        openai_image_model: openaiImageModel,
      });
      setOpenaiTestResult(res);
    } catch (e) {
      setOpenaiTestResult({
        ok: false,
        message: e instanceof Error ? e.message : "测试失败",
        checked_model: null,
      });
    } finally {
      setTestingOpenai(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await onSave({
        app_mode: appMode,
        gemini_api_key: geminiKey,
        image_provider: imageProvider,
        openai_base_url: openaiBaseUrl,
        openai_api_key: openaiApiKey,
        openai_image_model: openaiImageModel,
        openai_max_concurrent: openaiMaxConcurrent,
        text_model: textModel,
        image_model: imageModel,
        omni_video_model: omniModel,
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
            模型与 API 配置（自动同步至 .env）
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
                <option value="live">Live（强制调用真实 AI 接口）</option>
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

          {/* 1. Gemini API */}
          <div className="space-y-3 rounded-xl border border-studio-border bg-studio-card p-4">
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold uppercase tracking-wider text-indigo-400">
                1. Gemini API（导演 / Omni 1.2 视频 / 关键帧 / 配乐）
              </div>
              <button
                type="button"
                className="studio-btn-secondary py-1 text-[11px]"
                onClick={handleTestGemini}
                disabled={testingGemini}
              >
                {testingGemini ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <PlugZap className="h-3 w-3 text-emerald-400" />
                )}
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
                驱动：Gemini 4 导演/审片、Gemini Omni 1.2 Flash 视频生成与 V2V 改片续写、Nano Banana 2.1 生图、Lyria 3.5 配乐。
              </p>
            </div>
            {geminiTestResult && (
              <div
                className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
                  geminiTestResult.ok
                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
                    : "border-rose-500/30 bg-rose-500/10 text-rose-200"
                }`}
              >
                {geminiTestResult.ok ? (
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                ) : (
                  <XCircle className="h-4 w-4 shrink-0 text-rose-400" />
                )}
                <span>{geminiTestResult.message}</span>
              </div>
            )}
          </div>

          {/* 2. GPT / OpenAI Compatible Image Provider */}
          <div className="space-y-3 rounded-xl border border-studio-border bg-studio-card p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-400">
                <ImageIcon className="h-3.5 w-3.5" />
                2. GPT / OpenAI 兼容生图（角色定妆照 &amp; 三视图）
              </div>
              <button
                type="button"
                className="studio-btn-secondary py-1 text-[11px]"
                onClick={handleTestOpenai}
                disabled={testingOpenai}
              >
                {testingOpenai ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <PlugZap className="h-3 w-3 text-emerald-400" />
                )}
                测试 GPT 接口
              </button>
            </div>

            <div>
              <label className="mb-1 block text-xs text-slate-300">生图引擎分配策略</label>
              <select
                className="studio-input text-xs"
                value={imageProvider}
                onChange={(e) => setImageProvider(e.target.value as ImageProvider)}
              >
                <option value="openai_assets">定妆照 &amp; 三视图用 GPT，分镜关键帧用 Gemini（推荐）</option>
                <option value="openai_all">全部生图（定妆照 + 三视图 + 分镜关键帧）均使用 GPT</option>
                <option value="gemini">全部生图使用 Gemini（Nano Banana 2.1）</option>
              </select>
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs text-slate-300">OPENAI_BASE_URL（支持中转站）</label>
                <input
                  className="studio-input font-mono text-xs"
                  placeholder="https://api.openai.com/v1"
                  value={openaiBaseUrl}
                  onChange={(e) => setOpenaiBaseUrl(e.target.value)}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-300">OPENAI_API_KEY</label>
                <input
                  type="password"
                  className="studio-input font-mono text-xs"
                  placeholder="sk-..."
                  value={openaiApiKey}
                  onChange={(e) => setOpenaiApiKey(e.target.value)}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-300">GPT 生图模型</label>
                <input
                  list="openai-image-models-list"
                  className="studio-input font-mono text-xs"
                  value={openaiImageModel}
                  onChange={(e) => setOpenaiImageModel(e.target.value)}
                />
                <datalist id="openai-image-models-list">
                  {OPENAI_IMAGE_MODELS.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-300">GPT 生图最大并发数 (1-8，超出自动排队)</label>
                <input
                  type="number"
                  min={1}
                  max={8}
                  className="studio-input font-mono text-xs"
                  value={openaiMaxConcurrent}
                  onChange={(e) => setOpenaiMaxConcurrent(Math.max(1, Math.min(8, Number(e.target.value) || 2)))}
                />
              </div>
            </div>

            {openaiTestResult && (
              <div
                className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
                  openaiTestResult.ok
                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
                    : "border-rose-500/30 bg-rose-500/10 text-rose-200"
                }`}
              >
                {openaiTestResult.ok ? (
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                ) : (
                  <XCircle className="h-4 w-4 shrink-0 text-rose-400" />
                )}
                <span>{openaiTestResult.message}</span>
              </div>
            )}
          </div>

          <details className="rounded-xl border border-studio-border bg-studio-card p-4">
            <summary className="cursor-pointer text-xs font-semibold text-slate-300">
              高级选项：Google 模型 ID 与通用并发超时设置
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
                <label className="mb-1 block text-[11px] text-slate-400">Gemini 生图模型 (Nano Banana 2.1)</label>
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
                <label className="mb-1 block text-[11px] text-slate-400">通用任务最大并发 (1-6)</label>
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
                <label className="mb-1 block text-[11px] text-slate-400">视频请求超时(秒)</label>
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
