/**
 * CrumbTail Resilient Dual-Instance WebSocket Client
 * 
 * Guarantees:
 * 1. Zero HTTP polling: all live updates pushed via WebSockets.
 * 2. Instant Failover (< 500ms): If Instance A (port 8000) drops, automatically
 *    reconnects to Instance B (port 8001) without page reload.
 * 3. Stream Replay: On reconnect, sends 'hello' handshake with last seen event ID
 *    to replay any missed frames from Redis Stream.
 * 4. Deduplication: Drops duplicate or out-of-order sequence packets.
 */

class CrumbTailWebSocket {
    constructor(path, options = {}) {
        this.path = path.startsWith('/') ? path : `/${path}`;
        this.options = options;
        
        // Instances endpoints (supports custom or default 8000 & 8001)
        const host = window.location.hostname || 'localhost';
        const currentPort = window.location.port || '8000';
        
        // Secondary instance is the other port
        const peerPort = (currentPort === '8000') ? '8001' : '8000';
        
        this.endpoints = [
            `ws://${host}:${currentPort}${this.path}`,
            `ws://${host}:${peerPort}${this.path}`
        ];
        
        this.currentEndpointIndex = 0;
        this.ws = null;
        this.lastEventId = '0-0';
        this.lastSeq = -1;
        this.isClosedManually = false;
        this.reconnectAttempts = 0;
        this.disconnectTime = null;
        
        // Callbacks
        this.onMessageCallback = options.onMessage || (() => {});
        this.onStatusCallback = options.onStatus || (() => {});
        this.onFailoverCallback = options.onFailover || (() => {});

        this.connect();
    }

    getCurrentUrl() {
        return this.endpoints[this.currentEndpointIndex];
    }

    getCurrentPort() {
        const url = this.getCurrentUrl();
        const match = url.match(/:(\d+)\//);
        return match ? match[1] : '8000';
    }

    connect() {
        if (this.isClosedManually) return;

        const targetUrl = this.getCurrentUrl();
        this.onStatusCallback('connecting', { url: targetUrl, port: this.getCurrentPort() });

        try {
            this.ws = new WebSocket(targetUrl);
        } catch (err) {
            console.error('[WS] Connection exception:', err);
            this.handleFailover();
            return;
        }

        this.ws.onopen = () => {
            let failoverDuration = null;
            if (this.disconnectTime) {
                failoverDuration = Math.round(performance.now() - this.disconnectTime);
                this.disconnectTime = null;
            }

            this.reconnectAttempts = 0;
            this.onStatusCallback('connected', {
                url: targetUrl,
                port: this.getCurrentPort(),
                failoverMs: failoverDuration
            });

            if (failoverDuration !== null) {
                this.onFailoverCallback({
                    targetUrl: targetUrl,
                    port: this.getCurrentPort(),
                    durationMs: failoverDuration
                });
            }

            // Send handshake to catch up on missed events from Redis Stream
            const handshake = {
                action: 'hello',
                last_event_id: this.lastEventId
            };
            this.ws.send(JSON.stringify(handshake));
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                
                // Track last event id for stream replay catchup
                if (data.stream_id) {
                    this.lastEventId = data.stream_id;
                } else if (data.event_id) {
                    this.lastEventId = data.event_id;
                }

                // Check monotonic sequence if GPS packet
                const seq = (data.seq !== undefined) ? data.seq : (data.event && data.event.seq !== undefined ? data.event.seq : null);
                if (seq !== null) {
                    const parsedSeq = parseInt(seq, 10);
                    if (!isNaN(parsedSeq)) {
                        if (parsedSeq <= this.lastSeq) {
                            console.warn(`[WS CLIENT] Dropped out-of-order/stale seq: ${parsedSeq} <= ${this.lastSeq}`);
                            return; // Marker never moves backward
                        }
                        this.lastSeq = parsedSeq;
                    }
                }

                this.onMessageCallback(data);
            } catch (err) {
                // Raw text or non-json message
                this.onMessageCallback({ type: 'raw', text: event.data });
            }
        };

        this.ws.onerror = (err) => {
            console.warn('[WS] Error encountered on:', targetUrl, err);
            // Let onclose handle the failover
        };

        this.ws.onclose = (event) => {
            if (this.isClosedManually) {
                this.onStatusCallback('disconnected', { url: targetUrl });
                return;
            }

            if (!this.disconnectTime) {
                this.disconnectTime = performance.now();
            }

            this.onStatusCallback('reconnecting', {
                url: targetUrl,
                port: this.getCurrentPort(),
                reconnectAttempts: this.reconnectAttempts
            });

            this.handleFailover();
        };
    }

    handleFailover() {
        if (this.isClosedManually) return;

        // Switch to the other instance immediately (Instance A <-> Instance B)
        this.currentEndpointIndex = (this.currentEndpointIndex + 1) % this.endpoints.length;
        this.reconnectAttempts++;

        // Fast reconnect under 100ms for seamless failover (< 500ms target)
        const delay = this.reconnectAttempts <= 3 ? 50 : Math.min(1000, 100 * Math.pow(1.5, this.reconnectAttempts));
        
        setTimeout(() => {
            if (!this.isClosedManually) {
                this.connect();
            }
        }, delay);
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(typeof data === 'string' ? data : JSON.stringify(data));
            return true;
        }
        return false;
    }

    close() {
        this.isClosedManually = true;
        if (this.ws) {
            this.ws.close();
        }
    }

    forceReconnect() {
        if (this.ws) {
            this.disconnectTime = performance.now();
            this.ws.close();
        }
    }
}

