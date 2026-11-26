from __future__ import annotations

import html
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import RuntimeSettings, load_settings
from app.services.genai_utils import create_genai_client


class BookBibleAssetItem(BaseModel):
    name: str
    kind: Literal["character", "scene", "prop"] = "character"
    description: str


class EpisodeSummaryItem(BaseModel):
    order_index: int
    summary: str


class BookBibleOutput(BaseModel):
    style_prompt: str
    bgm_prompt: str
    assets: list[BookBibleAssetItem] = Field(default_factory=list)
    episode_summaries: list[EpisodeSummaryItem] = Field(default_factory=list)


class EpisodeShotItem(BaseModel):
    title: str
    shot_type: str = "中景"
    camera_movement: str = "缓慢推进"
    visual_prompt_zh: str
    video_prompt_en: str
    dialogue: str = ""
    dialogue_mode: Literal["spoken", "narration", "none"] = "spoken"
    sfx_prompt: str = ""
    duration_sec: int = Field(default=5, ge=3, le=15)
    asset_names: list[str] = Field(default_factory=list)


class EpisodeBreakdownOutput(BaseModel):
    summary: str
    shots: list[EpisodeShotItem] = Field(default_factory=list)

# Matches common Chinese & English novel chapter headings at the start of a line
CHAPTER_HEADING_RE = re.compile(
    r"^(?:"
    r"(?:第[零一二三四五六七八九十百千万两\d]+[章节回卷集幕部篇](?:[\s：:·\-—]+[^\n]{0,60})?)"
    r"|(?:(?:序章|序言|楔子|引子|前言|尾声|终章|番外)(?:[\s：:·\-—]+[^\n]{0,50})?)"
    r"|(?:Chapter\s+\d+(?:[\s:\-—]+[^\n]{0,60})?)"
    r"|(?:Episode\s+\d+(?:[\s:\-—]+[^\n]{0,60})?)"
    r"|(?:#{1,3}\s+[^\n]{1,60})"
    r")\s*$",
    re.IGNORECASE,
)


def decode_text_bytes(raw: bytes) -> str:
    """Decode Chinese/English novel bytes cleanly across UTF-8, GB18030, GBK, UTF-16."""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_novel_text_from_file(filename: str, raw: bytes) -> str:
    """Extract clean plain text from .txt, .md, .docx, or .epub without heavy external dependencies."""
    lower = (filename or "novel.txt").lower()
    if lower.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs: list[str] = []
        for p in root.findall(".//w:p", ns):
            texts = [t.text for t in p.findall(".//w:t", ns) if t.text]
            line = "".join(texts).strip()
            if line:
                paragraphs.append(line)
        return "\n\n".join(paragraphs)

    if lower.endswith(".epub"):
        chunks: list[str] = []
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            html_names = sorted(
                n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))
            )
            for name in html_names:
                content = decode_text_bytes(zf.read(name))
                # Strip scripts/styles then tags
                content = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", content, flags=re.I | re.S)
                content = re.sub(r"</(p|div|h[1-6]|br|li)>", "\n", content, flags=re.I)
                content = re.sub(r"<[^>]+>", "", content)
                content = html.unescape(content)
                lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
                if lines:
                    chunks.append("\n".join(lines))
        return "\n\n".join(chunks)

    return decode_text_bytes(raw)


def _split_long_text_by_paragraphs(title: str, body: str, max_chars: int) -> list[dict[str, str]]:
    """Split a long block cleanly along paragraph boundaries."""
    body = body.strip()
    if len(body) <= int(max_chars * 1.35):
        return [{"title": title, "source_text": body}]

    paras = [p.strip() for p in re.split(r"\n+", body) if p.strip()]
    parts: list[str] = []
    buf: list[str] = []
    cur_len = 0

    for para in paras:
        if cur_len + len(para) > max_chars and buf:
            parts.append("\n\n".join(buf))
            buf = [para]
            cur_len = len(para)
        else:
            buf.append(para)
            cur_len += len(para)
    if buf:
        parts.append("\n\n".join(buf))

    if len(parts) == 1:
        return [{"title": title, "source_text": parts[0]}]
    return [
        {"title": f"{title}（上/第{i+1}段）" if len(parts) > 2 else f"{title}（{'上' if i == 0 else '下'}）", "source_text": p}
        for i, p in enumerate(parts)
    ]


