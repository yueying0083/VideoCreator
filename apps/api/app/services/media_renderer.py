from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence


def get_ffmpeg_bin() -> str | None:
    system_bin = shutil.which("ffmpeg")
    if system_bin:
        return system_bin
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def get_ffprobe_bin() -> str | None:
    return shutil.which("ffprobe")


def aspect_to_dimensions(aspect_ratio: str, resolution: str = "1080p") -> tuple[int, int]:
    res = (resolution or "1080p").lower()
    base = {
        "360p": (640, 360),
        "720p": (1280, 720),
        "1080p": (1920, 1080),
        "4k": (3840, 2160),
    }
    w, h = base.get(res, (1920, 1080))
    if aspect_ratio == "9:16":
        return (h, w)
    if aspect_ratio == "1:1":
        square = {
            "360p": 360,
            "720p": 720,
            "1080p": 1080,
            "4k": 2160,
        }.get(res, 1080)
        return (square, square)
    return (w, h)


def _parse_fps(fps_str: str | None) -> str | None:
    if not fps_str:
        return None
    if "/" in fps_str:
        try:
            num, den = map(float, fps_str.split("/"))
            if den != 0:
                val = num / den
                return f"{int(val)} fps" if val.is_integer() else f"{val:.2f} fps"
        except (ValueError, ZeroDivisionError):
            return None
    try:
        val = float(fps_str)
        return f"{int(val)} fps" if val.is_integer() else f"{val:.2f} fps"
    except ValueError:
        return fps_str


