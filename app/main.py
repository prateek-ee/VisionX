import argparse
import csv
import os
import threading
import time
from collections import deque

import cv2
from ultralytics import YOLO

from analytics import build_alerts, compute_summary, load_log
from fastapi import FastAPI, Query, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")

OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

DATA_PATH = os.path.join(OUTPUT_DIR, "person_count_log.csv")

LIVE_LOCK = threading.Lock()
LIVE_LOG = deque(maxlen=5000)
LIVE_STATUS = {"last_frame": None, "last_count": None, "last_update": None}


def read_log_rows(path: str, limit: int | None = None) -> list[dict]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row or len(row) < 2:
                continue
            if row[0].lower().strip() == "frame":
                continue
            try:
                rows.append({"frame": int(row[0]), "person_count": int(row[1])})
            except ValueError:
                continue
    if limit is None or limit <= 0:
        return rows
    return rows[-limit:]


def record_live(frame_id: int, person_count: int) -> None:
    with LIVE_LOCK:
        LIVE_LOG.append({"frame": frame_id, "person_count": person_count})
        LIVE_STATUS["last_frame"] = frame_id
        LIVE_STATUS["last_count"] = person_count
        LIVE_STATUS["last_update"] = time.time()


def read_live_rows(limit: int | None = None) -> list[dict]:
    with LIVE_LOCK:
        rows = list(LIVE_LOG)
    if limit is None or limit <= 0:
        return rows
    return rows[-limit:]


def build_alerts_from_rows(rows: list[dict], threshold: int, spike_delta: int) -> list[dict]:
    if not rows:
        return []
    alerts = []
    prev_count = None
    for row in rows:
        count = row["person_count"]
        frame_id = row["frame"]
        if count >= threshold:
            alerts.append(
                {
                    "frame": int(frame_id),
                    "person_count": int(count),
                    "type": "Crowd threshold exceeded",
                    "severity": "high" if count >= threshold + 3 else "medium",
                }
            )
        if prev_count is not None and (count - prev_count) >= spike_delta:
            delta = count - prev_count
            alerts.append(
                {
                    "frame": int(frame_id),
                    "person_count": int(count),
                    "type": "Sudden crowd spike",
                    "severity": "high" if delta >= spike_delta + 2 else "medium",
                }
            )
        prev_count = count
    alerts.sort(key=lambda item: item["frame"], reverse=True)
    return alerts


def anonymize_region(frame, x1, y1, x2, y2):
    roi = frame[y1:y2, x1:x2]
    if roi.size != 0:
        roi = cv2.GaussianBlur(roi, (51, 51), 0)
        frame[y1:y2, x1:x2] = roi
    return frame

