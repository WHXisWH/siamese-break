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
    from scipy.ndimage import binary_closing, binary_dilation, binary_opening, find_objects, gaussian_filter, label

    f = rgb / 255
    greenish = f[..., 1] - np.maximum(f[..., 0], f[..., 2])
    cat = alpha > 0.5
    above = np.maximum.accumulate(cat, axis=0)
    below = np.maximum.accumulate(cat[::-1], axis=0)[::-1]
    gaps = binary_opening(above & below & ~cat & (greenish < 0.03), iterations=1)
    labels, _ = label(binary_dilation(gaps, iterations=12))
    keep = np.zeros_like(gaps)
    for i, box in enumerate(find_objects(labels), 1):
        if box and box[1].stop - box[1].start >= 0.2 * gaps.shape[1]:
            keep |= (labels == i) & gaps
    if keep.any():
        from scipy.ndimage import median_filter

        h = keep.shape[0]
        cols = keep.any(axis=0)
        top = np.where(cols, keep.argmax(axis=0), h)
        top = median_filter(top, size=31, mode="nearest")
        rows = np.arange(h)[:, None]
        keep = keep | (rows >= top[None, :])
    return np.maximum(alpha, gaussian_filter(keep.astype(np.float32), 1.0))


def drop_fragments(alpha, min_ratio):
    from scipy.ndimage import binary_dilation, label

    labels, n = label(binary_dilation(alpha > 0.3, iterations=3))
    if n <= 1:
        return alpha
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    keep = sizes >= sizes.max() * min_ratio
    return np.where(keep[labels], alpha, 0)


def parse_cut_keys(text):
    keys = sorted((int(k), float(v)) for k, v in (item.split(":") for item in text.split(",") if item))
    return [k for k, _ in keys], [v for _, v in keys]


def cut_and_lower(rgb, alpha, cut_center, slope, margin, max_shift, feather):
    h, w = alpha.shape
    if cut_center >= h:
        return rgb, alpha
    xs = np.arange(w)
    line = cut_center - margin + slope * (xs - w / 2)
    rows = np.arange(h)[:, None]
    alpha = alpha * np.clip((line[None, :] - rows) / feather, 0, 1)
    shift = int(round(min(h - (cut_center - margin), max_shift)))
    if shift <= 0:
        return rgb, alpha
    rgb2 = np.zeros_like(rgb)
    alpha2 = np.zeros_like(alpha)
    rgb2[shift:] = rgb[:h - shift]
    alpha2[shift:] = alpha[:h - shift]
    return rgb2, alpha2


def body_anchors(masks, window):
    raw = []
    for m in masks:
        cat = m > 0.5
        rows = np.where(cat.any(axis=1))[0]
        top, low = rows.min(), rows.max()
        lowest = np.where(cat.any(axis=0), cat.shape[0] - 1 - np.argmax(cat[::-1], axis=0), -1)
        bottom = np.percentile(lowest[lowest >= 0], 90)
        band = cat[int(top + 0.6 * (bottom - top)):int(bottom) + 1]
        cx = np.nonzero(band)[1].mean()
        raw.append((cx, bottom, top))
    raw = np.array(raw, dtype=np.float64)
    k = np.ones(window) / window
    pad = window // 2
    smooth = np.stack([np.convolve(np.pad(raw[:, i], pad, mode="edge"), k, mode="valid") for i in range(3)], axis=1)
    return smooth


def fade_bottom(alpha, feather):
    cat = alpha > 0.5
    h = alpha.shape[0]
    lowest = np.where(cat.any(axis=0), h - 1 - np.argmax(cat[::-1], axis=0), -1).astype(np.float32)
    rows = np.arange(h, dtype=np.float32)[:, None]
    return alpha * np.clip((lowest[None, :] - rows) / feather, 0, 1)


