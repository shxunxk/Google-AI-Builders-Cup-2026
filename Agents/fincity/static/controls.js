import { setGraphData, setOnNodeClick } from "./graph.js";

const $ = (selector) => document.querySelector(selector);
const state = {
    windows: [],
    currentWindow: 0,
    rings: [],
    minTxnCount: 1,
    maxNodes: 500,
    activeRing: null,
    animationTimer: null,
    animationSpeed: 1,
};

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
    })[character]);
}

async function api(path, options = {}) {
    const response = await fetch(path, options);
    let payload;
    try {
        payload = await response.json();
    } catch {
        throw new Error(`Request failed (${response.status})`);
    }
    if (!response.ok) {
        throw new Error(payload.detail || `Request failed (${response.status})`);
    }
    return payload;
}

function queryString(includeWindow = true) {
    const params = new URLSearchParams({
        min_txn_count: String(state.minTxnCount),
        max_nodes: String(state.maxNodes),
    });
    if (includeWindow && state.windows.length) {
        params.set("time_window_idx", String(state.currentWindow));
    }
    return params.toString();
}

function setStatus(message, type = "info") {
    const banner = $("#status-banner");
    banner.textContent = message;
    banner.className = `status-banner ${type}`;
}

function setStats(stats) {
    $("#stat-nodes").textContent = Number(stats.num_nodes || 0).toLocaleString();
    $("#stat-edges").textContent = Number(stats.num_edges || 0).toLocaleString();
    $("#stat-rings").textContent = Number(stats.num_fraud_rings || 0).toLocaleString();
    const riskCount = Object.values(window.currentGraph?.nodes || {}).filter(
        (node) => node.risk_score >= 0.3,
    ).length;
    $("#stat-risk").textContent = riskCount.toLocaleString();
    $("#stats-detail").innerHTML = `
        <div class="detail-grid">
            <div class="detail-item"><div class="label">Customers</div><div class="value">${Number(stats.customer_nodes || 0).toLocaleString()}</div></div>
            <div class="detail-item"><div class="label">Merchants</div><div class="value">${Number(stats.merchant_nodes || 0).toLocaleString()}</div></div>
            <div class="detail-item"><div class="label">Connected groups</div><div class="value">${Number(stats.num_communities || 0).toLocaleString()}</div></div>
            <div class="detail-item"><div class="label">Review signals</div><div class="value">${Number(stats.total_review_signals || 0).toLocaleString()}</div></div>
        </div>
        <p class="data-note">${stats.risk_basis === "observed_label"
        ? "Risk signal uses observed transaction labels."
        : "Review heuristic: TRANSFER/CASH_OUT in the top 5% by amount with at least 90% of the sender balance depleted. Not a confirmed fraud label."}</p>
    `;
}

function renderRings(rings) {
    const container = $("#rings-list");
    if (!rings.length) {
        container.innerHTML = '<p class="placeholder">No review clusters in this time window.</p>';
        return;
    }
    container.innerHTML = rings.map((ring) => `
        <article class="ring-card">
            <div class="ring-card-head">
                <span class="ring-id">${escapeHtml(ring.id)}</span>
                <span class="ring-rate">${ring.risk_basis === "observed_label" ? "fraud" : "signal"} ${(ring.signal_rate * 100).toFixed(1)}%</span>
            </div>
            <p>${ring.size} accounts · ${ring.internal_edges} links</p>
            <p class="ring-evidence">${ring.risk_basis === "observed_label" ? "Observed label" : "Heuristic review signal"} · ${ring.total_review_signals} signals</p>
            <button class="btn btn-secondary btn-sm open-ring" data-ring="${escapeHtml(ring.id)}">Open cluster case</button>
        </article>
    `).join("");
    container.querySelectorAll(".open-ring").forEach((button) => {
        button.addEventListener("click", () => openRingCase(button.dataset.ring));
    });
}

function renderTransactionList(records, counterpartyKey) {
    if (!records.length) return '<p class="empty-note">No transactions in the loaded sample.</p>';
    return records.map((txn) => `
        <div class="transaction-row">
            <div><strong>${escapeHtml(txn.type)}</strong><span>Step ${Number(txn.step)}</span></div>
            <div class="transaction-amount">₹${Number(txn.amount).toLocaleString("en-IN", { maximumFractionDigits: 0 })}</div>
            <div class="transaction-party">${escapeHtml(txn[counterpartyKey] || "—")}</div>
        </div>
    `).join("");
}

