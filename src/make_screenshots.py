"""Render terminal-style PNG snapshots from *real* command output.

The images are generated from commands executed right now (Docker, aws-cli,
verification log). They are captioned in the report as terminal snapshots,
not as hand-made mock-ups: the commands and their full text are also included
in the report appendix.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path("report/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

FONT_REG = "C:/Windows/Fonts/consola.ttf"
FONT_BOLD = "C:/Windows/Fonts/consolab.ttf"
BG = (24, 26, 31)
BG_TITLE = (38, 41, 48)
FG = (226, 232, 240)
FG_DIM = (148, 163, 184)
FG_GREEN = (74, 222, 128)
FG_BLUE = (96, 165, 250)
ACCENTS = [(255, 95, 86), (255, 189, 46), (39, 201, 63)]

COMMANDS = [
    {
        "file": "01_docker_compose_ps.png",
        "title": "docker compose ps",
        "cmd": ["docker", "compose", "ps"],
        "cwd": ".",
    },
    {
        "file": "02_rustfs_bucket.png",
        "title": "minio/aws-cli: bucket hh-lake",
        "cmd": [
            "docker", "exec", "hh-s3cli", "aws", "--endpoint-url",
            "http://rustfs-home:9000", "s3", "ls", "s3://hh-lake/",
            "--recursive", "--human-readable", "--summarize",
        ],
        "cwd": ".",
    },
    {
        "file": "03_object_head.png",
        "title": "aws s3api head-object raw/vacancies.csv",
        "cmd": [
            "docker", "exec", "hh-s3cli", "aws", "--endpoint-url",
            "http://rustfs-home:9000", "s3api", "head-object",
            "--bucket", "hh-lake", "--key", "raw/vacancies.csv",
        ],
        "cwd": ".",
    },
]


def run(cmd: list[str], cwd: str = ".") -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    out = (proc.stdout or "") + (proc.stderr or "")
    return out.strip() or f"(exit {proc.returncode}, no output)"


def render(title: str, command: str, body: str, path: Path,
           width_chars: int = 118, show_prompt: bool = True) -> None:
    font = ImageFont.truetype(FONT_REG, 16, layout_engine=ImageFont.Layout.BASIC)
    bold = ImageFont.truetype(FONT_BOLD, 16, layout_engine=ImageFont.Layout.BASIC)
    small = ImageFont.truetype(FONT_REG, 13, layout_engine=ImageFont.Layout.BASIC)

    lines = textwrap.wrap(body, width=width_chars, replace_whitespace=False,
                          drop_whitespace=False) or [""]
    char_w = font.getlength("M")
    line_h = 22
    pad = 24
    width = int(min(max(char_w * width_chars + pad * 2, 900), 1600))
    height = 46 + pad * 2 + line_h * (len(lines) + (2 if show_prompt else 0))

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 36], fill=BG_TITLE)
    for i, color in enumerate(ACCENTS):
        draw.ellipse([16 + i * 22, 13, 28 + i * 22, 25], fill=color)
    draw.text((width / 2, 18), title, font=small, fill=FG_DIM, anchor="mm")

    y = 46 + pad
    if show_prompt:
        draw.text((pad, y), "PS> ", font=bold, fill=FG_BLUE)
        draw.text((pad + font.getlength("PS> "), y), command, font=font, fill=FG)
        y += line_h * 1.6
    for line in lines:
        color = FG
        low = line.lower()
        if low.startswith("total") or "upload:" in low or "etag" in low:
            color = FG_GREEN
        elif low.startswith("name ") or low.startswith("container") or low.startswith("hh-"):
            color = FG_BLUE
        draw.text((pad, y), line, font=font, fill=color)
        y += line_h

    img.save(path, optimize=True)
    print(f"  {path.name}: {width}x{height}, {path.stat().st_size // 1024} KiB")


def read_log_text(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"\xff\xfe"):
        return data.decode("utf-16")
    if data.startswith(b"\xfe\xff"):
        return data.decode("utf-16-be")
    return data.decode("utf-8-sig", errors="replace")


def from_log(log_path: str, title: str, command: str, out_name: str,
             tail: int | None = None) -> None:
    text = read_log_text(Path(log_path)).strip()
    if tail:
        text = "\n".join(text.splitlines()[-tail:])
    render(title, command, text, OUT / out_name)


def main() -> int:
    for item in COMMANDS:
        out = run(item["cmd"], item["cwd"])
        print(f"$ {' '.join(item['cmd'])}")
        print(out[:800])
        render(item["title"], " ".join(item["cmd"]), out, OUT / item["file"])

    verify_log = Path("report/logs/05_verify.log")
    if verify_log.exists():
        from_log(str(verify_log), "python src/verify.py",
                 "python src/verify.py", "04_verify.png")

    profile_log = Path("report/logs/12_profile.log")
    if profile_log.exists():
        lines = read_log_text(profile_log).splitlines()
        idx = next((i for i, ln in enumerate(lines) if "Profile Summary" in ln), None)
        if idx is not None:
            body = "\n".join(lines[idx:])
            render("python src/profile.py", "python src/profile.py", body,
                   OUT / "05_profile.png")

    bench_log = Path("report/logs/13_benchmark.log")
    if bench_log.exists():
        lines = read_log_text(bench_log).splitlines()
        idx = next((i for i, ln in enumerate(lines)
                    if "Optimization Benchmark Summary" in ln), None)
        if idx is not None:
            body = "\n".join(lines[idx:])
            render("python src/benchmark_optimization.py",
                   "python src/benchmark_optimization.py", body,
                   OUT / "06_benchmark.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
