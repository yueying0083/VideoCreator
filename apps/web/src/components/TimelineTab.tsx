import React, { useEffect, useState } from "react";
import { Download, Film, Music, Scissors, Sparkles, Subtitles, Upload, Volume2 } from "lucide-react";
import type { ExportRecord, Project, Shot } from "../types";

interface TimelineTabProps {
  project: Project;
  shots: Shot[];
  exportsList: ExportRecord[];
  onUpdateProject: (patch: Partial<Project>) => Promise<void>;
  onUpdateShot: (shotId: string, patch: Partial<Shot>) => Promise<void>;
  onGenerateBgm: (prompt: string, mode: "clip" | "pro") => Promise<void>;
  onUploadBgm: (file: File) => Promise<void>;
  onAutoSubtitles: () => Promise<void>;
  onExport: (payload: {
    resolution: "720p" | "1080p" | "4k";
    crossfade_sec: number;
    include_bgm: boolean;
    burn_subtitles: boolean;
  }) => Promise<void>;
}

export const TimelineTab: React.FC<TimelineTabProps> = ({
  project,
  shots,
  exportsList,
  onUpdateProject,
  onUpdateShot,
  onGenerateBgm,
  onUploadBgm,
  onAutoSubtitles,
  onExport,
}) => {
  const [bgmPrompt, setBgmPrompt] = useState(
    project.bgm_prompt || "Cinematic atmospheric underscore, subtle piano and warm synth pads, emotional build"
  );
  const [bgmVol, setBgmVol] = useState(project.bgm_volume);
  const [srtDraft, setSrtDraft] = useState(project.subtitle_srt);
  const [resolution, setResolution] = useState<"720p" | "1080p" | "4k">("1080p");
  const [crossfadeSec, setCrossfadeSec] = useState<number>(0.35);
  const [includeBgm, setIncludeBgm] = useState(true);
  const [burnSubtitles, setBurnSubtitles] = useState(false);

  useEffect(() => {
    setBgmPrompt(
      project.bgm_prompt || "Cinematic atmospheric underscore, subtle piano and warm synth pads, emotional build"
    );
    setBgmVol(project.bgm_volume);
    setSrtDraft(project.subtitle_srt);
  }, [project.id, project.bgm_prompt, project.bgm_volume, project.subtitle_srt]);

  const readyClips = shots
    .map((shot) => {
      const take = shot.takes.find((t) => t.id === shot.selected_take_id) || shot.takes[0] || null;
      return { shot, take };
    })
    .filter((item) => item.take !== null);

  const totalSec = readyClips.reduce((acc, item) => {
    const raw = item.take!.duration_sec;
    const start = item.shot.trim_start || 0;
    const end = item.shot.trim_end && item.shot.trim_end > start ? Math.min(raw, item.shot.trim_end) : raw;
    return acc + Math.max(0.2, end - start);
  }, 0);

  return (
    <div className="space-y-5 p-5">
      {/* Track 1: Video Clips Strip */}
      <div className="rounded-xl border border-studio-border bg-studio-card p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Scissors className="h-4 w-4 text-indigo-400" />
            主视频轨（自动汇集各分镜已锁定 Take）
          </div>
          <span className="font-mono text-xs text-indigo-300">
            已就绪 {readyClips.length}/{shots.length} 镜 · 总时长约 {totalSec.toFixed(1)}s
          </span>
        </div>

        {readyClips.length === 0 ? (
          <div className="rounded-lg border border-dashed border-studio-border p-8 text-center text-xs text-slate-500">
            请先在「分镜故事板」中为镜头生成或导入至少一个视频 Take，即可在此拼接合片。
          </div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-2">
            {readyClips.map(({ shot, take }, idx) => (
              <div
                key={shot.id}
                className="w-60 shrink-0 rounded-lg border border-studio-border bg-studio-bg p-2.5 text-xs"
              >
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="truncate font-medium text-white">
                    #{idx + 1} {shot.title}
                  </span>
                  <span className="font-mono text-[11px] text-slate-400">{take!.duration_sec.toFixed(1)}s</span>
                </div>
                <div className="mb-2 aspect-video overflow-hidden rounded bg-black">
                  {take!.thumbnail_url ? (
                    <img src={take!.thumbnail_url} alt={shot.title} className="h-full w-full object-cover" />
                  ) : (
                    <video src={take!.file_url} className="h-full w-full object-cover" />
                  )}
                </div>
                <div className="grid grid-cols-2 gap-1.5 text-[11px]">
                  <div>
                    <span className="text-slate-500">起剪(s)</span>
                    <input
                      type="number"
                      step="0.2"
                      min="0"
                      max={take!.duration_sec}
                      className="studio-input mt-0.5 py-1 text-xs"
                      defaultValue={shot.trim_start}
                      onBlur={(e) => onUpdateShot(shot.id, { trim_start: Number(e.target.value) || 0 })}
                    />
                  </div>
                  <div>
                    <span className="text-slate-500">止剪(s)</span>
                    <input
                      type="number"
                      step="0.2"
                      min="0"
                      max={take!.duration_sec}
                      placeholder={take!.duration_sec.toFixed(1)}
                      className="studio-input mt-0.5 py-1 text-xs"
                      defaultValue={shot.trim_end ?? ""}
                      onBlur={(e) =>
                        onUpdateShot(shot.id, {
                          trim_end: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Track 2 & 3: BGM (Lyria 3.5) + Subtitles */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="space-y-3 rounded-xl border border-studio-border bg-studio-card p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <Music className="h-4 w-4 text-emerald-400" />
              配乐轨（Lyria 3.5 生成 / 本地导入）
            </div>
            <label className="studio-btn-secondary cursor-pointer text-[11px]">
              <Upload className="h-3 w-3" /> 上传音乐
              <input
                type="file"
                accept="audio/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onUploadBgm(f);
                  e.target.value = "";
                }}
              />
            </label>
          </div>

          <textarea
            rows={2}
            className="studio-input text-xs"
            value={bgmPrompt}
            onChange={(e) => setBgmPrompt(e.target.value)}
            placeholder="输入英文配乐描述（风格、乐器、情绪、BPM）..."
          />

          <div className="flex flex-wrap gap-2">
            <button className="studio-btn-primary" onClick={() => onGenerateBgm(bgmPrompt, "clip")}>
              <Sparkles className="h-3.5 w-3.5" />
              Lyria 3.5 生成主题配乐 (~$0.04)
            </button>
            <button className="studio-btn-secondary" onClick={() => onGenerateBgm(bgmPrompt, "pro")}>
              生成完整长曲 (~$0.08)
            </button>
          </div>

          {project.bgm_url && (
            <div className="space-y-2 rounded-lg bg-studio-bg p-3">
              <audio src={project.bgm_url} controls className="h-9 w-full" />
              <div className="flex items-center gap-3 text-xs text-slate-300">
                <Volume2 className="h-4 w-4 text-emerald-400" />
                <span>混音音量: {Math.round(bgmVol * 100)}%</span>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={bgmVol}
                  onChange={(e) => setBgmVol(Number(e.target.value))}
                  onMouseUp={() => onUpdateProject({ bgm_volume: bgmVol })}
                  className="flex-1 accent-indigo-500"
                />
              </div>
            </div>
          )}
        </div>

        {/* Subtitles */}
        <div className="space-y-3 rounded-xl border border-studio-border bg-studio-card p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <Subtitles className="h-4 w-4 text-sky-400" />
              字幕轨（SRT）
            </div>
            <button className="studio-btn-secondary text-[11px]" onClick={onAutoSubtitles}>
              <Sparkles className="h-3 w-3 text-sky-400" />
              从分镜台词一键生成 SRT
            </button>
          </div>
          <textarea
            rows={6}
            className="studio-input font-mono text-[11px]"
            placeholder={"1\n00:00:00,300 --> 00:00:05,500\n这座城市从不真正入睡。"}
            value={srtDraft}
            onChange={(e) => setSrtDraft(e.target.value)}
            onBlur={() => {
              if (srtDraft !== project.subtitle_srt) {
                onUpdateProject({ subtitle_srt: srtDraft });
              }
            }}
          />
        </div>
      </div>

      {/* Export Controls */}
      <div className="rounded-xl border border-indigo-500/40 bg-indigo-950/20 p-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-4 text-xs text-slate-200">
            <div className="flex items-center gap-2">
              <span className="text-slate-400">分辨率:</span>
              <select
                className="rounded border border-studio-border bg-studio-bg px-2.5 py-1"
                value={resolution}
                onChange={(e) => setResolution(e.target.value as "720p" | "1080p" | "4k")}
              >
                <option value="1080p">1080p Full HD</option>
                <option value="720p">720p 快速预览</option>
                <option value="4k">4K Ultra HD</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-slate-400">转场:</span>
              <select
                className="rounded border border-studio-border bg-studio-bg px-2.5 py-1"
                value={crossfadeSec}
                onChange={(e) => setCrossfadeSec(Number(e.target.value))}
              >
                <option value={0}>0s 硬切（直连）</option>
                <option value={0.35}>0.35s 柔和叠化</option>
                <option value={0.6}>0.6s 慢叠化</option>
                <option value={1.0}>1.0s 长叠化</option>
              </select>
            </div>
            <label className="flex cursor-pointer items-center gap-1.5">
              <input
                type="checkbox"
                checked={includeBgm}
                onChange={(e) => setIncludeBgm(e.target.checked)}
                disabled={!project.bgm_url}
              />
              混入 BGM 配乐
            </label>
            <label className="flex cursor-pointer items-center gap-1.5">
              <input
                type="checkbox"
                checked={burnSubtitles}
                onChange={(e) => setBurnSubtitles(e.target.checked)}
                disabled={!srtDraft.trim()}
              />
              烧录硬字幕
            </label>
          </div>

          <button
            className="studio-btn-primary px-4 py-2 text-xs"
            disabled={readyClips.length === 0}
            onClick={() =>
              onExport({
                resolution,
                crossfade_sec: crossfadeSec,
                include_bgm: includeBgm,
                burn_subtitles: burnSubtitles,
              })
            }
          >
            <Film className="h-4 w-4" />
            本地 FFmpeg 一键合片导出（$0 云费用）
          </button>
        </div>
      </div>

      {/* Export History */}
      {exportsList.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">成片导出记录</h3>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {exportsList.map((exp) => (
              <div key={exp.id} className="rounded-xl border border-studio-border bg-studio-card p-3">
                <video src={exp.file_url} controls className="mb-2 aspect-video w-full rounded bg-black" />
                <div className="flex items-center justify-between text-xs">
                  <div className="text-slate-300">
                    {exp.resolution} · {exp.duration_sec.toFixed(1)}s
                    {exp.crossfade_sec > 0 && ` · 叠化 ${exp.crossfade_sec}s`}
                    {exp.include_bgm && " · 含BGM"}
                    {exp.burn_subtitles && " · 含字幕"}
                  </div>
                  <a
                    href={exp.file_url}
                    download
                    className="studio-btn-secondary py-1 text-[11px]"
                  >
                    <Download className="h-3 w-3" /> 下载 MP4
                  </a>
                </div>
                <div className="mt-1 truncate font-mono text-[10px] text-slate-500" title={exp.local_path}>
                  本地路径: {exp.local_path}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
