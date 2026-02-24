const metricLatest = document.getElementById("metricLatest");
const metricPeak = document.getElementById("metricPeak");
const metricAvg = document.getElementById("metricAvg");
const metricFrames = document.getElementById("metricFrames");
const alertsList = document.getElementById("alertsList");
const logBody = document.getElementById("logBody");

const thresholdInput = document.getElementById("threshold");
const spikeDeltaInput = document.getElementById("spikeDelta");
const refreshInput = document.getElementById("refreshSec");
const toggleAuto = document.getElementById("toggleAuto");
const debugStatus = document.getElementById("debugStatus");

let autoRefresh = true;
let chart;

function initChart() {
  const ctx = document.getElementById("trendChart");
  chart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "People Count",
          data: [],
          borderColor: "#4bd4ff",
          backgroundColor: "rgba(75, 212, 255, 0.2)",
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        x: { ticks: { color: "#9aa7bd" } },
        y: { ticks: { color: "#9aa7bd" } },
      },
      plugins: {
        legend: { labels: { color: "#e7ecf4" } },
      },
    },
  });
}

function setMetrics(metrics) {
  metricLatest.textContent = metrics.latest ?? 0;
  metricPeak.textContent = metrics.peak ?? 0;
  metricAvg.textContent = Number(metrics.average ?? 0).toFixed(1);
  metricFrames.textContent = metrics.total_frames ?? 0;
}

function renderAlerts(alerts) {
  alertsList.innerHTML = "";
  if (!alerts.length) {
    const empty = document.createElement("div");
    empty.className = "alert";
    empty.textContent = "No alerts right now.";
    alertsList.appendChild(empty);
    return;
  }
  alerts.slice(0, 12).forEach((alert) => {
    const card = document.createElement("div");
    card.className = `alert ${alert.severity}`;
    card.innerHTML = `
      <h3>${alert.type}</h3>
      <p>Frame ${alert.frame} · People ${alert.person_count}</p>
    `;
    alertsList.appendChild(card);
  });
}

function renderLog(rows) {
  logBody.innerHTML = "";
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.frame}</td>
      <td>${row.person_count}</td>
    `;
    logBody.appendChild(tr);
  });
}

function updateChart(rows) {
  const labels = rows.map((row) => row.frame);
  const values = rows.map((row) => row.person_count);
  chart.data.labels = labels;
  chart.data.datasets[0].data = values;
  chart.update("none");
}

async function fetchJSON(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }
  return res.json();
}

async function refresh() {
  const threshold = Number(thresholdInput.value || 6);
  const spikeDelta = Number(spikeDeltaInput.value || 3);

  try {
    const [metrics, alerts, log] = await Promise.all([
      fetchJSON("/api/metrics"),
      fetchJSON(`/api/alerts?threshold=${threshold}&spike_delta=${spikeDelta}`),
      fetchJSON("/api/log?limit=120"),
    ]);
    setMetrics(metrics);
    renderAlerts(alerts);
    renderLog(log);
    updateChart(log);
    if (debugStatus) {
      const latest = metrics.latest ?? 0;
      const frames = metrics.total_frames ?? 0;
      debugStatus.textContent = `Status: ok · latest ${latest} · frames ${frames}`;
    }
  } catch (err) {
    console.error(err);
    if (debugStatus) {
      debugStatus.textContent = `Status: error · ${err.message ?? err}`;
    }
  }
}

function scheduleRefresh() {
  if (!autoRefresh) return;
  const delay = Math.max(1, Number(refreshInput.value || 2)) * 1000;
  setTimeout(async () => {
    await refresh();
    scheduleRefresh();
  }, delay);
}

toggleAuto.addEventListener("click", () => {
  autoRefresh = !autoRefresh;
  toggleAuto.textContent = autoRefresh ? "Auto: On" : "Auto: Off";
  if (autoRefresh) scheduleRefresh();
});

initChart();
refresh().then(scheduleRefresh);