async function showCaseFile(accountId) {
    $("#node-details").innerHTML = '<p class="placeholder">Loading account case file…</p>';
    document.querySelector('[data-tab="details"]').click();
    try {
        const caseFile = await api(
            `/api/case-file/${encodeURIComponent(accountId)}?${queryString()}`,
        );
        const profile = caseFile.profile;
        const riskClass = profile.risk_score >= 0.5 ? "risk-high" : profile.risk_score >= 0.2 ? "risk-med" : "risk-low";
        $("#node-details").innerHTML = `
            <div class="case-heading">
                <span class="eyebrow">ACCOUNT CASE FILE</span>
                <h3>${escapeHtml(caseFile.account_id)}</h3>
                <span class="account-type">${escapeHtml(profile.type)}</span>
            </div>
            <div class="detail-grid">
                <div class="detail-item"><div class="label">Review signal</div><div class="value ${riskClass}">${(profile.risk_score * 100).toFixed(1)}%</div></div>
                <div class="detail-item"><div class="label">Balance</div><div class="value">₹${Number(profile.balance).toLocaleString("en-IN", { maximumFractionDigits: 0 })}</div></div>
                <div class="detail-item"><div class="label">Outgoing</div><div class="value">${Number(profile.outgoing_count).toLocaleString()}</div></div>
                <div class="detail-item"><div class="label">Incoming</div><div class="value">${Number(profile.incoming_count).toLocaleString()}</div></div>
            </div>
            <p class="data-note">${profile.risk_basis === "observed_label" ? "Based on observed transaction labels." : "Heuristic review signal; not a confirmed fraud finding."}</p>
            ${caseFile.fraud_rings.length ? `<div class="detail-section"><h4>Linked review clusters</h4><p>${caseFile.fraud_rings.map(escapeHtml).join(", ")}</p></div>` : ""}
            <div class="detail-section"><h4>Recent outgoing</h4>${renderTransactionList(caseFile.recent_outgoing, "nameDest")}</div>
            <div class="detail-section"><h4>Recent incoming</h4>${renderTransactionList(caseFile.recent_incoming, "nameOrig")}</div>
        `;
    } catch (error) {
        $("#node-details").innerHTML = `<p class="error-copy">${escapeHtml(error.message)}</p>`;
    }
}

function showCourtroomPreview(transaction, ring) {
    $("#courtroom-content").innerHTML = `
        <div class="ring-summary">
            <span class="eyebrow">${escapeHtml(ring.id)} · ${ring.size} accounts</span>
            <p>${ring.risk_basis === "observed_label"
        ? "Selected transaction has an observed fraud label."
        : "Review candidate selected by transaction amount; this is not a confirmed fraud label."}</p>
        </div>
        <div class="detail-grid">
            <div class="detail-item"><div class="label">Transaction</div><div class="value">${escapeHtml(transaction.type)} · Step ${transaction.step}</div></div>
            <div class="detail-item"><div class="label">Amount</div><div class="value">₹${Number(transaction.amount).toLocaleString("en-IN", { maximumFractionDigits: 0 })}</div></div>
            <div class="detail-item"><div class="label">Origin</div><div class="value">${escapeHtml(transaction.nameOrig)}</div></div>
            <div class="detail-item"><div class="label">Destination</div><div class="value">${escapeHtml(transaction.nameDest)}</div></div>
        </div>
        <div id="trial-result" class="trial-result"></div>
    `;
}

async function openRingCase(ringId) {
    const ring = state.rings.find((item) => item.id === ringId);
    if (!ring) return;
    state.activeRing = ring;
    $("#courtroom-content").innerHTML = '<p class="placeholder">Loading highest-priority transaction…</p>';
    $("#run-courtroom").disabled = true;
    $("#courtroom-dialog").showModal();
    try {
        const transaction = await api(`/api/worst-txn/${encodeURIComponent(ringId)}?${queryString()}`);
        showCourtroomPreview(transaction, ring);
        $("#run-courtroom").disabled = false;
    } catch (error) {
        $("#courtroom-content").innerHTML = `<p class="error-copy">${escapeHtml(error.message)}</p>`;
    }
}

async function runCourtroomTrial() {
    if (!state.activeRing) return;
    const button = $("#run-courtroom");
    const result = $("#trial-result");
    button.disabled = true;
    button.textContent = "Running trial…";
    result.textContent = "The Courtroom agents are reviewing the transaction.";
    try {
        const response = await api(
            `/api/courtroom/${encodeURIComponent(state.activeRing.id)}?${queryString()}`,
            { method: "POST" },
        );
        const trial = response.trial;
        result.innerHTML = `
            <div class="verdict-card">
                <span class="eyebrow">JUDGE'S VERDICT · ${(Number(trial.confidence) * 100).toFixed(0)}% confidence</span>
                <h3>${escapeHtml(trial.verdict)}</h3>
                <p>${escapeHtml(trial.judge_reasoning)}</p>
            </div>
            <div class="trial-argument"><strong>Prosecutor</strong><p>${escapeHtml(trial.prosecutor_argument)}</p></div>
            <div class="trial-argument"><strong>Defense</strong><p>${escapeHtml(trial.defense_argument)}</p></div>
            <div class="trial-argument counterfactual"><strong>Counterfactual</strong><p>${escapeHtml(trial.counterfactual)}</p></div>
        `;
    } catch (error) {
        result.innerHTML = `<p class="error-copy">Courtroom trial unavailable: ${escapeHtml(error.message)}</p>`;
    } finally {
        button.disabled = false;
        button.textContent = "Run courtroom trial";
    }
}