def split_novel_into_episodes(
    text: str,
    split_mode: str = "auto_chapter",
    chars_per_episode: int = 2000,
) -> list[dict[str, str]]:
    """
    Split raw novel text into episodes.
    - auto_chapter: detects Chinese/English chapter titles; splits oversized chapters cleanly by paragraph.
      Falls back to by_length if fewer than 2 headings are detected.
    - by_length: ignores headings and chunks cleanly by paragraph near chars_per_episode.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    if split_mode == "auto_chapter":
        lines = normalized.split("\n")
        sections: list[tuple[str, list[str]]] = []
        current_title: str | None = None
        current_lines: list[str] = []
        preface_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped and len(stripped) <= 64 and CHAPTER_HEADING_RE.match(stripped):
                heading = stripped.lstrip("#").strip()
                if current_title is not None:
                    sections.append((current_title, current_lines))
                elif preface_lines and len("".join(preface_lines).strip()) >= 80:
                    sections.append(("序幕 / 引子", preface_lines))
                current_title = heading
                current_lines = []
            else:
                if current_title is None:
                    preface_lines.append(line)
                else:
                    current_lines.append(line)

        if current_title is not None:
            sections.append((current_title, current_lines))

        if len(sections) >= 1:
            episodes: list[dict[str, str]] = []
            for sec_title, sec_lines in sections:
                sec_body = "\n".join(sec_lines).strip()
                if not sec_body:
                    continue
                episodes.extend(_split_long_text_by_paragraphs(sec_title, sec_body, chars_per_episode))
            if episodes:
                return episodes

    # Fallback or explicit by_length mode
    paras = [p.strip() for p in re.split(r"\n+", normalized) if p.strip()]
    episodes = []
    buf: list[str] = []
    cur_len = 0
    ep_num = 1
    for para in paras:
        if cur_len + len(para) > chars_per_episode and buf:
            episodes.append({"title": f"第 {ep_num} 集", "source_text": "\n\n".join(buf)})
            ep_num += 1
            buf = [para]
            cur_len = len(para)
        else:
            buf.append(para)
            cur_len += len(para)
    if buf:
        episodes.append({"title": f"第 {ep_num} 集", "source_text": "\n\n".join(buf)})
    return episodes


BOOK_BIBLE_SYSTEM_PROMPT = """你是一位顶级漫剧/影视改编制片人与美术总监。
你将阅读一部小说的完整或核心章节文本，请你提取整部作品需要跨集保持高度一致性的「全局视觉设定集（Book Bible）」。
严格返回如下 JSON（不要附加任何多余说明）：
{
  "style_prompt": "全剧统一视觉基调（中文，描述画风、色调、光影、镜头质感）",
  "bgm_prompt": "全剧主题配乐的英文 Lyria 3 提示词",
  "assets": [
    {
      "name": "简短清晰的角色/场景/关键道具名（不含特殊符号）",
      "kind": "character" 或 "scene" 或 "prop",
      "description": "极度具体的中文外貌/服装/建筑/材质设定（供 AI 生图模型绘制单主体定妆照与三视图，确保第1集到第50集外观不跑偏）。重要：每个资产只写一套唯一固定的主要服装与平静神态，不要写“前期穿A、后期穿B”或“在表情A与B之间切换”"
    }
  ],
  "episode_summaries": [
    {"order_index": 0, "summary": "该集 50 字以内的核心剧情梗概"}
  ]
}
要求：角色提取核心人物（3~8位），场景提取高频核心地点（2~6个），关键道具（1~3个）。"""


def extract_book_bible(
    novel_title: str,
    episodes: list[dict[str, Any]],
    settings: RuntimeSettings | None = None,
) -> tuple[dict[str, Any], str, bool]:
    """Use Gemini's 1M long-context window to extract global Characters/Scenes/Props across the novel."""
    cfg = settings or load_settings()
    if cfg.effective_mode == "demo":
        # Extract candidate names/snippets deterministically from the imported novel text
        sample_text = "\n".join(e["source_text"][:500] for e in episodes[:3])
        snippet = sample_text.replace("\n", " ")[:60]
        return (
            {
                "style_prompt": f"《{novel_title}》专属电影级改编画风：细腻体积光、高对比度叙事光影、35mm 电影景深与高一致性人物建模",
                "bgm_prompt": "Emotional cinematic film score with warm strings, subtle piano motif and atmospheric percussion, 92 BPM",
                "assets": [
                    {
                        "name": "主角（小说核心人物）",
                        "kind": "character",
                        "description": f"基于《{novel_title}》原文提炼的核心主角形象，五官立体辨识度高，服装细节统一，适配跨集连续出镜（Demo 演示设定，接入 GEMINI_API_KEY 后将自动精准读完整本小说提炼所有真实角色名与外貌）",
                    },
                    {
                        "name": "核心故事主场景",
                        "kind": "scene",
                        "description": f"《{novel_title}》核心开篇与高频场景：{snippet}...",
                    },
                    {
                        "name": "关键线索道具",
                        "kind": "prop",
                        "description": "贯穿剧情的核心信物/道具，高细节写实材质，带电影级微距光泽",
                    },
                ],
                "episode_summaries": [
                    {
                        "order_index": e["order_index"],
                        "summary": f"本集（{e['title']}）约 {len(e['source_text'])} 字：{e['source_text'].strip().replace(chr(10), ' ')[:55]}...",
                    }
                    for e in episodes
                ],
            },
            "demo-bible",
            True,
        )

    client = create_genai_client(cfg, timeout_seconds=180)
    # Concatenate chapters up to ~280,000 chars (well within Gemini 4 1M token window!)
    parts: list[str] = [f"小说名称：《{novel_title}》\n"]
    total_chars = 0
    for ep in episodes:
        chunk = f"\n=== [order_index={ep['order_index']}] {ep['title']} ===\n{ep['source_text']}\n"
        if total_chars + len(chunk) > 280000:
            break
        parts.append(chunk)
        total_chars += len(chunk)

    interaction = client.interactions.create(
        model=cfg.text_model,
        system_instruction=BOOK_BIBLE_SYSTEM_PROMPT,
        input="".join(parts),
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": BookBibleOutput.model_json_schema(),
        },
        store=False,
    )
    raw = (interaction.output_text or "{}").strip()
    try:
        parsed = BookBibleOutput.model_validate_json(raw).model_dump()
    except Exception:
        parsed = json.loads(raw)
    return parsed, cfg.text_model, False


