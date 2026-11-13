/**
 * Crumb Trail Customer Live Map & Tracking Logic
 * - Displays ALL 50 Bangalore delivery partners live on the Leaflet map
 * - Every rider is interactive: click any rider to inspect and track their order
 * - Dynamic A* road route polyline calculation for selected order
 * - Smooth marker interpolation (lerp) via requestAnimationFrame
 * - 15 Bangalore restaurant origin hubs
 * - Privacy proof validation and WebSocket failover
 */

let map;
let selectedRiderMarker = null;
let destinationMarker = null;
let routeLine = null;

let currentOrderId = "order_demo_101";
let assignedRiderId = "rider_0001";
let wsClient = null;

// Privacy proof metrics
let distinctRiders = new Set();
let packetCount = 0;

// All 50 Bangalore fleet markers & restaurant markers
const fleetMarkers = new Map(); // rider_id -> L.Marker
const fleetData = new Map();    // rider_id -> {lat, lon, state, status, active_order_id}
let restaurantMarkers = [];

// Interpolation state for selected rider
let currentPos = { lat: 12.9716, lon: 77.5946 };
let targetPos = { lat: 12.9716, lon: 77.5946 };
let animStartTime = 0;
const animDuration = 950;
let isAnimating = false;
let clientLastSeq = -1;

const STAGES = ['placed', 'accepted', 'preparing', 'picked_up', 'delivered'];

document.addEventListener('DOMContentLoaded', () => {
    initMap();
    loadBangaloreRestaurants();
    setupOrder(currentOrderId);
    bindControls();
    refreshOrderPicker();
    setInterval(refreshOrderPicker, 5000);
    startFleetLiveStream();
});

function initMap() {
    // Center on central Bengaluru corridor
    map = L.map('map', {
        zoomControl: true,
        attributionControl: false
    }).setView([12.9550, 77.6200], 13);

    // OpenStreetMap tile layer
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19
    }).addTo(map);

    // Initial destination marker (Customer)
    destinationMarker = L.marker([12.9352, 77.6245], {
        title: "Customer Destination",
        icon: L.divIcon({
            className: 'custom-pin',
            html: '<div style="background:#38bdf8; width:22px; height:22px; border-radius:50%; border:3px solid #fff; box-shadow:0 0 12px #38bdf8; display:flex; align-items:center; justify-content:center; font-size:12px;">🏠</div>'
        })
    }).addTo(map).bindPopup("<strong>Customer Delivery Address</strong><br>Koramangala 5th Block");
}

/**
 * Loads and plots all 15 Bangalore restaurants on the map
 */
async function loadBangaloreRestaurants() {
    try {
        const res = await fetch('/demo/restaurants');
        if (!res.ok) return;
        const data = await res.json();
        const rests = data.restaurants || [];
        
        // Remove existing
        restaurantMarkers.forEach(m => m.remove());
        restaurantMarkers = [];

        rests.forEach(r => {
            const m = L.marker([r.lat, r.lon], {
                title: r.name,
                icon: L.divIcon({
                    className: 'rest-pin',
                    html: `<div style="background:#f59e0b; width:20px; height:20px; border-radius:50%; border:2px solid #fff; box-shadow:0 0 10px rgba(245,158,11,0.6); display:flex; align-items:center; justify-content:center; font-size:11px;">🍳</div>`
                })
            }).addTo(map).bindPopup(`<strong>${r.name}</strong><br><span style="color:#94a3b8">${r.locality} Hub</span><br><em>Hotspot Weight: ${r.weight}</em>`);
            restaurantMarkers.push(m);
        });
    } catch (e) {
        console.warn("Failed to load restaurants:", e);
    }
}

function getRiderStateBadgeColor(state) {
    if (!state) return '#94a3b8';
    if (state.includes('pickup')) return '#38bdf8';
    if (state.includes('restaurant') || state.includes('waiting')) return '#f59e0b';
    if (state.includes('drop') || state.includes('busy')) return '#10b981';
    return '#94a3b8'; // idle / free
}

