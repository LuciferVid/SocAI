/**
 * SOC Dashboard — live WebSocket client with Chart.js visualizations.
 * Connects to the FastAPI WebSocket at /ws/live and renders events
 * in real-time: table, alert feed, charts, and stat counters.
 */

(() => {
    'use strict';

    // ─── State ───
    const state = {
        ws: null,
        events: [],
        alerts: [],
        scores: [],         // rolling window for chart
        timestamps: [],
        eventCounts: [],
        totalEvents: 0,
        totalAlerts: 0,
        recentScores: [],
        connected: false,
        maxTableRows: 200,
        maxChartPoints: 60,
        eventsPerSecond: 0,
        lastCountCheck: Date.now(),
        lastCountValue: 0,
    };

    // ─── DOM refs ───
    const dom = {
        status: document.getElementById('pipeline-status'),
        clock: document.getElementById('clock'),
        statEvents: document.getElementById('stat-events'),
        statAlerts: document.getElementById('stat-alerts'),
        statBlocked: document.getElementById('stat-blocked'),
        statAvgScore: document.getElementById('stat-avg-score'),
        statScoreBar: document.getElementById('stat-score-bar'),
        statEventsTrend: document.getElementById('stat-events-trend'),
        alertList: document.getElementById('alert-list'),
        alertBadge: document.getElementById('alert-count-badge'),
        eventTbody: document.getElementById('event-tbody'),
        ipFilter: document.getElementById('ip-filter'),
        scoreFilter: document.getElementById('score-filter'),
        btnRetrain: document.getElementById('btn-retrain'),
    };

    // ─── Chart setup ───
    const ctx = document.getElementById('timeline-chart').getContext('2d');
    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Events/s',
                    data: [],
                    borderColor: '#6366f1',
                    backgroundColor: 'rgba(99, 102, 241, 0.1)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    borderWidth: 2,
                    yAxisID: 'y',
                },
                {
                    label: 'Anomaly Score',
                    data: [],
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.08)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    borderWidth: 2,
                    yAxisID: 'y1',
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: {
                    labels: { color: '#9ca3af', font: { size: 11 } },
                },
            },
            scales: {
                x: {
                    ticks: { color: '#6b7280', font: { size: 10 }, maxTicksLimit: 10 },
                    grid: { color: 'rgba(255,255,255,0.03)' },
                },
                y: {
                    position: 'left',
                    ticks: { color: '#6b7280', font: { size: 10 } },
                    grid: { color: 'rgba(255,255,255,0.03)' },
                    title: { display: true, text: 'Events/s', color: '#6b7280' },
                },
                y1: {
                    position: 'right',
                    min: 0, max: 1,
                    ticks: { color: '#6b7280', font: { size: 10 } },
                    grid: { drawOnChartArea: false },
                    title: { display: true, text: 'Score', color: '#6b7280' },
                },
            },
        },
    });

    // ─── WebSocket ───
    function connect() {
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${proto}://${location.host}/ws/live`;

        state.ws = new WebSocket(wsUrl);

        state.ws.onopen = () => {
            state.connected = true;
            dom.status.innerHTML = '<span class="status-dot online"></span> Live';

        };

        state.ws.onclose = () => {
            state.connected = false;
            dom.status.innerHTML = '<span class="status-dot offline"></span> Disconnected';

            setTimeout(connect, 3000);
        };

        state.ws.onerror = () => {
            // reconnection handled by onclose
        };

        state.ws.onmessage = (msg) => {
            try {
                const event = JSON.parse(msg.data);
                handleEvent(event);
            } catch (_) {
            }
        };
    }

    // ─── Event handler ───
    function handleEvent(event) {
        state.totalEvents++;
        state.recentScores.push(event.anomaly_score || 0);
        if (state.recentScores.length > 500) state.recentScores.shift();

        // check filters before adding to table
        const ipFilter = dom.ipFilter.value.trim();
        const minScore = parseFloat(dom.scoreFilter.value) || 0;

        const passFilter = (
            (!ipFilter || (event.source_ip && event.source_ip.includes(ipFilter))) &&
            (event.anomaly_score || 0) >= minScore
        );

        if (passFilter) {
            addTableRow(event);
        }

        // if it's an alert-worthy event, add to alert feed
        if ((event.anomaly_score || 0) >= 0.7) {
            state.totalAlerts++;
            addAlertItem(event);
        }

        updateStats();
    }

    // ─── Table ───
    function addTableRow(event) {
        const tr = document.createElement('tr');
        const score = event.anomaly_score || 0;

        if (score >= 0.7) tr.classList.add('high-score');

        const time = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : '--';
        const scoreCls = score >= 0.9 ? 'critical' : score >= 0.7 ? 'high' : score >= 0.5 ? 'medium' : 'low';

        tr.innerHTML = `
            <td>${time}</td>
            <td class="col-ip">${event.source_ip || '—'}</td>
            <td class="col-method">${event.method || '—'}</td>
            <td class="col-path" title="${event.path || ''}">${event.path || '—'}</td>
            <td>${event.status_code || '—'}</td>
            <td><span class="score-badge ${scoreCls}">${score.toFixed(3)}</span></td>
            <td>${event.attack_type ? `<span class="type-badge">${event.attack_type}</span>` : '—'}</td>
        `;

        // prepend so newest is at top
        dom.eventTbody.prepend(tr);

        // trim old rows
        while (dom.eventTbody.children.length > state.maxTableRows) {
            dom.eventTbody.removeChild(dom.eventTbody.lastChild);
        }
    }

    // ─── Alert feed ───
    function addAlertItem(event) {
        const empty = dom.alertList.querySelector('.alert-empty');
        if (empty) empty.remove();

        const score = event.anomaly_score || 0;
        const severity = score >= 0.95 ? 'critical' : score >= 0.85 ? 'high' : score >= 0.7 ? 'medium' : 'low';
        const time = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : '--';

        const div = document.createElement('div');
        div.className = 'alert-item';
        div.innerHTML = `
            <div class="alert-severity ${severity}"></div>
            <div class="alert-content">
                <div class="alert-type">${event.attack_type || 'anomaly'}</div>
                <div class="alert-meta">
                    <span class="alert-ip">${event.source_ip}</span> · ${event.path || '/'} · ${time}
                </div>
            </div>
            <div class="alert-score">${score.toFixed(3)}</div>
        `;

        dom.alertList.prepend(div);

        // keep last 50 alerts
        while (dom.alertList.children.length > 50) {
            dom.alertList.removeChild(dom.alertList.lastChild);
        }

        dom.alertBadge.textContent = state.totalAlerts;
    }

    // ─── Stats ───
    function updateStats() {
        dom.statEvents.textContent = state.totalEvents.toLocaleString();
        dom.statAlerts.textContent = state.totalAlerts;

        const avg = state.recentScores.length > 0
            ? state.recentScores.reduce((a, b) => a + b, 0) / state.recentScores.length
            : 0;
        dom.statAvgScore.textContent = avg.toFixed(3);
        dom.statScoreBar.style.width = `${Math.min(avg * 100, 100)}%`;
    }

    // ─── Chart updates (every second) ───
    function updateChart() {
        const now = new Date().toLocaleTimeString();
        const elapsed = (Date.now() - state.lastCountCheck) / 1000;
        const eps = Math.round((state.totalEvents - state.lastCountValue) / elapsed);
        state.lastCountCheck = Date.now();
        state.lastCountValue = state.totalEvents;

        dom.statEventsTrend.textContent = `+${eps}/s`;

        const avg = state.recentScores.length > 0
            ? state.recentScores.reduce((a, b) => a + b, 0) / state.recentScores.length
            : 0;

        chart.data.labels.push(now);
        chart.data.datasets[0].data.push(eps);
        chart.data.datasets[1].data.push(avg);

        if (chart.data.labels.length > state.maxChartPoints) {
            chart.data.labels.shift();
            chart.data.datasets[0].data.shift();
            chart.data.datasets[1].data.shift();
        }

        chart.update('none');  // skip animation for performance
    }

    // ─── Clock ───
    function updateClock() {
        dom.clock.textContent = new Date().toLocaleTimeString();
    }

    // ─── Retrain button ───
    dom.btnRetrain.addEventListener('click', async () => {
        dom.btnRetrain.disabled = true;
        dom.btnRetrain.textContent = '⏳ Training…';
        try {
            const resp = await fetch('/api/retrain/', { method: 'POST' });
            const data = await resp.json();
            dom.btnRetrain.textContent = '✅ Done';
            setTimeout(() => {
                dom.btnRetrain.textContent = '🔄 Retrain';
                dom.btnRetrain.disabled = false;
            }, 3000);
        } catch (e) {
            dom.btnRetrain.textContent = '❌ Failed';
            setTimeout(() => {
                dom.btnRetrain.textContent = '🔄 Retrain';
                dom.btnRetrain.disabled = false;
            }, 3000);
        }
    });

    // ─── Load initial stats from API ───
    async function loadInitialStats() {
        try {
            const [eventsResp, alertsResp] = await Promise.all([
                fetch('/api/events/count'),
                fetch('/api/alerts/stats'),
            ]);
            if (eventsResp.ok) {
                const data = await eventsResp.json();
                state.totalEvents = data.count || 0;
            }
            if (alertsResp.ok) {
                const data = await alertsResp.json();
                state.totalAlerts = data.active_alerts || 0;
            }
            updateStats();
        } catch (_) {
        }
    }

    // ─── Boot ───
    connect();
    loadInitialStats();
    setInterval(updateChart, 1000);
    setInterval(updateClock, 1000);
    updateClock();
})();
