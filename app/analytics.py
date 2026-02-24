import csv
from typing import Iterable


def load_log(path: str = "output/person_count_log.csv") -> list[dict]:
    if not path:
        return []
    rows: list[dict] = []
    try:
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
    except FileNotFoundError:
        return []
    return rows


def compute_summary(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    if not rows:
        return {"latest": 0, "peak": 0, "average": 0, "total_frames": 0}
    counts = [int(row["person_count"]) for row in rows]
    return {
        "latest": int(counts[-1]),
        "peak": int(max(counts)),
        "average": float(sum(counts) / len(counts)),
        "total_frames": int(len(counts)),
    }


def build_alerts(rows: Iterable[dict], threshold: int, spike_delta: int) -> list[dict]:
    rows = list(rows)
    if not rows:
        return []
    alerts: list[dict] = []
    prev_count = None
    for row in rows:
        count = int(row["person_count"])
        frame_id = int(row["frame"])
        if count >= threshold:
            alerts.append(
                {
                    "frame": frame_id,
                    "person_count": count,
                    "type": "Crowd threshold exceeded",
                    "severity": "high" if count >= threshold + 3 else "medium",
                }
            )
        if prev_count is not None and (count - prev_count) >= spike_delta:
            delta = count - prev_count
            alerts.append(
                {
                    "frame": frame_id,
                    "person_count": count,
                    "type": "Sudden crowd spike",
                    "severity": "high" if delta >= spike_delta + 2 else "medium",
                }
            )
        prev_count = count
    return alerts


def plot_crowd_density(rows: Iterable[dict]) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed. Run: python -m pip install matplotlib")
        return

    rows = list(rows)
    if not rows:
        print("No data available to plot.")
        return
    frames = [row["frame"] for row in rows]
    counts = [row["person_count"] for row in rows]

    plt.figure(figsize=(10, 4))
    plt.plot(frames, counts)
    plt.xlabel("Frame")
    plt.ylabel("People Count")
    plt.title("Crowd Density Over Time (Privacy-Preserved)")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    rows = load_log()
    plot_crowd_density(rows)