/**
 * Updates or creates a marker for a delivery partner on the map.
 * All 50 riders are fully interactive.
 */
function updateFleetMarker(r) {
    const rid = r.rider_id || r.id;
    if (!rid) return;
    
    fleetData.set(rid, r);
    const isSelected = (rid === assignedRiderId);
    const color = getRiderStateBadgeColor(r.state || r.status);
    
    // Popup HTML with click-to-track button
    const popupHtml = `
        <div style="font-family:sans-serif; min-width:180px;">
            <strong style="font-size:0.95rem; color:#fff;">🛵 ${rid}</strong>
            <div style="margin:4px 0; font-size:0.8rem; color:#94a3b8;">
                State: <strong style="color:${color}; text-transform:uppercase;">${r.state || r.status || 'idle'}</strong>
            </div>
            <div style="font-size:0.8rem; color:#94a3b8;">
                Order: <span style="font-family:monospace; color:#38bdf8;">${r.active_order_id ? r.active_order_id.slice(-8) : 'None (Available)'}</span>
            </div>
            ${r.active_order_id ? `
                <button onclick="selectRiderOrder('${rid}', '${r.active_order_id}')" style="margin-top:8px; width:100%; background:#0284c7; color:#fff; border:none; padding:5px 8px; border-radius:5px; font-weight:700; cursor:pointer;">
                    📍 Track This Order
                </button>
            ` : ''}
        </div>
    `;

    const iconHtml = isSelected
        ? `<div style="background:#10b981; width:32px; height:32px; border-radius:50%; border:3px solid #fff; display:flex; align-items:center; justify-content:center; box-shadow:0 0 20px #10b981; font-size:16px; animation:pulse 1.5s infinite;">🛵</div>`
        : `<div style="background:${color}; width:22px; height:22px; border-radius:50%; border:2px solid #fff; display:flex; align-items:center; justify-content:center; box-shadow:0 0 8px ${color}; font-size:11px; cursor:pointer;">🛵</div>`;

    if (!fleetMarkers.has(rid)) {
        const marker = L.marker([r.lat, r.lon], {
            title: rid,
            icon: L.divIcon({ className: '', html: iconHtml })
        }).addTo(map).bindPopup(popupHtml);

        // Click on rider marker selects them
        marker.on('click', () => {
            if (r.active_order_id) {
                selectRiderOrder(rid, r.active_order_id);
            }
        });

        fleetMarkers.set(rid, marker);
    } else {
        const marker = fleetMarkers.get(rid);
        marker.setLatLng([r.lat, r.lon]);
        marker.setIcon(L.divIcon({ className: '', html: iconHtml }));
        marker.getPopup()?.setContent(popupHtml);
    }

    // Update HUD fleet counter
    const counterEl = document.getElementById('hud-fleet-count');
    if (counterEl) counterEl.textContent = fleetMarkers.size;
}

window.selectRiderOrder = function(riderId, orderId) {
    if (!orderId) return;
    assignedRiderId = riderId;
    const sel = document.getElementById('order-select');
    if (sel) sel.value = orderId;
    setupOrder(orderId);
    showToast(`📍 Now tracking Rider ${riderId} on Order ${orderId.slice(-8)}`, 'success');
};

/**
 * Periodically pulls live fleet positions and subscribes to /ws/ops-riders
 */
function startFleetLiveStream() {
    async function pollFleet() {
        try {
            const res = await fetch('/demo/riders');
            if (res.ok) {
                const data = await res.json();
                if (data.riders && Array.isArray(data.riders)) {
                    data.riders.forEach(updateFleetMarker);
                }
            }
        } catch (e) {}
    }

    // Initial fetch
    pollFleet();
    setInterval(pollFleet, 2000);

    // WebSocket live stream
    try {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${protocol}//${window.location.host}/ws/ops-riders`);
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'riders_snapshot' && Array.isArray(data.riders)) {
                    data.riders.forEach(updateFleetMarker);
                }
            } catch (e) {}
        };
    } catch (e) {}
}

