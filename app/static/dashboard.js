/**
 * Mini Analytics Dashboard Controller
 * Vanilla JS with SVG chart rendering, dynamic API polling, and settings management.
 */

(function () {
    'use strict';

    let currentSiteId = 'default';
    let currentRange = '30d';
    let overviewData = null;
    let trendsData = [];

    // Elements
    const siteSelect = document.getElementById('siteSelect');
    const refreshBtn = document.getElementById('refreshBtn');
    const rangeTabs = document.querySelectorAll('[data-range]');
    const settingsForm = document.getElementById('settingsForm');
    const purgeBtn = document.getElementById('purgeBtn');
    const toastEl = document.getElementById('toast');

    function showToast(message, isError = false) {
        if (!toastEl) return;
        toastEl.textContent = message;
        toastEl.style.borderColor = isError ? 'var(--accent-rose)' : 'var(--accent-emerald)';
        toastEl.style.display = 'block';
        setTimeout(() => {
            toastEl.style.display = 'none';
        }, 3500);
    }

    function formatNumber(num) {
        if (num === null || num === undefined) return '0';
        return Number(num).toLocaleString();
    }

    // Load Overview Metrics
    async function loadOverview() {
        try {
            const res = await fetch(`/api/overview?site_id=${encodeURIComponent(currentSiteId)}`);
            if (!res.ok) throw new Error('Failed to load overview data');
            overviewData = await res.json();
            renderOverviewCards(overviewData);
        } catch (err) {
            console.error('Error fetching overview:', err);
            showToast('Failed to load overview metrics', true);
        }
    }

    function renderOverviewCards(data) {
        // Today
        document.getElementById('todayBrowsers').textContent = formatNumber(data.today.unique_browsers);
        document.getElementById('todayPageViews').textContent = formatNumber(data.today.page_views);
        document.getElementById('todayIps').textContent = formatNumber(data.today.unique_ips);

        // Week
        document.getElementById('weekBrowsers').textContent = formatNumber(data.current_week.unique_browsers);
        document.getElementById('weekPageViews').textContent = formatNumber(data.current_week.page_views);
        document.getElementById('weekIps').textContent = formatNumber(data.current_week.unique_ips);

        // Month
        document.getElementById('monthBrowsers').textContent = formatNumber(data.current_month.unique_browsers);
        document.getElementById('monthPageViews').textContent = formatNumber(data.current_month.page_views);
        document.getElementById('monthIps').textContent = formatNumber(data.current_month.unique_ips);

        // All-time & Breakdown
        document.getElementById('totalPageViews').textContent = formatNumber(data.total_page_views);
        
        // Breakdown (Today)
        const newCount = data.today.new_browsers || 0;
        const retCount = data.today.returning_browsers || 0;
        const totalToday = newCount + retCount;
        const newPct = totalToday > 0 ? Math.round((newCount / totalToday) * 100) : 0;
        const retPct = totalToday > 0 ? (100 - newPct) : 0;

        document.getElementById('newVisitorsCount').textContent = `${formatNumber(newCount)} (${newPct}%)`;
        document.getElementById('returningVisitorsCount').textContent = `${formatNumber(retCount)} (${retPct}%)`;
        document.getElementById('newVisitorsBar').style.width = `${newPct}%`;
        document.getElementById('returningVisitorsBar').style.width = `${retPct}%`;

        // Bot / Excluded stats
        const botViews = data.today.bot_page_views || 0;
        document.getElementById('botEventsCount').textContent = formatNumber(botViews);

        // Last Event Time
        const lastEventEl = document.getElementById('lastEventTime');
        if (data.last_event_received) {
            const dt = new Date(data.last_event_received);
            lastEventEl.textContent = dt.toLocaleTimeString();
        } else {
            lastEventEl.textContent = 'None yet';
        }
    }

    // Load Trends
    async function loadTrends() {
        try {
            const res = await fetch(`/api/trends?site_id=${encodeURIComponent(currentSiteId)}&days=30`);
            if (!res.ok) throw new Error('Failed to load trends data');
            const data = await res.json();
            trendsData = data.trends || [];
            renderTrendChart(trendsData);
        } catch (err) {
            console.error('Error fetching trends:', err);
        }
    }

    // Render SVG Trend Chart
    function renderTrendChart(trends) {
        const container = document.getElementById('trendChartContainer');
        if (!container) return;
        if (!trends || trends.length === 0) {
            container.innerHTML = '<div class="empty-state">No trend data available for this range.</div>';
            return;
        }

        const width = container.clientWidth || 700;
        const height = 240;
        const padding = { top: 20, right: 20, bottom: 40, left: 45 };
        const chartW = width - padding.left - padding.right;
        const chartH = height - padding.top - padding.bottom;

        // Max values
        const maxViews = Math.max(...trends.map(t => Math.max(t.page_views, t.unique_browsers)), 5);
        const barWidth = Math.max(chartW / trends.length - 4, 3);

        let svgHtml = `<svg width="100%" height="100%" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="overflow: visible;">`;

        // Grid lines (3 horizontal lines)
        for (let i = 0; i <= 3; i++) {
            const yVal = padding.top + (chartH / 3) * i;
            const labelVal = Math.round(maxViews - (maxViews / 3) * i);
            svgHtml += `
                <line x1="${padding.left}" y1="${yVal}" x2="${width - padding.right}" y2="${yVal}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="3,3" />
                <text x="${padding.left - 8}" y="${yVal + 4}" fill="#64748b" font-size="10" text-anchor="end">${labelVal}</text>
            `;
        }

        // Bars for page_views and points/lines for unique_browsers
        let linePoints = [];

        trends.forEach((t, i) => {
            const x = padding.left + (i * (chartW / trends.length)) + (chartW / trends.length) / 2;
            const barH = (t.page_views / maxViews) * chartH;
            const barY = padding.top + chartH - barH;

            const browserH = (t.unique_browsers / maxViews) * chartH;
            const browserY = padding.top + chartH - browserH;
            linePoints.push(`${x},${browserY}`);

            // Tooltip title
            const tipText = `${t.date}: ${t.page_views} views, ${t.unique_browsers} unique browsers, ${t.unique_ips} IPs`;

            // Bar for Page Views
            svgHtml += `
                <rect x="${x - barWidth / 2}" y="${barY}" width="${barWidth}" height="${barH}" 
                      fill="url(#barGradient)" rx="2" opacity="${t.is_partial ? '0.6' : '0.9'}">
                    <title>${tipText}</title>
                </rect>
            `;

            // X-axis date labels (show every 5th or 6th date)
            if (i % Math.ceil(trends.length / 6) === 0 || i === trends.length - 1) {
                const shortDate = t.date.slice(5); // MM-DD
                svgHtml += `
                    <text x="${x}" y="${height - 12}" fill="#64748b" font-size="10" text-anchor="middle">
                        ${shortDate}${t.is_partial ? '*' : ''}
                    </text>
                `;
            }
        });

        // Unique browsers line
        if (linePoints.length > 1) {
            svgHtml += `
                <polyline fill="none" stroke="#06b6d4" stroke-width="2.5" points="${linePoints.join(' ')}" />
            `;
            // Points
            trends.forEach((t, i) => {
                const x = padding.left + (i * (chartW / trends.length)) + (chartW / trends.length) / 2;
                const browserY = padding.top + chartH - (t.unique_browsers / maxViews) * chartH;
                svgHtml += `
                    <circle cx="${x}" cy="${browserY}" r="3" fill="#06b6d4">
                        <title>${t.date}: ${t.unique_browsers} Unique Browsers</title>
                    </circle>
                `;
            });
        }

        // Gradients definition
        svgHtml += `
            <defs>
                <linearGradient id="barGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#6366f1" />
                    <stop offset="100%" stop-color="#4338ca" />
                </linearGradient>
            </defs>
        </svg>`;

        container.innerHTML = svgHtml;
    }

    // Load Top Pages
    async function loadPages() {
        const tableBody = document.getElementById('pagesTableBody');
        try {
            const res = await fetch(`/api/pages?site_id=${encodeURIComponent(currentSiteId)}&range=${currentRange}`);
            if (!res.ok) throw new Error('Failed to load pages');
            const data = await res.json();
            const pages = data.pages || [];

            if (pages.length === 0) {
                tableBody.innerHTML = '<tr><td colspan="3" class="empty-state">No page visits recorded in this range.</td></tr>';
                return;
            }

            tableBody.innerHTML = pages.map(p => `
                <tr>
                    <td class="mono-cell" title="${p.path}">${escapeHtml(p.path)}</td>
                    <td class="num-cell">${formatNumber(p.views)}</td>
                    <td class="num-cell" style="color: var(--accent-cyan);">${formatNumber(p.unique_browsers)}</td>
                </tr>
            `).join('');
        } catch (err) {
            console.error('Error fetching pages:', err);
            tableBody.innerHTML = '<tr><td colspan="3" class="empty-state">Error loading top pages.</td></tr>';
        }
    }

    // Load Referrers
    async function loadReferrers() {
        const tableBody = document.getElementById('referrersTableBody');
        try {
            const res = await fetch(`/api/referrers?site_id=${encodeURIComponent(currentSiteId)}&range=${currentRange}`);
            if (!res.ok) throw new Error('Failed to load referrers');
            const data = await res.json();
            const referrers = data.referrers || [];

            if (referrers.length === 0) {
                tableBody.innerHTML = '<tr><td colspan="3" class="empty-state">No external referrers observed. (Direct traffic or stripped referrer)</td></tr>';
                return;
            }

            tableBody.innerHTML = referrers.map(r => `
                <tr>
                    <td class="mono-cell" title="${r.referrer}">${escapeHtml(r.referrer)}</td>
                    <td class="num-cell">${formatNumber(r.views)}</td>
                    <td class="num-cell" style="color: var(--accent-cyan);">${formatNumber(r.unique_browsers)}</td>
                </tr>
            `).join('');
        } catch (err) {
            console.error('Error fetching referrers:', err);
            tableBody.innerHTML = '<tr><td colspan="3" class="empty-state">Error loading referrers.</td></tr>';
        }
    }

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // Full Refresh
    function refreshAll() {
        loadOverview();
        loadTrends();
        loadPages();
        loadReferrers();
    }

    // Event Handlers
    if (siteSelect) {
        siteSelect.addEventListener('change', (e) => {
            currentSiteId = e.target.value;
            refreshAll();
        });
    }

    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            refreshAll();
            showToast('Refreshed analytics data');
        });
    }

    rangeTabs.forEach(tab => {
        tab.addEventListener('click', (e) => {
            rangeTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentRange = tab.getAttribute('data-range');
            loadPages();
            loadReferrers();
        });
    });

    // Settings Form Submission
    if (settingsForm) {
        settingsForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(settingsForm);
            try {
                const res = await fetch('/admin/settings', {
                    method: 'POST',
                    body: formData,
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Failed to save settings');
                showToast('Settings saved successfully!');
                refreshAll();
            } catch (err) {
                showToast(err.message, true);
            }
        });
    }

    // Purge Action
    if (purgeBtn) {
        purgeBtn.addEventListener('click', async () => {
            if (!confirm('Are you sure you want to purge event records older than the configured retention policy?')) {
                return;
            }
            const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;
            try {
                const res = await fetch('/admin/purge', {
                    method: 'POST',
                    headers: { 'X-CSRF-Token': csrfToken },
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Failed to purge data');
                showToast(data.message || 'Purge completed successfully');
                refreshAll();
            } catch (err) {
                showToast(err.message, true);
            }
        });
    }

    // Initial Load & Auto-poll every 30s
    refreshAll();
    setInterval(refreshAll, 30000);

    // Responsive re-render for chart on window resize
    window.addEventListener('resize', () => {
        if (trendsData.length > 0) {
            renderTrendChart(trendsData);
        }
    });
})();