def place(rgb, alpha, anchor, scale, size):
    from PIL import Image as Img

    w, h = size
    cx, bottom, _ = anchor
    sw, sh = round(rgb.shape[1] * scale), round(rgb.shape[0] * scale)
    rgb_s = np.asarray(Img.fromarray(rgb.clip(0, 255).astype(np.uint8)).resize((sw, sh), Img.LANCZOS)).astype(np.float32)
    a_s = np.asarray(Img.fromarray((alpha * 255).astype(np.uint8)).resize((sw, sh), Img.LANCZOS)).astype(np.float32) / 255
    ox = round(w / 2 - cx * scale)
    oy = round(h - bottom * scale)
    out_rgb = np.zeros((h, w, 3), np.float32)
    out_a = np.zeros((h, w), np.float32)
    x0, y0 = max(ox, 0), max(oy, 0)
    x1, y1 = min(ox + sw, w), min(oy + sh, h)
    out_rgb[y0:y1, x0:x1] = rgb_s[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
    out_a[y0:y1, x0:x1] = a_s[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
    return out_rgb, out_a


def compose(frames, masks, out_dir, gamma, sigma, fill, cut_keys, cut_slope, cut_margin, lift_keys, feather, framing=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    keys = parse_cut_keys(cut_keys) if cut_keys else None
    lifts = parse_cut_keys(lift_keys) if lift_keys else None
    for f, a in zip(frames, masks):
        rgb = np.asarray(Image.open(f).convert("RGB")).astype(np.float32)
        alpha = np.clip(a, 0, 1)
        if fill:
            alpha = fill_occluders(rgb, alpha)
        alpha = drop_fragments(alpha, 0.03)
        alpha = alpha ** gamma
        rgb = decontaminate(rgb, alpha, sigma)
        if framing:
            alpha = fade_bottom(alpha, framing["feather"])
            rgb, alpha = place(rgb, alpha, framing["anchors"][int(f.stem) - 1], framing["scale"], framing["size"])
        if keys:
            n = int(f.stem)
            cut = float(np.interp(n, keys[0], keys[1], right=alpha.shape[0] + cut_margin + 1))
            lift = float(np.interp(n, lifts[0], lifts[1])) if lifts else alpha.shape[0]
            rgb, alpha = cut_and_lower(rgb, alpha, cut, cut_slope, cut_margin, lift, feather)
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
    p.add_argument("--cut-keys", default="")
    p.add_argument("--cut-slope", type=float, default=0.0)
    p.add_argument("--cut-margin", type=float, default=8.0)
    p.add_argument("--cut-feather", type=float, default=50.0)
    p.add_argument("--lift-keys", default="")
    p.add_argument("--frame", default="")
    p.add_argument("--frame-fill", type=float, default=0.96)
    p.add_argument("--bottom-feather", type=float, default=40.0)
    p.add_argument("--anchor-window", type=int, default=9)
    p.add_argument("--skip-extract", action="store_true")
    args = p.parse_args()

    frames_dir = args.work / "frames"
    if not args.skip_extract:
        extract_frames(args.video, frames_dir, args.width, args.height)
    frames = sorted(frames_dir.glob("[0-9][0-9][0-9][0-9].png"))
    if not frames:
        sys.exit("no frames extracted")

    make_masks(frames, args.model)
    masks = [np.asarray(Image.open(mask_path(f, args.model)).convert("L")).astype(np.float32) / 255 for f in frames]
    masks = smooth_masks(masks, args.smooth)

    framing = None
    if args.frame:
        w, h = (int(v) for v in args.frame.split("x"))
        anchors = body_anchors(masks, args.anchor_window)
        scale = args.frame_fill * h / max(b - t for _, b, t in anchors)
        framing = {"anchors": anchors, "scale": scale, "size": (w, h), "feather": args.bottom_feather}
        print(f"framing scale {scale:.2f}", flush=True)

    rgba_dir = args.work / "rgba"
    compose(frames, masks, rgba_dir, args.gamma, args.decontam, not args.no_fill, args.cut_keys, args.cut_slope, args.cut_margin, args.lift_keys, args.cut_feather, framing)
    encode(rgba_dir, [f.name for f in frames], args.output, args.fps, args.crf, not args.no_pingpong)
    print("done", args.output, flush=True)


if __name__ == "__main__":
    main()