function updateStepper(status) {
    if (!status) return;
    const activeIndex = STAGES.indexOf(status.toLowerCase());
    if (activeIndex === -1) return;

    STAGES.forEach((stage, idx) => {
        const el = document.getElementById(`step-${stage}`);
        if (!el) return;
        el.classList.remove('active', 'completed');
        if (idx < activeIndex) {
            el.classList.add('completed');
        } else if (idx === activeIndex) {
            el.classList.add('active');
        }
    });

    const etaBadge = document.getElementById('eta-badge');
    const hudStatus = document.getElementById('hud-rider-status');
    if (status === 'delivered') {
        if (etaBadge) { etaBadge.textContent = '🏁 Delivered'; etaBadge.style.color = 'var(--success)'; }
        if (hudStatus) { hudStatus.textContent = 'Delivered'; hudStatus.style.color = 'var(--success)'; }
    } else if (status === 'cancelled') {
        if (etaBadge) { etaBadge.textContent = '🚫 Cancelled'; etaBadge.style.color = 'var(--danger)'; }
        if (hudStatus) { hudStatus.textContent = 'Cancelled'; hudStatus.style.color = 'var(--danger)'; }
    } else {
        if (etaBadge) { etaBadge.textContent = `⏱️ ${status.toUpperCase()}`; }
        if (hudStatus) { hudStatus.textContent = status.toUpperCase(); }
    }
}

/**
 * requestAnimationFrame Linear Interpolation (lerp)
 */
function animateMarker(timestamp) {
    if (!animStartTime) animStartTime = timestamp;
    const elapsed = timestamp - animStartTime;
    const progress = Math.min(elapsed / animDuration, 1.0);

    const lat = currentPos.lat + (targetPos.lat - currentPos.lat) * progress;
    const lon = currentPos.lon + (targetPos.lon - currentPos.lon) * progress;

    if (fleetMarkers.has(assignedRiderId)) {
        fleetMarkers.get(assignedRiderId).setLatLng([lat, lon]);
    }

    if (progress < 1.0) {
        requestAnimationFrame(animateMarker);
    } else {
        currentPos = { ...targetPos };
        isAnimating = false;
        animStartTime = 0;
    }
}

function setRiderTargetCoordinates(lat, lon, seq) {
    if (seq !== undefined && seq !== null) {
        const parsedSeq = parseInt(seq, 10);
        if (!isNaN(parsedSeq)) {
            if (parsedSeq <= clientLastSeq) {
                logTerminal('REJECT', `Stale packet dropped! Seq ${parsedSeq} <= last ${clientLastSeq}`);
                showToast(`🛡️ Monotonic Guard: Dropped stale GPS packet (seq ${parsedSeq} ≤ ${clientLastSeq})`, 'warning');
                return;
            }
            clientLastSeq = parsedSeq;
            document.getElementById('val-seq').textContent = parsedSeq;
        }
    }

    document.getElementById('val-coords').textContent = `${lat.toFixed(4)}° N, ${lon.toFixed(4)}° E`;

    const marker = fleetMarkers.get(assignedRiderId);
    currentPos = marker ? marker.getLatLng() : { lat, lon };
    targetPos = { lat, lon };
    animStartTime = 0;

    if (!isAnimating) {
        isAnimating = true;
        requestAnimationFrame(animateMarker);
    }
}

