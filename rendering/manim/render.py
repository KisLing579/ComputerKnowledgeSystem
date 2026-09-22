from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


def quarantine_invalid_text_cache(media_dir: Path) -> int:
    """Preserve damaged SVGs for inspection and let Manim rebuild them."""
    count = 0
    for path in (media_dir / "texts").glob("*.svg"):
        try:
            ET.parse(path)
        except ET.ParseError:
            path.rename(path.with_suffix(f".invalid-{uuid.uuid4().hex}.svg.bak"))
            count += 1
    return count


def audio_references(script: Path) -> list[str]:
    """Inspect the generated literal plan without importing Manim or executing code."""
    tree = ast.parse(script.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PLAN" for t in node.targets):
            if isinstance(node.value, ast.Call) and node.value.args:
                payload = json.loads(ast.literal_eval(node.value.args[0]))
                return ([payload["opening_audio"]["path"]] if payload.get("opening_audio") else []) + [b["audio"]["path"] for s in payload.get("scenes", [])
                        for b in s.get("beats", []) if b.get("audio")]
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a generated semantic explanation Manim script")
    parser.add_argument("script")
    parser.add_argument("--quality", default="l", choices=["l", "m", "h", "p", "k"])
    parser.add_argument("--scene", default="GeneratedExplanation")
    parser.add_argument("--media-dir", default="media")
    parser.add_argument("--async-writer", action="store_true", help="Use Manim's original queued frame writer")
    args = parser.parse_args()

    script = Path(args.script).expanduser().resolve()
    if not script.exists():
        raise SystemExit(f"Script not found: {script}")
    repaired = quarantine_invalid_text_cache(Path(args.media_dir).expanduser().resolve())
    if repaired:
        print(f"Quarantined {repaired} damaged text SVG cache files; Manim will rebuild them.", flush=True)
    audio = audio_references(script)
    missing = [p for p in audio if not Path(p).is_file()]
    if missing:
        raise SystemExit("Missing narration audio: " + ", ".join(missing))
    print(f"Narration audio clips: {len(audio)}", flush=True)
    if not audio:
        print("WARNING: This script has no narration audio. Run resource_planning.tts on render_plan.json first.", flush=True)
    cmd = [
        sys.executable, "-m", "manim" if args.async_writer else "rendering.manim.low_memory", f"-q{args.quality}",
        "--media_dir", str(Path(args.media_dir).expanduser().resolve()),
        str(script), args.scene,
    ]
    if audio:
        # Cached play() calls can leave skip_animations set when add_sound runs.
        cmd.insert(3, "--disable_caching")
    print("Running:", " ".join(cmd))
    env = os.environ.copy()
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("OMP_NUM_THREADS", "1")
    print("Frame writer:", "queued" if args.async_writer else "synchronous (low memory)", flush=True)
    raise SystemExit(subprocess.call(cmd, env=env))


if __name__ == "__main__":
    main()
