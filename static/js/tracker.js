/**
 * CrumbTail Customer Live Map & Tracking Logic
 * - Leaflet map initialization
 * - Smooth marker interpolation (lerp) via requestAnimationFrame
 * - Monotonic packet check
 * - Dual-instance WebSocket integration with instant failover
 */

let map;
let riderMarker = null;
let restaurantMarker = null;
let destinationMarker = null;
let routeLine = null;

let currentOrderId = "order_demo_101";
let assignedRiderId = "rider_alpha";
let wsClient = null;

// Interpolation state
let currentPos = { lat: 12.9716, lon: 77.5946 };
let targetPos = { lat: 12.9716, lon: 77.5946 };
let animStartTime = 0;
const animDuration = 950; // ms (smooth interpolation for 1 Hz updates)
let isAnimating = false;
let clientLastSeq = -1;

const STAGES = ['placed', 'accepted', 'preparing', 'picked_up', 'delivered'];

document.addEventListener('DOMContentLoaded', () => {
    initMap();
    setupOrder(currentOrderId);
    bindControls();
});

function initMap() {
    // Bengaluru coordinates
    map = L.map('map', {
        zoomControl: true,
        attributionControl: false
    }).setView([12.9716, 77.5946], 14);

    // OpenStreetMap dark / standard tiles
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19
    }).addTo(map);

    // Restaurant marker (Indiranagar / MG Road)
    restaurantMarker = L.marker([12.9750, 77.5900], {
        title: "Kitchen Hub",
        icon: L.divIcon({
            className: 'custom-pin',
            html: '<div style="background:#f59e0b; width:16px; height:16px; border-radius:50%; border:3px solid #fff; box-shadow:0 0 10px #f59e0b;"></div>'
        })
    }).addTo(map).bindPopup("<strong>Kitchen Hub</strong><br>Restaurant Origin");

    // Destination marker (Customer)
    destinationMarker = L.marker([12.9650, 77.6050], {
        title: "Customer Destination",
        icon: L.divIcon({
            className: 'custom-pin',
            html: '<div style="background:#38bdf8; width:16px; height:16px; border-radius:50%; border:3px solid #fff; box-shadow:0 0 10px #38bdf8;"></div>'
        })
    }).addTo(map).bindPopup("<strong>Customer Address</strong><br>Delivery Destination");

    // Rider marker (motorcycle)
    riderMarker = L.marker([12.9716, 77.5946], {
        title: "Delivery Partner",
        icon: L.divIcon({
            className: 'rider-pin',
            html: '<div style="background:#22c55e; width:22px; height:22px; border-radius:50%; border:3px solid #fff; display:flex; align-items:center; justify-content:center; box-shadow:0 0 12px #22c55e;"><span style="font-size:12px;">🛵</span></div>'
        })
    }).addTo(map).bindPopup("<strong>Rider</strong><br>Status: In Transit");

    // Route polyline
    routeLine = L.polyline([
        [12.9750, 77.5900],
        [12.9716, 77.5946],
        [12.9650, 77.6050]
    ], { color: '#38bdf8', weight: 4, opacity: 0.6, dashArray: '6, 8' }).addTo(map);
}

function updateStepper(status) {
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
}

/**
 * requestAnimationFrame Linear Interpolation (lerp)
 * Prevents abrupt jumps and ensures marker glides smoothly across streets.
 */