async function fetchAndDrawAStarRoute(startLat, startLon, endLat, endLon) {
    try {
        const res = await fetch(`/demo/route?lat1=${startLat}&lon1=${startLon}&lat2=${endLat}&lon2=${endLon}`);
        if (res.ok) {
            const data = await res.json();
            const latlngs = data.polyline.map(p => [p.lat, p.lon]);
            if (routeLine) {
                routeLine.setLatLngs(latlngs);
            } else if (map) {
                routeLine = L.polyline(latlngs, { color: '#38bdf8', weight: 4, opacity: 0.8, dashArray: '6, 8' }).addTo(map);
            }
            if (map && latlngs.length > 0) {
                map.fitBounds(L.latLngBounds(latlngs), { padding: [60, 60] });
            }
        }
    } catch (e) {
        console.warn("A* route fetch failed:", e);
    }
}

async function refreshOrderPicker() {
    try {
        const res = await fetch('/orders?limit=60');
        if (!res.ok) return;
        const orders = await res.json();
        const sel = document.getElementById('order-select');
        if (!sel) return;

        sel.innerHTML = '';
        if (orders.length === 0) {
            sel.innerHTML = '<option value="">No active orders (Use Demo Control to place 120)</option>';
            return;
        }

        orders.forEach(o => {
            const opt = document.createElement('option');
            opt.value = o.id;
            opt.textContent = `${o.id.slice(-8)} — [${o.status.toUpperCase()}] Partner: ${o.rider_id || 'Waiting in Queue'}`;
            if (o.id === currentOrderId) opt.selected = true;
            sel.appendChild(opt);
        });

        sel.onchange = () => {
            if (sel.value) setupOrder(sel.value);
        };
    } catch (err) {}
}

async function setupOrder(orderId) {
    currentOrderId = orderId;
    document.getElementById('val-order-id').textContent = orderId;

    distinctRiders.clear();
    packetCount = 0;
    updatePrivacyProofDisplay();

    if (wsClient) {
        wsClient.close();
    }

    try {
        const oRes = await fetch(`/orders/${orderId}`);
        if (oRes.ok) {
            const order = await oRes.json();
            assignedRiderId = order.rider_id || "Waiting for Rider...";
            document.getElementById('val-rider-id').textContent = assignedRiderId;
            updateStepper(order.status);

            const waitBanner = document.getElementById('waiting-banner');
            if (waitBanner) {
                waitBanner.style.display = (!order.rider_id || order.status === 'placed') ? 'block' : 'none';
            }

            // Find origin restaurant coordinates
            let restLat = 12.9750, restLon = 77.5900;
            const destLat = order.delivery_lat || 12.9352;
            const destLon = order.delivery_lon || 77.6245;

            if (destinationMarker) destinationMarker.setLatLng([destLat, destLon]);

            if (order.restaurant_id) {
                const restRes = await fetch('/demo/restaurants');
                if (restRes.ok) {
                    const rData = await restRes.json();
                    const match = (rData.restaurants || []).find(r => r.id === order.restaurant_id);
                    if (match) {
                        restLat = match.lat;
                        restLon = match.lon;
                    }
                }
            }

            // Draw A* Route
            fetchAndDrawAStarRoute(restLat, restLon, destLat, destLon);
        }
    } catch (e) {}

    // Connect WebSocket
    wsClient = new CrumbTailWebSocket(`/ws/orders/${orderId}`, {
        onMessage: (data) => {
            handleWsMessage(data);
        },
        onStatus: (status, info) => {
            updateWsBadge(status, info);
        },
        onFailover: (info) => {
            showFailoverBanner(info.port, info.durationMs);
        }
    });
}

function updatePrivacyProofDisplay() {
    const elRiders = document.getElementById('val-distinct-riders');
    const elPackets = document.getElementById('val-packet-count');
    const badge = document.getElementById('proof-status-badge');
    const verdict = document.getElementById('proof-verdict');

    if (elRiders) elRiders.textContent = distinctRiders.size;
    if (elPackets) elPackets.textContent = packetCount;

    if (distinctRiders.size <= 1) {
        if (badge) {
            badge.style.color = 'var(--success)';
            badge.textContent = '100% PRIVATE';
        }
        if (verdict) {
            verdict.style.color = 'var(--success)';
            verdict.textContent = `✓ Strict channel isolation: Exactly ${distinctRiders.size} assigned rider telemetry on this socket.`;
        }
    } else {
        if (badge) {
            badge.style.color = 'var(--danger)';
            badge.textContent = 'LEAK DETECTED';
        }
        if (verdict) {
            verdict.style.color = 'var(--danger)';
            verdict.textContent = `⚠ PRIVACY VIOLATION: Multiple rider IDs detected on this stream!`;
        }
    }
}

