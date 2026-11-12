/**
 * CrumbTail Restaurant Order Kanban Board Logic
 * - Zero HTTP polling: updates pushed via WebSockets (ws://localhost:8000/8001 /ws/restaurant)
 * - HTML5 Drag & Drop state progression
 * - Enforces state machine: returns HTTP 409 Conflict on illegal moves and snaps card back
 */

let draggedCard = null;
let sourceColumn = null;
let wsClient = null;

const COLUMNS = ['placed', 'accepted', 'preparing', 'picked_up', 'delivered', 'cancelled'];

document.addEventListener('DOMContentLoaded', () => {
    loadInitialOrders();
    initWebSocket();
    setupDropZones();
    bindHeaderControls();
});

async function loadInitialOrders() {
    try {
        const res = await fetch('/orders');
        if (!res.ok) return;
        const orders = await res.json();
        
        // Clear columns
        COLUMNS.forEach(c => {
            const list = document.getElementById(`list-${c}`);
            if (list) list.innerHTML = '';
        });

        orders.forEach(renderOrderCard);
        updateCounts();
    } catch (err) {
        console.error('Failed to load initial orders:', err);
    }
}

function initWebSocket() {
    wsClient = new CrumbTailWebSocket('/ws/restaurant', {
        onMessage: (data) => {
            handleBoardEvent(data);
        },
        onStatus: (status, info) => {
            const statusEl = document.getElementById('ws-status');
            if (status === 'connected') {
                statusEl.textContent = `● Live WS Connected (Port ${info.port})`;
                statusEl.style.color = 'var(--success)';
            } else if (status === 'reconnecting') {
                statusEl.textContent = `● Reconnecting to Port ${info.port}...`;
                statusEl.style.color = 'var(--warning)';
            } else {
                statusEl.textContent = `● Disconnected`;
                statusEl.style.color = 'var(--danger)';
            }
        }
    });
}

function handleBoardEvent(data) {
    const eventType = data.type || data.event;
    if ((eventType === 'order_created' || eventType === 'order') && data.order) {
        renderOrderCard(data.order);
        updateCounts();
    } else if (eventType === 'status_change' || eventType === 'status' || data.status) {
        const orderId = data.order_id || (data.order && data.order.id);
        const toStatus = data.to_status || data.status || (data.order && data.order.status);
        if (!orderId || !toStatus) return;

        let card = document.getElementById(`card-${orderId}`);
        const targetList = document.getElementById(`list-${toStatus}`);
        if (!card && data.order) {
            renderOrderCard(data.order);
            card = document.getElementById(`card-${orderId}`);
        }
        if (card && targetList && card.parentElement !== targetList) {
            targetList.appendChild(card);
            card.dataset.status = toStatus;
            const riderId = data.rider_id || (data.order && data.order.rider_id);
            if (riderId) {
                let riderBadge = card.querySelector('.card-rider');
                if (!riderBadge) {
                    riderBadge = document.createElement('div');
                    riderBadge.className = 'card-rider';
                    card.appendChild(riderBadge);
                }
                riderBadge.textContent = `🛵 Rider: ${riderId}`;
            }
            updateCounts();
        }
    }
}

function renderOrderCard(order) {
    const list = document.getElementById(`list-${order.status}`);
    if (!list) return;

    let card = document.getElementById(`card-${order.id}`);
    if (!card) {
        card = document.createElement('div');
        card.id = `card-${order.id}`;
        card.className = 'order-card';
        card.draggable = true;
        
        card.addEventListener('dragstart', handleDragStart);
        card.addEventListener('dragend', handleDragEnd);
    }

    card.dataset.orderId = order.id;
    card.dataset.status = order.status;

    let riderHtml = '';
    if (order.rider_id) {
        riderHtml = `<div class="card-rider">🛵 Rider: ${order.rider_id}</div>`;
    }

    card.innerHTML = `
        <div class="card-id">${order.id}</div>
        <div class="card-cust">Customer: ${order.customer_id}</div>
        ${riderHtml}
    `;

    list.appendChild(card);
}

function updateCounts() {
    COLUMNS.forEach(c => {
        const list = document.getElementById(`list-${c}`);
        const countBadge = document.getElementById(`count-${c}`);
        if (list && countBadge) {
            countBadge.textContent = list.children.length;
        }
    });
}

function handleDragStart(e) {
    draggedCard = this;
    sourceColumn = this.parentElement.id.replace('list-', '');
    this.classList.add('dragging');
    e.dataTransfer.setData('text/plain', this.dataset.orderId);
    e.dataTransfer.effectAllowed = 'move';
}

function handleDragEnd(e) {
    this.classList.remove('dragging');
    document.querySelectorAll('.cards-list').forEach(l => l.classList.remove('drag-over'));
}

function setupDropZones() {
    COLUMNS.forEach(col => {
        const list = document.getElementById(`list-${col}`);
        if (!list) return;

        list.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            list.classList.add('drag-over');
        });

        list.addEventListener('dragleave', () => {
            list.classList.remove('drag-over');
        });

        list.addEventListener('drop', async (e) => {
            e.preventDefault();
            list.classList.remove('drag-over');

            if (!draggedCard) return;

            const targetStatus = col;
            const fromStatus = sourceColumn;
            const orderId = draggedCard.dataset.orderId;

            if (targetStatus === fromStatus) return;

            // Move card optimistically
            list.appendChild(draggedCard);
            updateCounts();

            // Send transition request to backend
            try {
                const res = await fetch(`/orders/${orderId}/status`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        status: targetStatus,
                        latitude: 12.9716,
                        longitude: 77.5946
                    })
                });

                if (res.status === 409) {
                    const err = await res.json();
                    // Snap back!
                    const originalList = document.getElementById(`list-${fromStatus}`);
                    if (originalList) originalList.appendChild(draggedCard);
                    updateCounts();

                    // Shake card and display conflict toast
                    draggedCard.classList.add('shake');
                    setTimeout(() => draggedCard.classList.remove('shake'), 600);
                    showToast(`⚠️ 409 Conflict: ${err.detail || 'Illegal order state transition!'}`);
                    return;
                }

                if (!res.ok) {
                    throw new Error(`Server returned ${res.status}`);
                }

                const updated = await res.json();
                draggedCard.dataset.status = targetStatus;
                const riderId = (updated.order && updated.order.rider_id) || updated.rider_id;
                if (riderId) {
                    let riderBadge = draggedCard.querySelector('.card-rider');
                    if (!riderBadge) {
                        riderBadge = document.createElement('div');
                        riderBadge.className = 'card-rider';
                        draggedCard.appendChild(riderBadge);
                    }
                    riderBadge.textContent = `🛵 Rider: ${riderId}`;
                }
            } catch (err) {
                // Network or other error: snap back
                const originalList = document.getElementById(`list-${fromStatus}`);
                if (originalList) originalList.appendChild(draggedCard);
                updateCounts();
                showToast(`❌ Error: ${err.message}`);
            }
        });
    });
}

function showToast(message) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `<span>${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 400);
    }, 4000);
}

function bindHeaderControls() {
    document.getElementById('btn-add-order').addEventListener('click', async () => {
        try {
            const randCust = "cust_" + Math.floor(Math.random() * 900 + 100);
            const res = await fetch('/orders', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    customer_id: randCust,
                    restaurant_id: "rest_kitchen_hub"
                })
            });
            const newOrder = await res.json();
            renderOrderCard(newOrder);
            updateCounts();
        } catch (err) {
            showToast('Failed to create order: ' + err.message);
        }
    });
}