EPISODE_BREAKDOWN_SYSTEM_PROMPT = """你是一位擅长把网文/小说改编为高质量 AI 短剧的分镜导演。
你会收到：
1. 全局角色/场景/道具资产设定（必须严格使用资产清单中的准确名称，以便系统自动挂载定妆图保持角色不崩！）
2. 上一集剧情衔接摘要（如有）
3. 本集小说原文与目标镜头数

请严格遵守以下 AI 视频工业级分镜铁律（严禁把多场戏、多动作塞进同一镜），输出 JSON：
1. **一镜一事（Atomic Single-Beat Rule）**：
   - 每个镜头默认 4~6 秒（仅纯空镜/慢建立镜头可用 7~8 秒）；
   - 每个镜头**严格只包含 1 个固定空间/场景、1 个核心主体动作、1 种简单运镜**；
   - **严禁在同一镜头内**出现室内外跨越（如“在屋内说完再走出门进入走廊”）、时间跳跃、物体瞬移或 2 个以上戏剧转折——必须拆成连续的 2~3 个镜头（例如：镜A 屋内对话 → 镜B 推门背影 → 镜C 门外暗影变脸）！
2. **单镜资产上限**：每镜 `asset_names` 严格控制在 **1~3 个**当下真正入画的核心资产（通常为 1 个场景 + 1~2 个焦点人物/关键道具），不要把所有出场人都堆在同一个镜头里。
3. **区分「角色开口说」与「画外旁白/心理」**：
   - `dialogue_mode`:
     - `"spoken"`：仅当镜头画面里某位角色明确张嘴说短台词（严格 ≤ 12 个汉字，确保 5 秒内能说完）；
     - `"narration"`：用于旁白解说、心理活动、环境交代（不让画面中角色开口），此时 `video_prompt_en` 必须明确包含 `"No spoken dialogue, mouth closed, no on-screen subtitles"`；
     - `"none"`：纯动作或氛围空镜（`dialogue` 留空），`video_prompt_en` 也写 `"No spoken dialogue, no on-screen subtitles"`。
4. **`video_prompt_en` 规范**：
   - 必须以 `"Continuous, unbroken single shot, no scene cuts."` 开头；
   - 先用清晰英文描述 t=0s 开场画面构图（方便 GPT Image 先生成单张干净首帧），再写单一连贯微动作、运镜、光影与纯英文同期环境音；
   - 严禁使用 `<FIRST_FRAME>`、`<IMAGE_REF_1>` 等已废弃 XML 标签。"""