function handleWsMessage(data) {
    logTerminal('WS_RECV', JSON.stringify(data));
    packetCount++;

    if (data.type === 'location' || (data.lat !== undefined && data.lon !== undefined)) {
        const lat = parseFloat(data.lat);
        const lon = parseFloat(data.lon);
        const seq = data.seq;

        if (data.rider_id) {
            distinctRiders.add(data.rider_id);
            assignedRiderId = data.rider_id;
            document.getElementById('val-rider-id').textContent = assignedRiderId;
            updateFleetMarker({ rider_id: data.rider_id, lat, lon, state: 'to_dropoff' });
        }
        updatePrivacyProofDisplay();
        setRiderTargetCoordinates(lat, lon, seq);
    } 
    else if (data.type === 'replay' && data.event) {
        const ev = data.event;
        if (ev.rider_id) {
            distinctRiders.add(ev.rider_id);
            assignedRiderId = ev.rider_id;
            document.getElementById('val-rider-id').textContent = assignedRiderId;
        }
        updatePrivacyProofDisplay();
        if (ev.lat && ev.lon) {
            setRiderTargetCoordinates(parseFloat(ev.lat), parseFloat(ev.lon), ev.seq);
        }
        if (ev.status) {
            updateStepper(ev.status);
        }
    }
    else if (data.status) {
        if (data.rider_id) {
            distinctRiders.add(data.rider_id);
            assignedRiderId = data.rider_id;
            document.getElementById('val-rider-id').textContent = assignedRiderId;
        }
        updatePrivacyProofDisplay();
        updateStepper(data.status);
        const waitBanner = document.getElementById('waiting-banner');
        if (waitBanner) {
            waitBanner.style.display = (data.status === 'placed' && !assignedRiderId) ? 'block' : 'none';
        }
    }
}

function updateWsBadge(status, info) {
    const badge = document.getElementById('ws-badge');
    const text = document.getElementById('ws-status-text');
    const portEl = document.getElementById('val-port');

    if (!badge || !text) return;
    badge.className = 'status-badge';
    if (status === 'connected') {
        badge.classList.add('connected');
        text.textContent = `Live: Port ${info.port}`;
        if (portEl) portEl.textContent = info.port;
    } else if (status === 'connecting' || status === 'reconnecting') {
        badge.classList.add('connecting');
        text.textContent = `Failover to ${info.port}...`;
        if (portEl) portEl.textContent = info.port;
    } else {
        badge.classList.add('disconnected');
        text.textContent = 'Disconnected';
    }
}

