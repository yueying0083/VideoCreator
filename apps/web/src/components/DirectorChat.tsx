import React, { useEffect, useRef, useState } from "react";
import { Bot, Check, Film, Loader2, Send, Sparkles, User, Wand2 } from "lucide-react";
import type { Asset, ChatMessage } from "../types";

interface DirectorChatProps {
  messages: ChatMessage[];
  assets: Asset[];
  sending: boolean;
  onSend: (text: string) => Promise<void>;
  onApplyProposal: (messageId: string) => Promise<void>;
}

const STARTER_IDEAS = [
  "做一个 18 秒赛博雨夜短片：青年侦探在霓虹巷口发现悬浮微光体，3 个电影感镜头",
  "帮我策划一个极简高端咖啡机 3 镜头产品广告，微距特写蒸汽与拉花",
  "治愈系宫崎骏风动画短片：橘猫在海边车站等待电车驶来，3 个连贯镜头",
];

export const DirectorChat: React.FC<DirectorChatProps> = ({
  messages,
  assets,
  sending,
  onSend,
  onApplyProposal,
}) => {
  const [input, setInput] = useState("");
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, sending]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || sending) return;
    const text = input.trim();
    setInput("");
    await onSend(text);
  };

  const handleApply = async (mid: string) => {
    setApplyingId(mid);
    try {
      await onApplyProposal(mid);
    } finally {
      setApplyingId(null);
    }
  };

  return (
    <aside className="flex w-[360px] shrink-0 flex-col border-r border-studio-border bg-studio-panel lg:w-[400px]">
      <div className="flex items-center justify-between border-b border-studio-border px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-white">
          <Bot className="h-4 w-4 text-indigo-400" />
          AI 导演工作台
        </div>
        <span className="rounded bg-indigo-500/15 px-2 py-0.5 text-[11px] text-indigo-300">
          人机确认防烧钱
        </span>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="space-y-3 rounded-xl border border-dashed border-studio-border bg-studio-card/50 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-200">
              <Sparkles className="h-4 w-4 text-indigo-400" />
              一句话开启你的 AI 短片
            </div>
            <p className="text-xs leading-relaxed text-slate-400">
              告诉我你想拍的主题、风格、角色或脚本。我会先为你拆解角色定妆档案与结构化分镜提案，经你确认后再写入分镜板，绝不擅自扣费出视频。
            </p>
            <div className="space-y-1.5 pt-1">
              <div className="text-[11px] font-medium text-slate-500">快捷灵感示例：</div>
              {STARTER_IDEAS.map((idea) => (
                <button
                  key={idea}
                  disabled={sending}
                  onClick={() => onSend(idea)}
                  className="block w-full rounded-lg border border-studio-border bg-studio-bg px-3 py-2 text-left text-xs text-slate-300 transition hover:border-indigo-500/60 hover:text-white"
                >
                  {idea}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`flex flex-col gap-2 ${m.role === "user" ? "items-end" : "items-start"}`}>
            <div
              className={`max-w-[92%] rounded-xl px-3.5 py-2.5 text-xs leading-relaxed ${
                m.role === "user"
                  ? "bg-indigo-600 text-white"
                  : "border border-studio-border bg-studio-card text-slate-200"
              }`}
            >
              <div className="mb-1 flex items-center gap-1.5 text-[10px] opacity-70">
                {m.role === "user" ? <User className="h-3 w-3" /> : <Bot className="h-3 w-3 text-indigo-400" />}
                {m.role === "user" ? "你" : "总导演 Agent"}
              </div>
              <div className="whitespace-pre-wrap">{m.content}</div>
            </div>

            {m.proposal && (
              <div className="w-full rounded-xl border border-indigo-500/40 bg-indigo-950/25 p-3 text-xs">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 font-semibold text-indigo-300">
                    <Film className="h-3.5 w-3.5" />
                    {m.proposal.title || "导演分镜提案"}
                  </span>
                  {m.proposal_applied ? (
                    <span className="inline-flex items-center gap-1 rounded bg-emerald-500/20 px-2 py-0.5 text-[11px] text-emerald-300">
                      <Check className="h-3 w-3" /> 已应用
                    </span>
                  ) : (
                    <button
                      className="studio-btn-primary py-1 text-[11px]"
                      disabled={applyingId === m.id}
                      onClick={() => handleApply(m.id)}
                    >
                      {applyingId === m.id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Wand2 className="h-3 w-3" />
                      )}
                      应用到分镜板
                    </button>
                  )}
                </div>

                {m.proposal.assets && m.proposal.assets.length > 0 && (
                  <div className="mb-2 flex flex-wrap gap-1">
                    {m.proposal.assets.map((a, idx) => (
                      <span
                        key={idx}
                        className="rounded bg-slate-800 px-2 py-0.5 text-[11px] text-slate-300"
                      >
                        @{a.name} ({a.kind})
                      </span>
                    ))}
                  </div>
                )}

                {m.proposal.shots && m.proposal.shots.length > 0 && (
                  <div className="space-y-1.5">
                    {m.proposal.shots.map((s, idx) => (
                      <div key={idx} className="rounded-lg bg-studio-bg/80 p-2 text-[11px]">
                        <div className="flex items-center justify-between font-medium text-slate-200">
                          <span>
                            #{idx + 1} {s.title}
                          </span>
                          <span className="text-slate-400">
                            {s.shot_type} · {s.camera_movement} · {s.duration_sec || 6}s
                          </span>
                        </div>
                        <p className="mt-0.5 line-clamp-2 text-slate-400">{s.visual_prompt_zh}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}

        {sending && (
          <div className="flex items-center gap-2 text-xs text-indigo-300">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            导演 Agent 正在构思分镜与提示词...
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="border-t border-studio-border p-3">
        {assets.length > 0 && (
          <div className="mb-2 flex flex-wrap items-center gap-1">
            <span className="text-[10px] text-slate-500">引用资产:</span>
            {assets.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => setInput((prev) => `${prev}${prev ? " " : ""}@${a.name} `)}
                className="rounded bg-studio-card px-1.5 py-0.5 text-[11px] text-indigo-300 hover:bg-indigo-500/20"
              >
                @{a.name}
              </button>
            ))}
          </div>
        )}
        <form onSubmit={handleSubmit} className="flex gap-2">
          <textarea
            rows={2}
            className="studio-input resize-none text-xs"
            placeholder="输入创意、脚本或修改指令（如：把第2镜改成逆光特写）..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
          />
          <button
            type="submit"
            disabled={sending || !input.trim()}
            className="studio-btn-primary h-auto self-stretch px-3"
          >
            <Send className="h-4 w-4" />
          </button>
        </form>
      </div>
    </aside>
  );
};
