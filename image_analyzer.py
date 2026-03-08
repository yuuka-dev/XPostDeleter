"""
image_analyzer.py
顔認識（insightface）とNSFW判定（NudeNet）を行うモジュール
reference_media/ の自撮り画像と顔照合して本人判定する
各プロセスで独立してモデルを保持する（ProcessPoolExecutor対応）
"""

import os
import tempfile
from pathlib import Path

import cv2
import numpy as np
from nudenet import NudeDetector

# NudeNetの検出クラスのうちリスクありとみなすもの
NSFW_CLASSES = {
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "ANUS_EXPOSED",
    "BUTTOCKS_EXPOSED",
}

NSFW_MILD_CLASSES = {
    "FEMALE_BREAST_COVERED",
    "FEMALE_GENITALIA_COVERED",
    "MALE_GENITALIA_COVERED",
    "BUTTOCKS_COVERED",
    "BELLY_EXPOSED",
    "ARMPITS_EXPOSED",
}

REFERENCE_DIR = Path(__file__).parent / "reference_media"

# 顔照合の類似度閾値（cosine similarity: 0〜1、高いほど同一人物）
FACE_SIMILARITY_THRESHOLD = 0.4

_face_app = None
_nude_detector = None
_reference_embeddings: list[np.ndarray] = []
_reference_loaded = False


def _get_face_app():
    global _face_app
    if _face_app is None:
        from insightface.app import FaceAnalysis
        _face_app = FaceAnalysis(providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        _face_app.prepare(ctx_id=0, det_size=(640, 640))
    return _face_app


def _get_nude_detector():
    global _nude_detector
    if _nude_detector is None:
        _nude_detector = NudeDetector()
    return _nude_detector


def _load_reference_embeddings():
    global _reference_embeddings, _reference_loaded
    if _reference_loaded:
        return
    _reference_loaded = True

    if not REFERENCE_DIR.exists():
        print(f"[WARN] reference_media が見つかりません: {REFERENCE_DIR}")
        return

    app = _get_face_app()
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    loaded = 0
    for p in REFERENCE_DIR.iterdir():
        if p.suffix.lower() not in exts:
            continue
        img = cv2.imread(str(p))
        if img is None:
            continue
        faces = app.get(img)
        for face in faces:
            if face.embedding is not None:
                emb = face.embedding / np.linalg.norm(face.embedding)
                _reference_embeddings.append(emb)
                loaded += 1

    print(f"[INFO] reference_media: {loaded} 件の顔embeddingを登録")


def _is_my_face(embedding: np.ndarray) -> bool:
    """embeddingがreference_mediaの顔と一致するか判定"""
    if not _reference_embeddings:
        return False
    emb = embedding / np.linalg.norm(embedding)
    sims = [float(np.dot(emb, ref)) for ref in _reference_embeddings]
    return max(sims) >= FACE_SIMILARITY_THRESHOLD


def analyze_video(video_path: str, sample_interval_sec: float = 2.0) -> dict:
    """
    動画をフレームサンプリングして解析する
    sample_interval_sec 秒おきにフレームを抽出して analyze_image と同等の判定を行う
    """
    result = {
        "has_face": False,
        "face_is_selfie": False,
        "nsfw_score": 0.0,
        "risk_tags": [],
        "severity": 0,
        "error": None,
    }

    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            result["error"] = f"動画読み込み失敗: {video_path}"
            return result

        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        frame_interval = max(1, int(fps * sample_interval_sec))
        frame_idx = 0
        best_severity = 0
        all_risk_tags = []

        with tempfile.TemporaryDirectory() as tmpdir:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                if frame_idx % frame_interval == 0:
                    tmp_path = os.path.join(tmpdir, f"frame_{frame_idx}.jpg")
                    cv2.imwrite(tmp_path, frame)
                    frame_result = analyze_image(tmp_path)
                    if frame_result["severity"] > best_severity:
                        best_severity = frame_result["severity"]
                    for tag in frame_result["risk_tags"]:
                        if tag not in all_risk_tags:
                            all_risk_tags.append(tag)
                    if best_severity >= 5:
                        break
                frame_idx += 1
        cap.release()

        result["severity"] = best_severity
        result["risk_tags"] = all_risk_tags
        result["has_face"] = "FACE_SELFIE" in all_risk_tags or "FACE_DETECTED" in all_risk_tags
        result["face_is_selfie"] = "FACE_SELFIE" in all_risk_tags
        result["nsfw_score"] = 1.0 if "NSFW_HIGH" in all_risk_tags else (0.5 if "NSFW_MILD" in all_risk_tags else 0.0)

    except Exception as e:
        result["error"] = f"動画解析エラー: {e}"

    return result


def analyze_image(image_path: str) -> dict:
    """
    画像を解析して顔・NSFWリスクを返す

    Returns:
        {
            "has_face": bool,
            "face_is_selfie": bool,   # 本人の顔が検出された場合True
            "nsfw_score": float,
            "risk_tags": list[str],
            "severity": int,          # 0〜5
            "error": str | None,
        }
    """
    _load_reference_embeddings()

    result = {
        "has_face": False,
        "face_is_selfie": False,
        "nsfw_score": 0.0,
        "risk_tags": [],
        "severity": 0,
        "error": None,
    }

    try:
        img = cv2.imread(image_path)
        if img is None:
            result["error"] = f"画像読み込み失敗: {image_path}"
            return result

        # --- 顔認識・本人照合 ---
        try:
            app = _get_face_app()
            faces = app.get(img)
            if faces:
                result["has_face"] = True
                for face in faces:
                    if face.embedding is not None and _is_my_face(face.embedding):
                        result["face_is_selfie"] = True
                        break
        except Exception as e:
            result["error"] = f"顔認識エラー: {e}"

        # --- NSFW判定 ---
        try:
            nd = _get_nude_detector()
            detections = nd.detect(image_path)
            nsfw_scores = []
            mild_scores = []
            for det in detections:
                cls = det.get("class", "")
                score = det.get("score", 0.0)
                if cls in NSFW_CLASSES:
                    nsfw_scores.append(score)
                    if score >= 0.5:
                        tag = cls.replace("_EXPOSED", "").replace("_", " ").title()
                        if f"NSFW:{tag}" not in result["risk_tags"]:
                            result["risk_tags"].append(f"NSFW:{tag}")
                elif cls in NSFW_MILD_CLASSES:
                    mild_scores.append(score)
            if nsfw_scores:
                result["nsfw_score"] = max(nsfw_scores)
            elif mild_scores:
                result["nsfw_score"] = max(mild_scores) * 0.4
        except Exception as e:
            result["error"] = f"NSFW判定エラー: {e}"

        # --- severity計算 ---
        severity = 0
        if result["nsfw_score"] >= 0.7:
            severity = 5
            result["risk_tags"].insert(0, "NSFW_HIGH")
        elif result["nsfw_score"] >= 0.4:
            severity = 3
            result["risk_tags"].insert(0, "NSFW_MILD")

        if result["face_is_selfie"]:
            severity = max(severity, 3)
            result["risk_tags"].insert(0, "FACE_SELFIE")
        elif result["has_face"]:
            severity = max(severity, 1)
            result["risk_tags"].insert(0, "FACE_DETECTED")

        result["severity"] = severity

    except Exception as e:
        result["error"] = f"予期しないエラー: {e}"

    return result
