import React, { useEffect, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  FileText,
  FileUp,
  Layers,
  Sparkles,
  Trash2,
  Wand2,
} from "lucide-react";
import type { Episode, Project } from "../types";

interface NovelTabProps {
  project: Project;
  episodes: Episode[];
  onImportFile: (
    file: File,
    splitMode: "auto_chapter" | "by_length",
    charsPerEpisode: number,
    replaceExisting: boolean
  ) => Promise<void>;
  onImportText: (payload: {
    novel_title: string;
    text: string;
    split_mode: "auto_chapter" | "by_length";
    chars_per_episode: number;
    replace_existing: boolean;
  }) => Promise<void>;
  onUpdateEpisode: (eid: string, patch: Partial<Episode>) => Promise<void>;
  onDeleteEpisode: (eid: string) => Promise<void>;
  onExtractBible: (maxEpisodes: number) => Promise<void>;
  onBreakdownEpisode: (eid: string, targetShots: number, replaceExisting: boolean) => Promise<void>;
  onOpenEpisodeStoryboard: (eid: string) => void;
}

const SAMPLE_NOVEL = `第一章 雨夜来客
九月的暴雨把整座霓虹老街洗得发亮。林澈推开侦探事务所生锈的铁门，风铃发出清脆的声响。
桌上的全息投影仪突然自行启动，一枚淡蓝色的晶体在半空中缓缓旋转，折射出细碎的光斑。
“你终于回来了。”阴影里传来女人的声音。林澈握紧风衣口袋里的怀表，目光锁向窗边那个撑着黑色长伞的身影。

第二章 失落的坐标
“这不是普通的芯片，是十年前沉没的星港核心钥匙。”苏晚将一张泛黄的星图推到林澈面前。
窗外警笛由远及近，红蓝灯光扫过斑驳的百叶窗。林澈看了一眼星图背面的暗纹，低声道：“他们已经追到这里了，从天台走。”
两人冲出走廊，推开通往天台的铁门，整座赛博城市的雨夜天际线在雷光中豁然展开。`;