def breakdown_episode_to_shots(
    episode_title: str,
    episode_text: str,
    prev_summary: str,
    project_style: str,
    assets: list[dict[str, str]],
    target_shots: int = 10,
    settings: RuntimeSettings | None = None,
) -> tuple[dict[str, Any], str, bool]:
    cfg = settings or load_settings()
    if cfg.effective_mode == "demo":
        paras = [p.strip() for p in re.split(r"\n+", episode_text) if p.strip()]
        if not paras:
            paras = [episode_title]
        asset_names = [a["name"] for a in assets[:2]]
        shot_types = ["远景", "中景", "中近景", "特写", "全景", "近景"]
        cam_moves = ["缓慢推进", "侧面跟拍", "横摇", "缓慢拉远", "俯拍航拍", "固定机位"]
        shots: list[dict[str, Any]] = []
        for i in range(target_shots):
            p_idx = min(len(paras) - 1, int(i * len(paras) / max(1, target_shots)))
            excerpt = paras[p_idx][:75]
            st = shot_types[i % len(shot_types)]
            cm = cam_moves[i % len(cam_moves)]
            has_narration = i % 2 == 0
            shots.append(
                {
                    "title": f"{episode_title} · 镜{i + 1}",
                    "shot_type": st,
                    "camera_movement": cm,
                    "visual_prompt_zh": f"【改编自原文】{excerpt}",
                    "video_prompt_en": (
                        f"Continuous, unbroken single shot, no scene cuts. Cinematic {st} shot with {cm}, adapting single beat from '{episode_title}': "
                        f"expressive storytelling lighting, rich atmosphere, smooth motion, synchronized ambient audio, no spoken dialogue, no on-screen subtitles, 35mm film look."
                    ),
                    "dialogue": excerpt[:18] if has_narration else "",
                    "dialogue_mode": "narration" if has_narration else "none",
                    "sfx_prompt": "沉浸式场景环境音、自然动作拟音",
                    "duration_sec": 5,
                    "asset_names": asset_names,
                }
            )
        return (
            {
                "summary": f"{episode_title} 改编分镜（共 {target_shots} 镜）：{paras[0][:50]}...",
                "shots": shots,
            },
            "demo-episode-breakdown",
            True,
        )

    client = create_genai_client(cfg, timeout_seconds=180)
    payload_text = (
        f"全剧画风：{project_style}\n"
        f"全局资产库（asset_names 必须从以下 name 中精确挑选，单镜最多选 1~3 个核心资产）：\n"
        f"{json.dumps(assets, ensure_ascii=False, indent=2)}\n\n"
        f"上一集剧情衔接摘要：{prev_summary or '（本集为开篇第一集）'}\n"
        f"目标分镜数：约 {target_shots} 个镜头（每镜 4~6 秒，一镜一事单场景单动作，绝不在一镜内跨场景转场）\n\n"
        f"=== 本集标题：{episode_title} ===\n"
        f"{episode_text[:30000]}"
    )

    interaction = client.interactions.create(
        model=cfg.text_model,
        system_instruction=EPISODE_BREAKDOWN_SYSTEM_PROMPT,
        input=payload_text,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": EpisodeBreakdownOutput.model_json_schema(),
        },
        store=False,
    )
    raw = (interaction.output_text or "{}").strip()
    try:
        parsed = EpisodeBreakdownOutput.model_validate_json(raw).model_dump()
    except Exception:
        parsed = json.loads(raw)
    return parsed, cfg.text_model, False