function animateMarker(timestamp) {
    if (!animStartTime) animStartTime = timestamp;
    const elapsed = timestamp - animStartTime;
    const progress = Math.min(elapsed / animDuration, 1.0);

    // Lerp coordinates
    const lat = currentPos.lat + (targetPos.lat - currentPos.lat) * progress;
    const lon = currentPos.lon + (targetPos.lon - currentPos.lon) * progress;

    if (riderMarker) {
        riderMarker.setLatLng([lat, lon]);
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
    // Client-side monotonic safeguard (Packet drop if seq <= clientLastSeq)
    if (seq !== undefined && seq !== null) {
        const parsedSeq = parseInt(seq, 10);
        if (!isNaN(parsedSeq)) {
            if (parsedSeq <= clientLastSeq) {
                console.warn(`[MAP] Dropped out-of-order packet: seq ${parsedSeq} <= ${clientLastSeq}`);
                return;
            }
            clientLastSeq = parsedSeq;
            document.getElementById('val-seq').textContent = parsedSeq;
        }
    }

    document.getElementById('val-coords').textContent = `${lat.toFixed(4)}° N, ${lon.toFixed(4)}° E`;

    currentPos = riderMarker ? riderMarker.getLatLng() : { lat, lon };
    targetPos = { lat, lon };
    animStartTime = 0;

    if (!isAnimating) {
        isAnimating = true;
        requestAnimationFrame(animateMarker);
    }
}

function setupOrder(orderId) {
    currentOrderId = orderId;
    document.getElementById('val-order-id').textContent = orderId;
    document.getElementById('val-rider-id').textContent = assignedRiderId;

    if (wsClient) {
        wsClient.close();
    }

    // Connect via CrumbTail resilient client
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

function handleWsMessage(data) {
    // 1. Handle live location packet
    if (data.type === 'location' || (data.lat !== undefined && data.lon !== undefined)) {
        const lat = parseFloat(data.lat);
        const lon = parseFloat(data.lon);
        const seq = data.seq;
        setRiderTargetCoordinates(lat, lon, seq);
    } 
    // 2. Handle Redis Stream replay packet
    else if (data.type === 'replay' && data.event) {
        const ev = data.event;
        if (ev.lat && ev.lon) {
            setRiderTargetCoordinates(parseFloat(ev.lat), parseFloat(ev.lon), ev.seq);
        }
        if (ev.status) {
            updateStepper(ev.status);
        }
    }
    // 3. Handle order lifecycle status change
    else if (data.type === 'status_change' || data.status) {
        const status = data.status || data.to_status;
        if (status) {
            updateStepper(status);
        }
    }
}

function updateWsBadge(status, info) {
    const badge = document.getElementById('ws-badge');
    const text = document.getElementById('ws-status-text');
    const portEl = document.getElementById('val-port');

    badge.className = 'status-badge';
    if (status === 'connected') {
        badge.classList.add('connected');
        text.textContent = `Live: Port ${info.port}`;
        portEl.textContent = info.port;
    } else if (status === 'connecting' || status === 'reconnecting') {
        badge.classList.add('connecting');
        text.textContent = `Failover to ${info.port}...`;
        portEl.textContent = info.port;
    } else {
        badge.classList.add('disconnected');
        text.textContent = 'Disconnected';
    }
}

function showFailoverBanner(port, durationMs) {
    const banner = document.getElementById('failover-banner');
    document.getElementById('failover-time').textContent = durationMs || '< 500';
    banner.classList.add('show');
    setTimeout(() => {
        banner.classList.remove('show');
    }, 4000);
}

function bindControls() {
    // 1. Place New Order & Assign Rider
    document.getElementById('btn-create-order').addEventListener('click', async () => {
        try {
            // First register sample rider nearby if needed
            await fetch('/riders/rider_alpha/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ lat: 12.9750, lon: 77.5900 })
            });

            // Create order
            const res = await fetch('/orders', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    customer_id: "cust_" + Math.floor(Math.random() * 900 + 100),
                    restaurant_id: "rest_kitchen_hub"
                })
            });
            const orderData = await res.json();
            
            // Accept & assign rider
            const assignRes = await fetch(`/orders/${orderData.id}/status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    status: 'accepted',
                    latitude: 12.9750,
                    longitude: 77.5900
                })
            });
            const assignedData = await assignRes.json();
            
            assignedRiderId = (assignedData.order && assignedData.order.rider_id) || assignedData.rider_id || "rider_alpha";
            setupOrder(orderData.id);
            updateStepper('accepted');
            alert(`Order ${orderData.id} created & Rider ${assignedRiderId} assigned atomically!`);
        } catch (err) {
            console.error('Order creation error:', err);
            alert('Failed to create order: ' + err.message);
        }
    });

    // 2. Simulate Rider Movement (10 GPS updates)
    document.getElementById('btn-simulate-route').addEventListener('click', async () => {
        const startLat = 12.9750, startLon = 77.5900;
        const endLat = 12.9650, endLon = 77.6050;
        const steps = 10;
        
        for (let i = 1; i <= steps; i++) {
            const progress = i / steps;
            const lat = startLat + (endLat - startLat) * progress;
            const lon = startLon + (endLon - startLon) * progress;
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

        // Finish delivery
        await fetch(`/orders/${currentOrderId}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'delivered' })
        });
        updateStepper('delivered');
        document.getElementById('eta-badge').textContent = '🏁 Delivered';
        document.getElementById('eta-badge').style.color = 'var(--success)';
    });

    // 3. Cancel Order Test (409 validation)
    document.getElementById('btn-cancel-order').addEventListener('click', async () => {
        try {
            const res = await fetch(`/orders/${currentOrderId}/status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: 'cancelled' })
            });
            if (res.status === 409) {
                const err = await res.json();
                alert(`⚠️ 409 Conflict: ${err.detail || 'Cannot cancel order in current state!'}`);
            } else if (res.ok) {
                alert(`Order ${currentOrderId} successfully cancelled.`);
                document.getElementById('eta-badge').textContent = '🚫 Cancelled';
                document.getElementById('eta-badge').style.color = 'var(--danger)';
            }
        } catch (e) {
            alert('Cancel failed: ' + e.message);
        }
    });

    // 4. Force Failover
    document.getElementById('btn-force-failover').addEventListener('click', () => {
        if (wsClient) {
            wsClient.forceReconnect();
        }
    });
}