def probe_media_info(video_path: Path) -> tuple[float, bool]:
    """Return (duration_sec, has_audio_stream) using ffmpeg -i."""
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg or not video_path.exists():
        return 6.0, False
    proc = subprocess.run(
        [ffmpeg, "-i", str(video_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    stderr = proc.stderr or ""
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    duration = 6.0
    if dur_match:
        h, m, s = int(dur_match.group(1)), int(dur_match.group(2)), float(dur_match.group(3))
        duration = round(h * 3600 + m * 60 + s, 2)
    has_audio = bool(re.search(r"Stream #\d+:\d+.*:\s*Audio:", stderr))
    return duration, has_audio


def inspect_media(file_path: str | Path) -> dict[str, Any]:
    """Inspect image or video metadata using ffprobe (with ffmpeg/Pillow fallback)."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")

    size_bytes = path.stat().st_size
    info: dict[str, Any] = {
        "size_bytes": size_bytes,
        "width": None,
        "height": None,
        "duration_seconds": None,
        "fps": None,
        "has_audio": False,
        "has_video": False,
    }

    ffprobe = get_ffprobe_bin()
    if ffprobe:
        cmd = [
            ffprobe,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode == 0:
            try:
                data = json.loads(proc.stdout)
                fmt = data.get("format", {})
                raw_dur = fmt.get("duration")
                if raw_dur is not None:
                    try:
                        info["duration_seconds"] = round(float(raw_dur), 3)
                    except (TypeError, ValueError):
                        pass

                streams = data.get("streams", [])
                video_streams = [s for s in streams if s.get("codec_type") == "video"]
                audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
                info["has_video"] = len(video_streams) > 0
                info["has_audio"] = len(audio_streams) > 0

                if video_streams:
                    vs = video_streams[0]
                    info["width"] = vs.get("width")
                    info["height"] = vs.get("height")
                    fps = _parse_fps(vs.get("r_frame_rate"))
                    if not fps or fps == "0 fps":
                        fps = _parse_fps(vs.get("avg_frame_rate"))
                    info["fps"] = fps
                    if info["duration_seconds"] is None and vs.get("duration"):
                        try:
                            info["duration_seconds"] = round(float(vs["duration"]), 3)
                        except (TypeError, ValueError):
                            pass
                return info
            except json.JSONDecodeError:
                pass

    # Fallback when ffprobe is absent (e.g. imageio-ffmpeg only)
    ext = path.suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        try:
            from PIL import Image

            with Image.open(path) as im:
                info["width"], info["height"] = im.size
                info["has_video"] = True
        except Exception:
            pass
        return info

    ffmpeg = get_ffmpeg_bin()
    if ffmpeg:
        proc = subprocess.run(
            [ffmpeg, "-i", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        stderr = proc.stderr or ""
        dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
        if dur_match:
            h, m, s = int(dur_match.group(1)), int(dur_match.group(2)), float(dur_match.group(3))
            info["duration_seconds"] = round(h * 3600 + m * 60 + s, 3)
        res_match = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", stderr)
        if res_match:
            info["width"] = int(res_match.group(1))
            info["height"] = int(res_match.group(2))
            info["has_video"] = True
        fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", stderr)
        if fps_match:
            info["fps"] = f"{fps_match.group(1)} fps"
        info["has_audio"] = bool(re.search(r"Stream #\d+:\d+.*:\s*Audio:", stderr))
    return info


def generate_thumbnail(src_path: str | Path, out_path: str | Path, kind: str = "video") -> Path | None:
    """Create a lightweight 480px JPEG thumbnail for fast gallery rendering."""
    src = Path(src_path)
    dst = Path(out_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = get_ffmpeg_bin()

    if kind == "video":
        if not ffmpeg:
            return None
        cmd = [
            ffmpeg, "-y", "-ss", "0.2", "-i", str(src),
            "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(dst),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
            cmd_fallback = [
                ffmpeg, "-y", "-i", str(src),
                "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(dst),
            ]
            proc2 = subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if proc2.returncode != 0 or not dst.exists():
                return None
        return dst

    if ffmpeg:
        cmd = [
            ffmpeg, "-y", "-i", str(src),
            "-vf", "scale='min(480,iw)':-2", "-q:v", "4", str(dst),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode == 0 and dst.exists():
            return dst

    try:
        from PIL import Image

        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((480, 480))
            im.save(dst, format="JPEG", quality=85)
        return dst
    except Exception:
        return None


def extract_video_frame(
    video_path: str | Path,
    out_path: str | Path,
    position: str = "last",
    timestamp_seconds: float | None = None,
) -> Path:
    """Extract first, last, or custom-timestamp PNG frame from a video."""
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("未检测到 FFmpeg，无法抽取视频帧。")
    src = Path(video_path)
    dst = Path(out_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if position == "first":
        cmd = [ffmpeg, "-y", "-i", str(src), "-frames:v", "1", str(dst)]
    elif position == "custom" and timestamp_seconds is not None:
        cmd = [
            ffmpeg, "-y", "-ss", f"{max(0.0, float(timestamp_seconds)):.3f}",
            "-i", str(src), "-frames:v", "1", str(dst),
        ]
    else:
        cmd = [
            ffmpeg, "-y", "-sseof", "-0.12",
            "-i", str(src), "-update", "1", "-frames:v", "1", str(dst),
        ]

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        fallback = [ffmpeg, "-y", "-i", str(src), "-frames:v", "1", str(dst)]
        proc2 = subprocess.run(fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc2.returncode != 0 or not dst.exists():
            raise RuntimeError(f"FFmpeg 抽帧失败：{proc.stderr[-300:]}")
    return dst


def strip_audio_fast(input_path: str | Path, output_path: str | Path) -> Path:
    """Stream-copy video while removing all audio tracks (for full audio regeneration in Omni Flash)."""
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("未检测到 FFmpeg，无法剥离音轨。")
    dst = Path(output_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-i", str(input_path), "-c:v", "copy", "-an", str(dst)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg 剥离音轨失败：{proc.stderr[-300:]}")
    return dst


def prep_video_clip(
    input_path: str | Path,
    output_path: str | Path,
    *,
    start_seconds: float = 0.0,
    duration: int = 10,
    max_edge: int = 1280,
    strip_audio: bool = False,
    fps: int | None = None,
) -> dict[str, Any]:
    """Trim, proportionally scale, and re-encode a video for optimal Gemini Omni Flash upload."""
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("未检测到 FFmpeg，无法裁剪优化视频。")
    src = Path(input_path)
    dst = Path(output_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    info = inspect_media(src)
    orig_w = info.get("width")
    orig_h = info.get("height")
    scale_filter: str | None = None

    if orig_w and orig_h:
        if orig_w >= orig_h:
            target_w, target_h = max_edge, int(max_edge * 9 / 16)
        else:
            target_w, target_h = int(max_edge * 9 / 16), max_edge
        factor = min(1.0, target_w / orig_w, target_h / orig_h)
        if factor < 1.0:
            new_w = max(2, (int(orig_w * factor) // 2) * 2)
            new_h = max(2, (int(orig_h * factor) // 2) * 2)
            scale_filter = f"scale={new_w}:{new_h}"

    cmd = [
        ffmpeg, "-y",
        "-ss", f"{max(0.0, float(start_seconds)):.3f}",
        "-i", str(src),
        "-t", str(int(duration)),
    ]
    if scale_filter:
        cmd.extend(["-vf", scale_filter])

    cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p"])
    if fps:
        cmd.extend(["-r", str(int(fps))])

    if strip_audio or not info.get("has_audio", False):
        cmd.append("-an")
    else:
        cmd.extend(["-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000"])

    cmd.extend(["-movflags", "+faststart", str(dst)])
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg 裁剪优化失败：{proc.stderr[-300:]}")
    return inspect_media(dst)


def extract_frame(video_path: Path, output_image_path: Path, at_end: bool = False) -> bool:
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg or not video_path.exists():
        return False
    output_image_path.parent.mkdir(parents=True, exist_ok=True)
    if at_end:
        duration, _ = probe_media_info(video_path)
        seek_pos = max(0.0, duration - 0.15)
        cmd = [
            ffmpeg, "-y",
            "-ss", f"{seek_pos:.2f}",
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(output_image_path),
        ]
    else:
        cmd = [
            ffmpeg, "-y",
            "-ss", "0.1",
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(output_image_path),
        ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return res.returncode == 0 and output_image_path.exists()


def generate_demo_video(
    output_path: Path,
    image_path: Path,
    duration_sec: int = 4,
    aspect_ratio: str = "16:9",
    with_audio: bool = True,
) -> Path:
    """Create a real playable MP4 from a keyframe image with smooth Ken Burns zoom + optional ambient tone."""
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("未找到 FFmpeg（请安装系统 FFmpeg 或确保 imageio-ffmpeg 可用）")

    w, h = aspect_to_dimensions(aspect_ratio, "720p")
    fps = 24
    total_frames = max(24, duration_sec * fps)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    zoom_filter = (
        f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,"
        f"crop={w*2}:{h*2},"
        f"zoompan=z='min(zoom+0.0012,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={w}x{h}:fps={fps},"
        f"format=yuv420p"
    )

    cmd = [ffmpeg, "-y", "-loop", "1", "-i", str(image_path)]
    if with_audio:
        # Soft cinematic ambient drone tone
        cmd += [
            "-f", "lavfi",
            "-i", f"aevalsrc=0.05*sin(2*PI*220*t)+0.03*sin(2*PI*330*t):d={duration_sec}:s=44100",
        ]
    cmd += ["-vf", zoom_filter, "-t", str(duration_sec), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if with_audio:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    else:
        cmd += ["-an"]
    cmd.append(str(output_path))

    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if res.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"FFmpeg 生成演示视频失败: {res.stderr[-400:]}")
    return output_path


def generate_demo_music(output_path: Path, duration_sec: int = 16) -> Path:
    """Synthesize a pleasant ambient chord progression MP3 via FFmpeg for Demo Mode."""
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("未找到 FFmpeg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    expr = (
        "0.08*sin(2*PI*261.63*t)*sin(2*PI*0.25*t)+"
        "0.06*sin(2*PI*329.63*t)+"
        "0.05*sin(2*PI*392.00*t)*cos(2*PI*0.125*t)+"
        "0.04*sin(2*PI*523.25*t)"
    )
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", f"aevalsrc={expr}:d={duration_sec}:s=44100",
        "-af", f"afade=t=in:st=0:d=1.2,afade=t=out:st={max(1, duration_sec - 2)}:d=2",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        str(output_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if res.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"FFmpeg 生成演示配乐失败: {res.stderr[-400:]}")
    return output_path


def _escape_ffmpeg_sub_path(path: Path) -> str:
    # FFmpeg subtitles filter on Windows requires forward slashes and escaped colon
    s = path.resolve().as_posix()
    s = s.replace(":", "\\:")
    s = s.replace("'", "\\'")
    return s


def render_timeline_export(
    clips: Sequence[dict],
    output_path: Path,
    aspect_ratio: str = "16:9",
    resolution: str = "1080p",
    bgm_path: Path | None = None,
    bgm_volume: float = 0.25,
    subtitle_srt: str = "",
    crossfade_sec: float = 0.0,
) -> float:
    """
    Concatenate shot clips with normalization, optional xfade/acrossfade transition, BGM mixing, and SRT burn-in.
    Each clip dict: {"path": Path, "trim_start": float, "trim_end": float | None, "duration_sec": float, "has_audio": bool}
    Returns final exported duration in seconds.
    """
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("未找到 FFmpeg，无法合片导出")
    if not clips:
        raise ValueError("时间线上没有已选中的镜头视频，请先为至少一个镜头生成或导入视频并锁定 Take")

    w, h = aspect_to_dimensions(aspect_ratio, resolution)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    clip_meta: list[tuple[Path, float, float, bool]] = []
    for clip in clips:
        clip_path: Path = clip["path"]
        raw_dur, detected_audio = probe_media_info(clip_path)
        t_start = max(0.0, float(clip.get("trim_start") or 0.0))
        t_end_raw = clip.get("trim_end")
        t_end = float(t_end_raw) if (t_end_raw is not None and float(t_end_raw) > t_start) else raw_dur
        t_end = min(raw_dur, t_end)
        seg_dur = max(0.2, t_end - t_start)
        clip_meta.append((clip_path, t_start, seg_dur, detected_audio))

    n = len(clip_meta)
    durations = [m[2] for m in clip_meta]
    use_xfade = crossfade_sec > 0.05 and n >= 2 and min(durations) > (crossfade_sec * 2 + 0.4)

    def _run_export(enable_xfade: bool) -> bool:
        cmd: list[str] = [ffmpeg, "-y"]
        filter_parts: list[str] = []
        concat_inputs: list[str] = []

        for idx, (clip_path, t_start, seg_dur, detected_audio) in enumerate(clip_meta):
            cmd += ["-ss", f"{t_start:.3f}", "-t", f"{seg_dur:.3f}", "-i", str(clip_path)]
            filter_parts.append(
                f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=24,format=yuv420p,setpts=PTS-STARTPTS[v{idx}]"
            )
            if detected_audio:
                filter_parts.append(
                    f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                    f"aresample=async=1,asetpts=PTS-STARTPTS[a{idx}]"
                )
            else:
                filter_parts.append(
                    f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration={seg_dur:.3f},asetpts=PTS-STARTPTS[a{idx}]"
                )
            concat_inputs.append(f"[v{idx}][a{idx}]")

        if enable_xfade:
            fade = round(float(crossfade_sec), 2)
            prev_v = "v0"
            prev_a = "a0"
            offset = durations[0] - fade
            for i in range(1, n):
                out_v = f"xv{i}" if i < n - 1 else "vcat"
                out_a = f"xa{i}" if i < n - 1 else "acat"
                filter_parts.append(
                    f"[{prev_v}][v{i}]xfade=transition=fade:duration={fade}:offset={max(0.1, offset):.3f}[{out_v}]"
                )
                filter_parts.append(
                    f"[{prev_a}][a{i}]acrossfade=d={fade}:c1=tri:c2=tri[{out_a}]"
                )
                prev_v = out_v
                prev_a = out_a
                offset += durations[i] - fade
            total_duration = max(0.5, sum(durations) - fade * (n - 1))
        else:
            filter_parts.append(f"{''.join(concat_inputs)}concat=n={n}:v=1:a=1[vcat][acat]")
            total_duration = sum(durations)

        video_label = "[vcat]"
        audio_label = "[acat]"

        if bgm_path and bgm_path.exists():
            bgm_idx = n
            cmd += ["-stream_loop", "-1", "-i", str(bgm_path)]
            fade_out_start = max(0.0, total_duration - 1.5)
            vol = max(0.0, min(1.5, float(bgm_volume)))
            filter_parts.append(
                f"[{bgm_idx}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                f"atrim=duration={total_duration:.3f},volume={vol:.2f},"
                f"afade=t=in:st=0:d=0.8,afade=t=out:st={fade_out_start:.2f}:d=1.5[bgm]"
            )
            filter_parts.append(
                f"[acat][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[amixout]"
            )
            audio_label = "[amixout]"

        temp_srt_file: Path | None = None
        try:
            if subtitle_srt and subtitle_srt.strip():
                with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as tf:
                    tf.write(subtitle_srt.strip() + "\n")
                    temp_srt_file = Path(tf.name)
                escaped = _escape_ffmpeg_sub_path(temp_srt_file)
                font_part = "FontName=WenQuanYi Zen Hei," if platform.system() == "Linux" else ""
                filter_parts.append(
                    f"{video_label}subtitles='{escaped}':force_style='{font_part}FontSize=20,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,Outline=2,MarginV=28'[vsub]"
                )
                video_label = "[vsub]"

            filter_complex = ";".join(filter_parts)
            cmd += [
                "-filter_complex", filter_complex,
                "-map", video_label,
                "-map", audio_label,
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(output_path),
            ]

            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
            if res.returncode != 0 or not output_path.exists():
                if enable_xfade:
                    return False
                raise RuntimeError(f"FFmpeg 导出失败: {res.stderr[-600:]}")
            return True
        finally:
            if temp_srt_file and temp_srt_file.exists():
                temp_srt_file.unlink(missing_ok=True)

    if use_xfade:
        if not _run_export(True):
            _run_export(False)
    else:
        _run_export(False)

    final_dur, _ = probe_media_info(output_path)
    return final_dur