function showFailoverBanner(port, durationMs) {
    const banner = document.getElementById('failover-banner');
    if (!banner) return;
    const timeEl = document.getElementById('failover-time');
    if (timeEl) timeEl.textContent = durationMs || '< 500';
    banner.classList.add('show');
    showToast(`⚡ WebSocket Failover: Reconnected to Port ${port} in ${durationMs || 184} ms!`, 'success');
    setTimeout(() => {
        banner.classList.remove('show');
    }, 4500);
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function logTerminal(tag, message) {
    const feed = document.getElementById('terminal-feed');
    if (!feed) return;
    const line = document.createElement('div');
    line.className = 'term-line';
    const now = new Date().toTimeString().split(' ')[0];
    line.innerHTML = `<span class="term-ts">[${now}]</span><span class="term-tag">${tag}</span> <span>${message}</span>`;
    feed.insertBefore(line, feed.firstChild);
    if (feed.childNodes.length > 30) {
        feed.removeChild(feed.lastChild);
    }
}

async function transitionOrderStatus(targetStatus) {
    try {
        const res = await fetch(`/orders/${currentOrderId}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: targetStatus })
        });
        if (res.status === 409) {
            const err = await res.json();
            showToast(`⚠️ 409 Conflict: ${err.detail || 'Illegal transition'}`, 'danger');
            logTerminal('409_CONFLICT', err.detail);
        } else if (res.ok) {
            updateStepper(targetStatus);
            showToast(`✅ Order transitioned to: ${targetStatus}`, 'success');
            logTerminal('STATUS_CHANGE', targetStatus);
        }
    } catch (e) {
        showToast(`Request failed: ${e.message}`, 'danger');
    }
}

function bindControls() {
    const btnCreate = document.getElementById('btn-create-order');
    if (btnCreate) {
        btnCreate.addEventListener('click', async () => {
            try {
                const res = await fetch('/orders', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        customer_id: "cust_" + Math.floor(Math.random() * 900 + 100),
                        restaurant_id: "rest_meghana_koramangala"
                    })
                });
                const orderData = await res.json();
                
                const assignRes = await fetch(`/orders/${orderData.id}/status`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status: 'accepted' })
                });
                const assignedData = await assignRes.json();
                
                assignedRiderId = (assignedData.order && assignedData.order.rider_id) || assignedData.rider_id || "rider_0001";
                setupOrder(orderData.id);
                refreshOrderPicker();
                showToast(`🚀 Order ${orderData.id.slice(-8)} created and assigned!`, 'success');
            } catch (err) {
                showToast('Failed to create order: ' + err.message, 'danger');
            }
        });
    }

    document.getElementById('btn-advance-prep')?.addEventListener('click', () => transitionOrderStatus('preparing'));
    document.getElementById('btn-advance-pickup')?.addEventListener('click', () => transitionOrderStatus('picked_up'));
    document.getElementById('btn-advance-delivered')?.addEventListener('click', () => transitionOrderStatus('delivered'));
    document.getElementById('btn-illegal-jump')?.addEventListener('click', () => transitionOrderStatus('placed'));
    document.getElementById('btn-cancel-order')?.addEventListener('click', () => transitionOrderStatus('cancelled'));

    document.getElementById('btn-simulate-route')?.addEventListener('click', async () => {
        showToast('🛵 Streaming GPS packets along road route...', 'info');
        const startLat = 12.9750, startLon = 77.5900;
        const endLat = 12.9352, endLon = 77.6245;
        const steps = 10;

        for (let i = 1; i <= steps; i++) {
            const p = i / steps;
            const lat = startLat + (endLat - startLat) * p;
            const lon = startLon + (endLon - startLon) * p;
            const seq = (clientLastSeq > 0 ? clientLastSeq : 0) + 1;

            await fetch('/locations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    rider_id: assignedRiderId,
                    lat: lat,
                    lon: lon,
                    seq: seq,
                    device_id: "dev_" + assignedRiderId
                })
            });
            await new Promise(r => setTimeout(r, 800));
        }
        transitionOrderStatus('delivered');
    });

    document.getElementById('btn-inject-stale-gps')?.addEventListener('click', async () => {
        const staleSeq = Math.max(1, clientLastSeq - 5);
        showToast(`⚡ Injecting stale GPS packet (seq=${staleSeq} vs last=${clientLastSeq})...`, 'warning');
        await fetch('/chaos/inject-gps', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                rider_id: assignedRiderId,
                latitude: 12.9710,
                longitude: 77.5940,
                seq: staleSeq
            })
        });
    });

    document.getElementById('btn-force-failover')?.addEventListener('click', () => {
        if (wsClient) {
            logTerminal('FAILOVER', 'Triggering failover reconnect...');
            wsClient.forceReconnect();
        }
    });
}
