"""
Train a CLIP-based image classifier from labeling data.

Usage:
    python train.py --image-dir /path/to/images --labeler-url https://labeler.goldentooth.net

Outputs:
    model.pkl  — trained classifier (sklearn pipeline)
    report.txt — classification report on held-out test set
"""

import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split


def load_labels(labeler_url: str, verify_ssl: bool = False) -> list[dict]:
    """Fetch labels from the labeler API."""
    import urllib.request
    import ssl

    ctx = None if verify_ssl else ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    url = f"{labeler_url.rstrip('/')}/api/export"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, context=ctx) as resp:
        return json.loads(resp.read().decode())


def load_clip_model(device: str):
    """Load CLIP model and preprocessing."""
    import open_clip

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k"
    )
    model = model.to(device).eval()
    return model, preprocess


def extract_embeddings(
    model, preprocess, image_paths: list[Path], device: str, batch_size: int = 64
) -> np.ndarray:
    """Extract CLIP image embeddings in batches."""
    all_embeddings = []
    total = len(image_paths)

    for i in range(0, total, batch_size):
        batch_paths = image_paths[i : i + batch_size]
        images = []
        for p in batch_paths:
            try:
                img = Image.open(p).convert("RGB")
                images.append(preprocess(img))
            except Exception as e:
                print(f"  Warning: skipping {p}: {e}", file=sys.stderr)
                images.append(preprocess(Image.new("RGB", (224, 224))))

        batch_tensor = torch.stack(images).to(device)
        with torch.no_grad():
            emb = model.encode_image(batch_tensor)
            emb = emb / emb.norm(dim=-1, keepdim=True)  # L2 normalize
            all_embeddings.append(emb.cpu().numpy())

        done = min(i + batch_size, total)
        print(f"  Embedded {done}/{total} images", end="\r")

    print()
    return np.vstack(all_embeddings)


def main():
    parser = argparse.ArgumentParser(description="Train image classifier from labels")
    parser.add_argument("--image-dir", required=True, help="Root of sharded image directory")
    parser.add_argument("--labeler-url", default="https://labeler.goldentooth.net")
    parser.add_argument("--output", default="model.pkl", help="Output model path")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--device", default=None, help="torch device (auto-detected if omitted)")
    args = parser.parse_args()

    image_dir = Path(args.image_dir)

    # Auto-detect device
    if args.device:
        device = args.device
    elif torch.cuda.is_available():
        device = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    print(f"Using device: {device}")

    # Load labels
    print("Fetching labels from labeler...")
    labels = load_labels(args.labeler_url)
    print(f"  {len(labels)} labeled images ({sum(1 for l in labels if l['label'] == 'reject')} rejected)")

    # Filter to images that exist on disk
    valid = []
    for entry in labels:
        p = image_dir / entry["path"]
        if p.exists():
            valid.append(entry)
    print(f"  {len(valid)} found on disk")

    if len(valid) < 20:
        print("Not enough images found. Check --image-dir path.", file=sys.stderr)
        sys.exit(1)

    paths = [image_dir / e["path"] for e in valid]
    y = np.array([0 if e["label"] == "keep" else 1 for e in valid])

    # Split train/test
    paths_train, paths_test, y_train, y_test = train_test_split(
        paths, y, test_size=args.test_size, random_state=42, stratify=y
    )
    print(f"  Train: {len(y_train)} ({y_train.sum()} reject) | Test: {len(y_test)} ({y_test.sum()} reject)")

    # Load CLIP
    print("Loading CLIP model...")
    model, preprocess = load_clip_model(device)

    # Extract embeddings
    print("Extracting train embeddings...")
    X_train = extract_embeddings(model, preprocess, paths_train, device, args.batch_size)
    print("Extracting test embeddings...")
    X_test = extract_embeddings(model, preprocess, paths_test, device, args.batch_size)

    # Train classifier
    print("Training classifier...")
    # class_weight='balanced' handles the ~2% reject imbalance
    clf = LogisticRegression(
        max_iter=1000,
        class_weight="balanced",
        C=1.0,
        random_state=42,
    )
    clf.fit(X_train, y_train)

    # Evaluate
    y_pred = clf.predict(X_test)
    report = classification_report(
        y_test, y_pred, target_names=["keep", "reject"], digits=3
    )
    cm = confusion_matrix(y_test, y_pred)

    print("\n=== Classification Report ===")
    print(report)
    print("Confusion Matrix:")
    print(f"  TN={cm[0,0]}  FP={cm[0,1]}")
    print(f"  FN={cm[1,0]}  TP={cm[1,1]}")

    # Resolve output path early (needed for errors.json too)
    output_path = Path(args.output)

    # Save misclassified images for review
    errors = {"false_positives": [], "missed_rejects": []}
    for i in range(len(y_test)):
        rel_path = str(paths_test[i].relative_to(image_dir))
        if y_test[i] == 0 and y_pred[i] == 1:
            errors["false_positives"].append(rel_path)
        elif y_test[i] == 1 and y_pred[i] == 0:
            errors["missed_rejects"].append(rel_path)

    errors_path = output_path.parent / "errors.json"
    with open(errors_path, "w") as f:
        json.dump(errors, f, indent=2)
    print(f"\nFalse positives: {len(errors['false_positives'])}")
    print(f"Missed rejects: {len(errors['missed_rejects'])}")
    print(f"Errors saved to {errors_path}")

    # Save model
    with open(output_path, "wb") as f:
        pickle.dump({"classifier": clf, "clip_model": "ViT-B-32", "clip_pretrained": "laion2b_s34b_b79k"}, f)
    print(f"Model saved to {output_path}")

    # Save report
    report_path = output_path.with_suffix(".report.txt")
    with open(report_path, "w") as f:
        f.write(report)
        f.write(f"\nConfusion Matrix:\n  TN={cm[0,0]}  FP={cm[0,1]}\n  FN={cm[1,0]}  TP={cm[1,1]}\n")
    print(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
