"""
Score all images using the trained classifier.

Usage:
    python score.py --image-dir /path/to/images --model model.pkl --output results.json

Outputs a JSON file with:
    {"reject": ["path1", "path2", ...], "keep": ["path3", ...], "errors": ["path4", ...]}
"""

import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image


def load_clip_model(clip_model_name: str, clip_pretrained: str, device: str):
    import open_clip

    model, _, preprocess = open_clip.create_model_and_transforms(
        clip_model_name, pretrained=clip_pretrained
    )
    model = model.to(device).eval()
    return model, preprocess


def scan_images(image_dir: Path) -> list[Path]:
    extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    images = []
    for path in image_dir.rglob("*"):
        if path.suffix.lower() in extensions and path.is_file():
            images.append(path)
    images.sort()
    return images


def score_batch(
    model, preprocess, classifier, paths: list[Path], device: str
) -> tuple[np.ndarray, list[int]]:
    """Embed and classify a batch. Returns (predictions, error_indices)."""
    images = []
    bad = []
    for idx, p in enumerate(paths):
        try:
            img = Image.open(p).convert("RGB")
            images.append(preprocess(img))
        except Exception:
            bad.append(idx)
            images.append(preprocess(Image.new("RGB", (224, 224))))

    batch_tensor = torch.stack(images).to(device)
    with torch.no_grad():
        emb = model.encode_image(batch_tensor)
        emb = emb / emb.norm(dim=-1, keepdim=True)

    preds = classifier.predict(emb.cpu().numpy())
    return preds, bad


def main():
    parser = argparse.ArgumentParser(description="Score all images")
    parser.add_argument("--image-dir", required=True, help="Root of image directory")
    parser.add_argument("--model", required=True, help="Path to model.pkl")
    parser.add_argument("--output", default="results.json", help="Output path")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default=None)
    args = parser.parse_args()

    image_dir = Path(args.image_dir)
    output_path = Path(args.output)

    if args.device:
        device = args.device
    elif torch.cuda.is_available():
        device = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    print(f"Using device: {device}")

    # Load trained model
    print("Loading classifier...")
    with open(args.model, "rb") as f:
        model_data = pickle.load(f)
    classifier = model_data["classifier"]
    clip_model_name = model_data.get("clip_model", "ViT-B-32")
    clip_pretrained = model_data.get("clip_pretrained", "laion2b_s34b_b79k")

    # Load CLIP
    print(f"Loading CLIP {clip_model_name}...")
    clip_model, preprocess = load_clip_model(clip_model_name, clip_pretrained, device)

    # Scan images
    print(f"Scanning {image_dir}...")
    all_images = scan_images(image_dir)
    total = len(all_images)
    print(f"Found {total} images")

    # Score in batches
    keep = []
    reject = []
    errors = []
    batch_size = args.batch_size

    for i in range(0, total, batch_size):
        batch_paths = all_images[i : i + batch_size]
        preds, bad_indices = score_batch(
            clip_model, preprocess, classifier, batch_paths, device
        )

        for j, path in enumerate(batch_paths):
            rel = str(path.relative_to(image_dir))
            if j in bad_indices:
                errors.append(rel)
            elif preds[j] == 1:
                reject.append(rel)
            else:
                keep.append(rel)

        done = min(i + batch_size, total)
        if done % (batch_size * 50) == 0 or done == total:
            print(f"  Scored {done}/{total} — {len(reject)} reject, {len(keep)} keep, {len(errors)} errors")

    # Save results
    results = {
        "total": total,
        "keep_count": len(keep),
        "reject_count": len(reject),
        "error_count": len(errors),
        "reject": reject,
        "keep": keep,
        "errors": errors,
    }
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nDone! {len(reject)} rejected, {len(keep)} kept, {len(errors)} errors")
    print(f"Results saved to {output_path}")


if __name__ == "__main__":
    main()
