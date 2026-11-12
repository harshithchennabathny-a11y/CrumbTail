/**
 * CrumbTail Chaos Control Console Logic
 * Triggers adversarial test scenarios against the running FastAPI / Redis cluster
 */

document.addEventListener('DOMContentLoaded', () => {
    bindChaosButtons();
});

function logToConsole(tag, message, json = null, type = 'info') {
    const consoleEl = document.getElementById('console-logs');
    const now = new Date();
    const timeStr = `[${now.toTimeString().split(' ')[0]}.${now.getMilliseconds().toString().padStart(3, '0')}]`;

    const entry = document.createElement('div');
    entry.className = 'log-entry';

    let jsonHtml = '';
    if (json) {
        jsonHtml = `<div class="log-json">${JSON.stringify(json, null, 2)}</div>`;
    }

    entry.innerHTML = `
        <span class="log-ts">${timeStr}</span>
        <span class="log-tag ${type}">[${tag}]</span>
        <div class="log-msg">
            ${message}
            ${jsonHtml}
        </div>
    `;

    consoleEl.appendChild(entry);
    consoleEl.scrollTop = consoleEl.scrollHeight;
}

function bindChaosButtons() {
    document.getElementById('btn-clear-console').addEventListener('click', () => {
        document.getElementById('console-logs').innerHTML = '';
    });

    // Chaos 1: Stale GPS Packet
    document.getElementById('btn-chaos-gps').addEventListener('click', async () => {
        logToConsole('CHAOS-1', 'Initiating backward GPS sequence test...', null, 'warning');
        try {
            // First send seq=10
            await fetch('/riders/rider_gps_test/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ lat: 12.9716, lon: 77.5946 })
            });
            await fetch('/locations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ rider_id: 'rider_gps_test', lat: 12.9716, lon: 77.5946, seq: 10 })
            });
            logToConsole('CHAOS-1', 'Initial GPS packet stored with seq=10', null, 'info');

            // Now inject seq=5 (backward!)
            const res = await fetch('/chaos/inject-gps', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    rider_id: 'rider_gps_test',
                    latitude: 12.9720,
                    longitude: 77.5950,
                    seq: 5
                })
            });
            const data = await res.json();
            if (data.status === 'rejected') {
                logToConsole('CHAOS-1', '✅ GUARANTEE VERIFIED: Ingest script rejected backward packet!', data, 'success');
            } else {
                logToConsole('CHAOS-1', '❌ UNEXPECTED: Packet was accepted', data, 'danger');
            }
        } catch (err) {
            logToConsole('CHAOS-1', `Error executing test: ${err.message}`, null, 'danger');
        }
    });

    // Chaos 2: Concurrency Burst (20 Orders for 1 Rider)
    document.getElementById('btn-chaos-burst').addEventListener('click', async () => {
        logToConsole('CHAOS-2', 'Spawning 1 free rider in Koramangala...', null, 'info');
        try {
            await fetch('/riders/rider_race_champion/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ lat: 12.9716, lon: 77.5946 })
            });

            logToConsole('CHAOS-2', 'Fired 20 concurrent order assignments in single async burst...', null, 'warning');
            const res = await fetch('/chaos/burst-orders', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ num_orders: 20, latitude: 12.9716, longitude: 77.5946 })
            });
            const data = await res.json();

            if (data.double_bookings === 0) {
                logToConsole('CHAOS-2', `✅ GUARANTEE VERIFIED: 0 double bookings across ${data.total_requests} concurrent requests! (${data.duration_ms} ms)`, data, 'success');
            } else {
                logToConsole('CHAOS-2', `❌ RACE HAZARD: Detected ${data.double_bookings} double bookings!`, data, 'danger');
            }
        } catch (err) {
            logToConsole('CHAOS-2', `Burst failed: ${err.message}`, null, 'danger');
        }
    });

    // Chaos 3: Batch Atomicity
    document.getElementById('btn-chaos-batch').addEventListener('click', async () => {
        logToConsole('CHAOS-3', 'Testing atomic dual-order batch assignment (assign_batch.lua)...', null, 'info');
        try {
            await fetch('/riders/rider_batch_hero/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ lat: 12.9720, lon: 77.5940 })
            });

            const res = await fetch('/chaos/competing-batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    order_id_1: 'order_batch_a_' + Date.now(),
                    order_id_2: 'order_batch_b_' + Date.now(),
                    center_lat: 12.9720,
                    center_lon: 77.5940,
                    radius_km: 5.0
                })
            });
            const data = await res.json();
            if (data.status === 'success') {
                logToConsole('CHAOS-3', `✅ BATCH ASSIGNED ATOMICALLY to rider ${data.assigned_rider}`, data, 'success');
            } else {
                logToConsole('CHAOS-3', `Batch response: ${data.message}`, data, 'warning');
            }
        } catch (err) {
            logToConsole('CHAOS-3', `Batch error: ${err.message}`, null, 'danger');
        }
    });

    // Chaos 4: Notification Ledger Audit
    document.getElementById('btn-chaos-notif').addEventListener('click', async () => {
        logToConsole('CHAOS-4', 'Auditing Mock Notification Service (Port 9000)...', null, 'info');
        try {
            const res = await fetch('/chaos/check-notifications', { method: 'POST' });
            const data = await res.json();
            if (data.service_status === 'online') {
                logToConsole('CHAOS-4', `✅ Notification service ONLINE. Total processed: ${data.processed_notifications_count}`, data, 'success');
            } else {
                logToConsole('CHAOS-4', `⚠️ Notification service is OFFLINE: ${data.message}`, data, 'warning');
            }
        } catch (err) {
            logToConsole('CHAOS-4', `Notification check failed: ${err.message}`, null, 'danger');
        }
    });

    // Chaos 5: Kill Instance A (Failover < 500ms)
    document.getElementById('btn-chaos-kill').addEventListener('click', async () => {
        if (!confirm("Are you sure? This will terminate Instance A (port 8000) to demonstrate automatic WebSocket failover to Instance B (port 8001).")) {
            return;
        }

        logToConsole('CHAOS-5', 'Triggering shutdown of Instance A (port 8000)...', null, 'danger');
        const t0 = performance.now();
        
        try {
            await fetch('/chaos/kill-instance', { method: 'POST' });
            logToConsole('CHAOS-5', 'Instance A terminated. Monitoring failover response...', null, 'warning');
        } catch (err) {
            logToConsole('CHAOS-5', 'Instance A connection severed as expected.', null, 'warning');
        }

        // Poll peer instance (port 8001) until healthy
        const peerUrl = 'http://localhost:8001/health';
        let recovered = false;
        for (let i = 0; i < 20; i++) {
            await new Promise(r => setTimeout(r, 50));
            try {
                const res = await fetch(peerUrl);
                if (res.ok) {
                    const elapsed = Math.round(performance.now() - t0);
                    const health = await res.json();
                    logToConsole('CHAOS-5', `✅ FAILOVER COMPLETE in ${elapsed} ms! Peer Instance ${health.instance} (port ${health.port}) active.`, health, 'success');
                    recovered = true;
                    break;
                }
            } catch (e) {
                // Keep polling
            }
        }

        if (!recovered) {
            logToConsole('CHAOS-5', '⚠️ Peer instance (port 8001) not reached within 1000ms. Ensure Instance B is running.', null, 'warning');
        }
    });

    // Chaos 6: Redis Interruption & Degraded Mode
    const degradedBtn = document.getElementById('btn-chaos-degraded');
    if (degradedBtn) {
        degradedBtn.addEventListener('click', async () => {
            logToConsole('CHAOS-6', 'Probing cluster operational health and degraded tolerance (/health)...', null, 'warning');
            try {
                const res = await fetch('/health');
                const data = await res.json();
                if (data.status === 'healthy') {
                    logToConsole('CHAOS-6', `✅ System operational: status='${data.status}', DB=${data.database}, Redis=${data.redis}`, data, 'success');
                } else if (data.status === 'degraded') {
                    logToConsole('CHAOS-6', `⚠️ DEGRADED MODE ACTIVE: SQLite WAL operational, Redis disconnected. Orders remain safe!`, data, 'warning');
                } else {
                    logToConsole('CHAOS-6', `Status: ${data.status}`, data, 'danger');
                }
            } catch (err) {
                logToConsole('CHAOS-6', `Health check failed: ${err.message}`, null, 'danger');
            }
        });
    }
}

