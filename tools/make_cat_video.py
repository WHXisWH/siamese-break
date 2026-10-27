import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def run(cmd):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


def extract_frames(video, frames_dir, width, height):
    frames_dir.mkdir(parents=True, exist_ok=True)
    if any(frames_dir.glob("[0-9][0-9][0-9][0-9].png")):
        return
    run([
        "ffmpeg", "-v", "error", "-y", "-i", str(video),
        "-vf", f"scale={width}:{height}:flags=lanczos",
        str(frames_dir / "%04d.png"),
    ])


def make_masks(frames, model):
    todo = [f for f in frames if not mask_path(f, model).exists()]
    if not todo:
        return
    import onnxruntime as ort
    from rembg import new_session, remove

    opts = ort.SessionOptions()
    opts.enable_cpu_mem_arena = False
    opts.enable_mem_pattern = False
    session = new_session(model, sess_opts=opts)
    for i, f in enumerate(todo, 1):
        remove(Image.open(f).convert("RGB"), session=session, only_mask=True).save(mask_path(f, model))
        print(f"mask {i}/{len(todo)} {f.name}", flush=True)


def mask_path(frame, model):
    return frame.with_name(f"{frame.stem}.{model}.mask.png")


def smooth_masks(masks, strength):
    if strength <= 0:
        return masks
    out = []
    for i, m in enumerate(masks):
        prev = masks[max(i - 1, 0)]
        nxt = masks[min(i + 1, len(masks) - 1)]
        blended = (1 - strength) * m + strength * 0.5 * (prev + nxt)
        stable = np.abs(prev - nxt) < 0.25
        out.append(np.where(stable, blended, m))
    return out


def decontaminate(rgb, alpha, sigma):
    from scipy.ndimage import gaussian_filter

    solid = (alpha > 0.95).astype(np.float32)
    den = gaussian_filter(solid, sigma)
    est = np.empty_like(rgb)
    for c in range(3):
        est[..., c] = gaussian_filter(rgb[..., c] * solid, sigma) / np.maximum(den, 1e-4)
    w = np.clip((0.95 - alpha) / 0.95, 0, 1)[..., None]
    w = np.where(den[..., None] > 1e-3, w, 0)
    return rgb * (1 - w) + est * w


def fill_occluders(rgb, alpha):
    from scipy.ndimage import binary_opening, gaussian_filter

    f = rgb / 255
    greenish = f[..., 1] - np.maximum(f[..., 0], f[..., 2])
    cat = alpha > 0.5
    above = np.maximum.accumulate(cat, axis=0)
    below = np.maximum.accumulate(cat[::-1], axis=0)[::-1]
    gaps = binary_opening(above & below & ~cat & (greenish < 0.03), iterations=1)
    return np.maximum(alpha, gaussian_filter(gaps.astype(np.float32), 1.0))


def compose(frames, masks, out_dir, gamma, sigma, fill):
    out_dir.mkdir(parents=True, exist_ok=True)
    for f, a in zip(frames, masks):
        rgb = np.asarray(Image.open(f).convert("RGB")).astype(np.float32)
        alpha = np.clip(a, 0, 1)
        if fill:
            alpha = fill_occluders(rgb, alpha)
        alpha = alpha ** gamma
        rgb = decontaminate(rgb, alpha, sigma)
        rgba = np.dstack([rgb, alpha * 255]).round().clip(0, 255).astype(np.uint8)
        Image.fromarray(rgba, "RGBA").save(out_dir / f.name)


def encode(rgba_dir, names, output, fps, crf, pingpong):
    order = list(names)
    if pingpong:
        order += list(reversed(names[1:-1]))
    seq_dir = rgba_dir / "seq"
    seq_dir.mkdir(exist_ok=True)
    for old in seq_dir.glob("*.png"):
        old.unlink()
    for i, name in enumerate(order, 1):
        (seq_dir / f"{i:05d}.png").symlink_to((rgba_dir / name).resolve())
    run([
        "ffmpeg", "-v", "error", "-y", "-framerate", str(fps),
        "-i", str(seq_dir / "%05d.png"),
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
        "-b:v", "0", "-crf", str(crf), "-row-mt", "1",
        "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "2",
        "-an", str(output),
    ])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--work", type=Path, default=Path("work"))
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=float, default=24)
    p.add_argument("--crf", type=int, default=30)
    p.add_argument("--model", default="birefnet-general")
    p.add_argument("--smooth", type=float, default=0.3)
    p.add_argument("--gamma", type=float, default=1.3)
    p.add_argument("--decontam", type=float, default=6.0)
    p.add_argument("--no-pingpong", action="store_true")
    p.add_argument("--no-fill", action="store_true")
    args = p.parse_args()

    frames_dir = args.work / "frames"
    extract_frames(args.video, frames_dir, args.width, args.height)
    frames = sorted(frames_dir.glob("[0-9][0-9][0-9][0-9].png"))
    if not frames:
        sys.exit("no frames extracted")

    make_masks(frames, args.model)
    masks = [np.asarray(Image.open(mask_path(f, args.model)).convert("L")).astype(np.float32) / 255 for f in frames]
    masks = smooth_masks(masks, args.smooth)

    rgba_dir = args.work / "rgba"
    compose(frames, masks, rgba_dir, args.gamma, args.decontam, not args.no_fill)
    encode(rgba_dir, [f.name for f in frames], args.output, args.fps, args.crf, not args.no_pingpong)
    print("done", args.output, flush=True)


if __name__ == "__main__":
    main()
