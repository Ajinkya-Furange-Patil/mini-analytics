/**
 * Mini Analytics Lightweight Tracker Snippet (< 2 KB)
 * Privacy-respecting, zero-fingerprinting, first-party cookie based visitor analytics.
 */
(function() {
    'use strict';

    // Locate tracker script element to extract config attributes
    const scriptEl = document.currentScript || (function() {
        const scripts = document.getElementsByTagName('script');
        return scripts[scripts.length - 1];
    })();

    const siteId = (scriptEl && scriptEl.getAttribute('data-site-id')) || 'default';
    const endpoint = (scriptEl && scriptEl.getAttribute('data-endpoint')) || '/collect';

    // Cryptographic UUIDv4 generator for event-level idempotency
    function generateUUID() {
        if (typeof crypto !== 'undefined' && crypto.randomUUID) {
            return crypto.randomUUID();
        }
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    // Sanitize path (strip query string and fragment)
    function getCleanPath() {
        try {
            return window.location.pathname || '/';
        } catch (e) {
            return '/';
        }
    }

    // Extract referrer origin only (omit paths and sensitive query tokens)
    function getReferrerOrigin() {
        if (!document.referrer) return '';
        try {
            const refUrl = new URL(document.referrer);
            // Don't report self-referrals within the same site as external referrers
            if (refUrl.origin === window.location.origin) {
                return '';
            }
            return refUrl.origin;
        } catch (e) {
            return '';
        }
    }

    // Extract strictly allowlisted campaign parameters
    function getCampaignParams() {
        const params = {};
        try {
            const searchParams = new URLSearchParams(window.location.search);
            const allowlist = ['utm_source', 'utm_medium', 'utm_campaign'];
            for (let i = 0; i < allowlist.length; i++) {
                const key = allowlist[i];
                const val = searchParams.get(key);
                if (val && val.length < 100) {
                    params[key] = val;
                }
            }
        } catch (e) {}
        return params;
    }

    // Construct event payload
    const eventId = generateUUID();
    const payload = Object.assign({
        event_id: eventId,
        site_id: siteId,
        page_path: getCleanPath(),
        referrer_origin: getReferrerOrigin(),
        client_time: new Date().toISOString(),
        event_type: 'pageview'
    }, getCampaignParams());

    // Dispatch event with credentials: 'include' to ensure first-party signed cookie is handled
    function sendEvent(retryCount) {
        const jsonStr = JSON.stringify(payload);

        if (typeof fetch === 'function') {
            fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: jsonStr,
                credentials: 'include',
                keepalive: true
            }).catch(function(err) {
                // If network failed and retry limit not reached, retry with the SAME event_id
                if (retryCount > 0) {
                    setTimeout(function() {
                        sendEvent(retryCount - 1);
                    }, 2000);
                }
            });
        } else if (navigator.sendBeacon) {
            const blob = new Blob([jsonStr], { type: 'application/json' });
            navigator.sendBeacon(endpoint, blob);
        }
    }

    // Execute tracking once DOM is ready or immediately
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            sendEvent(1);
        });
    } else {
        sendEvent(1);
    }
})();