export const NovelTab: React.FC<NovelTabProps> = ({
  project,
  episodes,
  onImportFile,
  onImportText,
  onUpdateEpisode,
  onDeleteEpisode,
  onExtractBible,
  onBreakdownEpisode,
  onOpenEpisodeStoryboard,
}) => {
  const [splitMode, setSplitMode] = useState<"auto_chapter" | "by_length">("auto_chapter");
  const [charsPerEp, setCharsPerEp] = useState(2000);
  const [replaceExisting, setReplaceExisting] = useState(true);
  const [pasteMode, setPasteMode] = useState(false);
  const [novelTitle, setNovelTitle] = useState(project.novel_title || "未命名小说");
  const [pasteText, setPasteText] = useState("");
  const [importing, setImporting] = useState(false);

  const [selectedEpId, setSelectedEpId] = useState<string | null>(null);
  const selectedEp = episodes.find((e) => e.id === selectedEpId) || episodes[0] || null;

  const [shotCountDraft, setShotCountDraft] = useState(6);
  const [sourceDraft, setSourceDraft] = useState("");

  useEffect(() => {
    if (selectedEp) {
      setSelectedEpId(selectedEp.id);
      setShotCountDraft(selectedEp.target_shots || 6);
      setSourceDraft(selectedEp.source_text);
    }
  }, [selectedEp?.id, selectedEp?.target_shots]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      await onImportFile(file, splitMode, charsPerEp, replaceExisting);
    } finally {
      setImporting(false);
      e.target.value = "";
    }
  };

  const handlePasteSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pasteText.trim().length < 10) return;
    setImporting(true);
    try {
      await onImportText({
        novel_title: novelTitle.trim() || "导入小说",
        text: pasteText,
        split_mode: splitMode,
        chars_per_episode: charsPerEp,
        replace_existing: replaceExisting,
      });
      setPasteMode(false);
      setPasteText("");
    } finally {
      setImporting(false);
    }
  };

  const totalChars = episodes.reduce((acc, e) => acc + e.char_count, 0);

  return (
    <div className="space-y-5 p-5">
      {/* Top Import & Pipeline Bar */}
      <div className="rounded-xl border border-studio-border bg-studio-card p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <BookOpen className="h-4 w-4 text-indigo-400" />
            小说导入与自动拆集引擎（支持 .txt / .md / .docx / .epub）
          </div>
          {episodes.length > 0 && (
            <span className="rounded bg-indigo-500/15 px-2.5 py-0.5 text-xs text-indigo-300">
              《{project.novel_title || project.name}》 · 共 {episodes.length} 集 · {(totalChars / 10000).toFixed(2)} 万字
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="text-slate-400">拆分策略:</span>
            <select
              className="rounded-lg border border-studio-border bg-studio-bg px-2.5 py-1.5 text-xs text-slate-100"
              value={splitMode}
              onChange={(e) => setSplitMode(e.target.value as "auto_chapter" | "by_length")}
            >
              <option value="auto_chapter">智能识别章节标题（超长章自动按段切分）</option>
              <option value="by_length">按固定字数均分（适合无章节标题文本）</option>
            </select>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-slate-400">单集上限字数:</span>
            <input
              type="number"
              min={400}
              max={15000}
              step={200}
              className="w-24 rounded-lg border border-studio-border bg-studio-bg px-2.5 py-1 text-xs text-slate-100"
              value={charsPerEp}
              onChange={(e) => setCharsPerEp(Number(e.target.value) || 2000)}
            />
          </div>

          <label className="flex cursor-pointer items-center gap-1.5 text-slate-300">
            <input
              type="checkbox"
              checked={replaceExisting}
              onChange={(e) => setReplaceExisting(e.target.checked)}
            />
            覆盖已有分集
          </label>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <label className="studio-btn-primary cursor-pointer">
              <FileUp className="h-3.5 w-3.5" />
              {importing ? "解析拆集中..." : "上传整本小说文件"}
              <input
                type="file"
                accept=".txt,.md,.docx,.epub"
                className="hidden"
                disabled={importing}
                onChange={handleFileChange}
              />
            </label>
            <button
              type="button"
              className="studio-btn-secondary"
              onClick={() => setPasteMode((v) => !v)}
            >
              <FileText className="h-3.5 w-3.5" />
              {pasteMode ? "收起粘贴框" : "直接粘贴文本"}
            </button>
          </div>
        </div>

        {pasteMode && (
          <form onSubmit={handlePasteSubmit} className="mt-4 space-y-3 border-t border-studio-border pt-4">
            <div className="flex flex-wrap items-center gap-2">
              <input
                className="studio-input max-w-xs text-xs"
                placeholder="小说标题"
                value={novelTitle}
                onChange={(e) => setNovelTitle(e.target.value)}
              />
              <button
                type="button"
                className="studio-btn-secondary text-[11px]"
                onClick={() => {
                  setNovelTitle("星港雨夜");
                  setPasteText(SAMPLE_NOVEL);
                }}
              >
                填入示例两章小说体验
              </button>
            </div>
            <textarea
              rows={7}
              className="studio-input text-xs leading-relaxed"
              placeholder="在此粘贴整本小说或若干章节文本（自动识别“第一章 / 第二章 / Chapter 1”等标题）..."
              value={pasteText}
              onChange={(e) => setPasteText(e.target.value)}
            />
            <div className="flex justify-end">
              <button type="submit" className="studio-btn-primary" disabled={importing || pasteText.trim().length < 10}>
                立即自动拆分分集
              </button>
            </div>
          </form>
        )}
      </div>

      {/* Step 2: Global Book Bible Action Banner */}
      {episodes.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-indigo-500/35 bg-indigo-950/20 p-4">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2 text-xs font-semibold text-indigo-200">
              <Layers className="h-4 w-4 text-indigo-400" />
              推荐第一步：利用 Gemini 1M 长上下文通读小说，提取「全书统一角色与场景设定」
            </div>
            <p className="text-[11px] text-slate-400">
              提炼完成后将自动写入「资产定妆库」，后续无论拆解第 1 集还是第 50 集，都会自动挂载同一套主角与场景定妆图，确保跨集不崩脸。
            </p>
          </div>
          <button className="studio-btn-primary" onClick={() => onExtractBible(Math.min(30, episodes.length))}>
            <Sparkles className="h-3.5 w-3.5" />
            AI 提取全书角色/场景 (~$0.02)
          </button>
        </div>
      )}

      {/* Episode Split View */}
      {episodes.length === 0 ? (
        <div className="rounded-xl border border-dashed border-studio-border p-12 text-center">
          <BookOpen className="mx-auto mb-2 h-8 w-8 text-slate-600" />
          <p className="text-sm text-slate-300">上传一本小说，一键拆分为多集漫剧/短剧工作流</p>
          <p className="mt-1 text-xs text-slate-500">
            支持 UTF-8 / GBK 中文 TXT、Markdown、Word (.docx) 与 EPUB 电子书；支持按章节自动拆分与按集独立生成分镜。
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
          {/* Left: Episode Directory */}
          <div className="max-h-[540px] space-y-2 overflow-y-auto rounded-xl border border-studio-border bg-studio-card p-3 xl:col-span-4">
            <div className="px-1 text-xs font-semibold text-slate-400">分集目录 ({episodes.length})</div>
            {episodes.map((ep, idx) => {
              const active = selectedEp?.id === ep.id;
              return (
                <div
                  key={ep.id}
                  onClick={() => setSelectedEpId(ep.id)}
                  className={`cursor-pointer rounded-lg border p-3 transition ${
                    active
                      ? "border-indigo-500 bg-indigo-500/15"
                      : "border-studio-border bg-studio-bg hover:border-slate-600"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs font-semibold text-white">
                      {idx + 1}. {ep.title}
                    </span>
                    {ep.shot_count > 0 ? (
                      <span className="inline-flex shrink-0 items-center gap-1 rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] text-emerald-300">
                        <CheckCircle2 className="h-3 w-3" /> {ep.shot_count} 镜
                      </span>
                    ) : (
                      <span className="shrink-0 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                        待拆镜
                      </span>
                    )}
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[11px] text-slate-500">
                    <span>{ep.char_count} 字</span>
                    <span>建议 {ep.target_shots} 镜</span>
                  </div>
                  {ep.summary && <p className="mt-1 line-clamp-2 text-[11px] text-slate-400">{ep.summary}</p>}
                </div>
              );
            })}
          </div>

          {/* Right: Selected Episode Inspector & Breakdown */}
          {selectedEp && (
            <div className="flex flex-col space-y-3 rounded-xl border border-studio-border bg-studio-card p-4 xl:col-span-8">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-studio-border pb-3">
                <input
                  className="w-72 rounded border border-transparent bg-transparent px-1.5 py-0.5 text-sm font-semibold text-white hover:border-studio-border focus:border-indigo-500 focus:bg-studio-bg focus:outline-none"
                  defaultValue={selectedEp.title}
                  key={selectedEp.id + "_title"}
                  onBlur={(e) => {
                    if (e.target.value !== selectedEp.title) {
                      onUpdateEpisode(selectedEp.id, { title: e.target.value });
                    }
                  }}
                />
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex items-center gap-1.5 text-xs">
                    <span className="text-slate-400">拆解目标镜数:</span>
                    <input
                      type="number"
                      min={2}
                      max={24}
                      className="w-16 rounded border border-studio-border bg-studio-bg px-2 py-1 font-mono text-xs text-white"
                      value={shotCountDraft}
                      onChange={(e) => setShotCountDraft(Number(e.target.value) || 6)}
                    />
                  </div>
                  <button
                    className="studio-btn-primary"
                    onClick={() => onBreakdownEpisode(selectedEp.id, shotCountDraft, true)}
                  >
                    <Wand2 className="h-3.5 w-3.5" />
                    AI 拆解本集分镜 (~$0.01)
                  </button>
                  {selectedEp.shot_count > 0 && (
                    <button
                      className="studio-btn-secondary border-emerald-500/40 text-emerald-300"
                      onClick={() => onOpenEpisodeStoryboard(selectedEp.id)}
                    >
                      进入本集分镜板 ({selectedEp.shot_count} 镜)
                      <ArrowRight className="h-3.5 w-3.5" />
                    </button>
                  )}
                  <button
                    className="studio-btn-ghost text-rose-400 hover:text-rose-300"
                    onClick={() => {
                      if (confirm(`确定删除分集「${selectedEp.title}」及其关联分镜？`)) {
                        onDeleteEpisode(selectedEp.id);
                      }
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              {selectedEp.summary && (
                <div className="rounded-lg bg-studio-bg px-3 py-2 text-xs text-slate-300">
                  <span className="font-semibold text-indigo-300">本集梗概（自动衔接下一集）：</span>
                  {selectedEp.summary}
                </div>
              )}

              <div className="flex-1">
                <div className="mb-1 flex items-center justify-between text-[11px] text-slate-400">
                  <span>本集小说原文（可直接在拆镜前微调删减）</span>
                  <span>{sourceDraft.length} 字</span>
                </div>
                <textarea
                  rows={16}
                  className="studio-input h-[380px] resize-y text-xs leading-relaxed"
                  value={sourceDraft}
                  onChange={(e) => setSourceDraft(e.target.value)}
                  onBlur={() => {
                    if (sourceDraft !== selectedEp.source_text) {
                      onUpdateEpisode(selectedEp.id, { source_text: sourceDraft });
                    }
                  }}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
