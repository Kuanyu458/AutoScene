"""Generate a royalty-free local input folder for the Beat3D quick start."""

from __future__ import annotations

import argparse
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-3000:] or completed.stdout[-3000:])


def _write_click_track(path: Path, *, duration: float = 8.0, bpm: float = 120.0) -> None:
    sample_rate = 48_000
    interval = 60.0 / bpm
    frames = bytearray()
    for index in range(round(duration * sample_rate)):
        t = index / sample_rate
        within_beat = t % interval
        if within_beat < 0.035:
            envelope = math.exp(-within_beat / 0.006)
            value = 0.72 * envelope * math.sin(2 * math.pi * 1100 * t)
        else:
            value = 0.0
        frames.extend(struct.pack("<h", max(-32767, min(32767, round(value * 32767)))))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)


def create_fixture(output: Path) -> Path:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"OUTPUT_EXISTS: refusing to overwrite {output}")
    output.mkdir(parents=True, exist_ok=True)
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFMPEG_UNAVAILABLE: install FFmpeg before generating the fixture")

    (output / "brief.md").write_text(
        """# Synthetic Beat3D demo

Create an eight-second energetic technology montage. Use the prepared source
clips, synchronize cuts to the 120 BPM music, and include one full-frame
procedural 3D data-constellation insert. No remote assets or API providers.
""",
        encoding="utf-8",
    )
    for index, hue in enumerate((0, 70, 145, 220), 1):
        clip = output / f"clip-{index}.mp4"
        _run([
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30:duration=2",
            "-vf",
            f"hue=h={hue}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(clip),
        ])
    _write_click_track(output / "music.wav")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="new or empty destination folder")
    args = parser.parse_args(argv)
    try:
        result = create_fixture(Path(args.output).expanduser().resolve())
    except (FileExistsError, RuntimeError) as exc:
        print(str(exc))
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