async function loadGraph() {
    const refresh = $("#refresh-btn");
    refresh.disabled = true;
    setStatus("Loading graph snapshot…");
    try {
        const response = await api(`/api/graph?${queryString()}`);
        window.currentGraph = response;
        state.rings = response.rings;
        setGraphData(response);
        renderRings(response.rings);
        setStats(response.stats);
        const [start, end] = response.stats.window_range || [];
        $("#time-label").textContent = start === undefined ? "No transactions" : `Step ${start}–${end}`;
        setStatus(
            response.stats.risk_basis === "observed_label"
                ? `Showing ${response.stats.num_nodes} accounts · observed labels`
                : `Showing ${response.stats.num_nodes} accounts · heuristic review signals, not confirmed fraud`,
        );
    } catch (error) {
        setStatus(`Unable to load FinCity graph: ${error.message}`, "error");
    } finally {
        refresh.disabled = false;
    }
}

async function initialize() {
    try {
        const response = await api("/api/time-windows");
        state.windows = response.windows;
        state.currentWindow = response.current || 0;
        const slider = $("#time-slider");
        slider.max = String(Math.max(0, state.windows.length - 1));
        slider.value = String(state.currentWindow);
        $("#time-label").textContent = state.windows[state.currentWindow]?.label || "No transactions";
        await loadGraph();
    } catch (error) {
        setStatus(`Unable to initialize FinCity: ${error.message}`, "error");
    }
}

setOnNodeClick(showCaseFile);
$("#refresh-btn").addEventListener("click", loadGraph);
$("#txn-filter").addEventListener("change", (event) => {
    state.minTxnCount = Number(event.target.value);
    loadGraph();
});
$("#node-limit").addEventListener("change", (event) => {
    state.maxNodes = Number(event.target.value);
    loadGraph();
});

$("#time-slider").addEventListener("input", (event) => {
    state.currentWindow = Number(event.target.value);
    $("#time-label").textContent = state.windows[state.currentWindow]?.label || "No transactions";
});
let sliderDebounce;
$("#time-slider").addEventListener("input", () => {
    window.clearTimeout(sliderDebounce);
    sliderDebounce = window.setTimeout(loadGraph, 100);
});

$("#play-btn").addEventListener("click", (event) => {
    if (state.animationTimer) {
        window.clearInterval(state.animationTimer);
        state.animationTimer = null;
        event.currentTarget.textContent = "▶";
        event.currentTarget.setAttribute("aria-label", "Play animation");
        return;
    }
    if (!state.windows.length) return;
    event.currentTarget.textContent = "Ⅱ";
    event.currentTarget.setAttribute("aria-label", "Pause animation");
    state.animationTimer = window.setInterval(() => {
        state.currentWindow = (state.currentWindow + 1) % state.windows.length;
        $("#time-slider").value = String(state.currentWindow);
        $("#time-label").textContent = state.windows[state.currentWindow].label;
        loadGraph();
    }, 1400 / state.animationSpeed);
});

$("#animation-speed").addEventListener("click", (event) => {
    state.animationSpeed = state.animationSpeed === 1 ? 2 : state.animationSpeed === 2 ? 4 : 1;
    event.currentTarget.textContent = `${state.animationSpeed}x`;
    if (state.animationTimer) {
        window.clearInterval(state.animationTimer);
        state.animationTimer = window.setInterval(() => {
            state.currentWindow = (state.currentWindow + 1) % state.windows.length;
            $("#time-slider").value = String(state.currentWindow);
            $("#time-label").textContent = state.windows[state.currentWindow].label;
            loadGraph();
        }, 1400 / state.animationSpeed);
    }
});

document.querySelectorAll(".tab-btn").forEach((button) => {
    button.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach((tab) => tab.classList.remove("active"));
        document.querySelectorAll(".panel-content").forEach((panel) => panel.classList.add("hidden"));
        button.classList.add("active");
        $(`#tab-${button.dataset.tab}`).classList.remove("hidden");
    });
});

$("#close-courtroom").addEventListener("click", () => $("#courtroom-dialog").close());
$("#run-courtroom").addEventListener("click", runCourtroomTrial);
$("#courtroom-dialog").addEventListener("click", (event) => {
    if (event.target === $("#courtroom-dialog")) $("#courtroom-dialog").close();
});

initialize();