def run_pipeline(video_path: str) -> None:
    model = YOLO("yolov8n.pt")

    cap = cv2.VideoCapture(video_path, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(video_path, cv2.CAP_MSMF)
    if not cap.isOpened():
        cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("Error: Video source not accessible")
        return

    with open(DATA_PATH, "w", newline="") as log_file:
        csv_writer = csv.writer(log_file)
        csv_writer.writerow(["frame", "person_count"])
        log_file.flush()

        frame_id = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            results = model(frame, conf=0.4)
            person_count = 0

            for r in results:
                for box in r.boxes:
                    cls = int(box.cls[0])
                    label = model.names[cls]

                    if label == "person":
                        person_count += 1

                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        frame = anonymize_region(frame, x1, y1, x2, y2)

                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(
                            frame,
                            "Person (masked)",
                            (x1, y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (0, 255, 0),
                            1,
                        )

            csv_writer.writerow([frame_id, person_count])
            log_file.flush()
            record_live(frame_id, person_count)
            frame_id += 1

            cv2.putText(
                frame,
                f"People Count: {person_count}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 255),
                2,
            )

            cv2.imshow("Privacy-First Surveillance", frame)

            if cv2.waitKey(1) & 0xFF == 27:
                break

    cap.release()
    cv2.destroyAllWindows()


def create_app() -> FastAPI:
    app = FastAPI()

    templates = Jinja2Templates(directory=TEMPLATES_DIR)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/debug")
    def api_debug():
        info = {
            "data_path": DATA_PATH,
            "exists": os.path.exists(DATA_PATH),
            "size": os.path.getsize(DATA_PATH) if os.path.exists(DATA_PATH) else 0,
            "tail": [],
        }
        if info["exists"]:
            try:
                with open(DATA_PATH, "r", encoding="utf-8") as handle:
                    lines = handle.read().strip().splitlines()
                info["tail"] = lines[-5:]
            except Exception as exc:
                info["tail_error"] = str(exc)
        return JSONResponse(info)

    @app.get("/api/health")
    def api_health():
        with LIVE_LOCK:
            live_len = len(LIVE_LOG)
            status = dict(LIVE_STATUS)
        return JSONResponse(
            {
                "live_len": live_len,
                "last_frame": status["last_frame"],
                "last_count": status["last_count"],
                "last_update_unix": status["last_update"],
            }
        )

    @app.get("/api/metrics")
    def api_metrics():
        rows = read_live_rows()
        if not rows:
            rows = read_log_rows(DATA_PATH)
        if not rows:
            return JSONResponse({"latest": 0, "peak": 0, "average": 0, "total_frames": 0})
        counts = [row["person_count"] for row in rows]
        return JSONResponse(
            {
                "latest": int(counts[-1]),
                "peak": int(max(counts)),
                "average": float(sum(counts) / len(counts)),
                "total_frames": int(len(rows)),
            }
        )

    @app.get("/api/alerts")
    def api_alerts(
        threshold: int = Query(default=6),
        spike_delta: int = Query(default=3),
    ):
        rows = read_live_rows()
        if not rows:
            rows = read_log_rows(DATA_PATH)
        alerts = build_alerts_from_rows(rows, threshold=threshold, spike_delta=spike_delta)
        return JSONResponse(alerts[:100])

    @app.get("/api/log")
    def api_log(limit: int = Query(default=200)):
        rows = read_live_rows(limit=limit)
        if not rows:
            rows = read_log_rows(DATA_PATH, limit=limit)
        return JSONResponse(rows)

    @app.get("/")
    def index(request: Request):
         return templates.TemplateResponse(
        "dashboard.html",
        {"request": request}
        )

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smart surveillance pipeline + dashboard server")
    parser.add_argument("--video", default="0", help="Path to input video file or camera index")
    parser.add_argument("--run-pipeline", action="store_true", help="Run video processing pipeline")
    parser.add_argument("--serve", action="store_true", help="Start dashboard web server")
    parser.add_argument("--probe-cam", action="store_true", help="Probe available camera indexes")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", default=5000, type=int, help="Server port")
    return parser.parse_args()


def probe_cameras(max_index: int = 5) -> None:
    print("Probing camera indexes...")
    available = []
    for idx in range(max_index + 1):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
        if not cap.isOpened():
            cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            available.append(idx)
            cap.release()
    if available:
        print(f"Available camera indexes: {available}")
    else:
        print("No cameras detected by OpenCV.")


def main() -> None:
    args = parse_args()
    video_source = int(args.video) if str(args.video).isdigit() else args.video
    if args.probe_cam:
        probe_cameras()
        return
    if args.run_pipeline and args.serve:
        pipeline_thread = threading.Thread(
            target=run_pipeline, args=(video_source,), daemon=True
        )
        pipeline_thread.start()
    elif args.run_pipeline:
        run_pipeline(video_source)
    if args.serve:
        app = create_app()
        try:
            import uvicorn
        except ImportError:
            print("Uvicorn not installed. Run: python -m pip install uvicorn")
            return
        uvicorn.run(app, host=args.host, port=args.port)
    if not args.run_pipeline and not args.serve:
        run_pipeline(video_source)


if __name__ == "__main__":
    main()

