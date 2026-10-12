const canvas = document.getElementById("graph-canvas");
const context = canvas.getContext("2d");
const tooltip = document.getElementById("tooltip");
const graphSection = document.querySelector(".graph-section");

let nodes = [];
let edges = [];
let rings = [];
let nodeById = new Map();
let ringNodeIds = new Set();
let width = 0;
let height = 0;
let scale = 1;
let offsetX = 0;
let offsetY = 0;
let active = true;
let simulationTicks = 0;
let draggedNode = null;
let pointerDown = null;
let onNodeClick = () => {};

const colors = {
    customer: "#42a5f5",
    merchant: "#a78bfa",
    unknown: "#94a3b8",
    risk: "#fb7185",
    edge: "rgba(148, 163, 184, 0.18)",
    flagged: "#fb7185",
};

function resizeCanvas() {
    const bounds = canvas.getBoundingClientRect();
    const pixelRatio = window.devicePixelRatio || 1;
    const oldWidth = width;
    const oldHeight = height;
    width = bounds.width;
    height = bounds.height;
    canvas.width = Math.max(1, Math.floor(width * pixelRatio));
    canvas.height = Math.max(1, Math.floor(height * pixelRatio));
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    if (!nodes.length) {
        offsetX = width / 2;
        offsetY = height / 2;
    } else {
        offsetX += (width - oldWidth) / 2;
        offsetY += (height - oldHeight) / 2;
    }
    active = true;
}

function seedPosition(id, index, count) {
    let hash = 0;
    for (const character of id) {
        hash = (hash * 31 + character.charCodeAt(0)) | 0;
    }
    const angle = (index / Math.max(1, count)) * Math.PI * 2 + (hash % 100) / 100;
    const radius = Math.min(width, height) * (0.18 + ((Math.abs(hash) % 100) / 100) * 0.27);
    return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
}

export function setGraphData(payload) {
    const previous = nodeById;
    const entries = Object.values(payload.nodes || {});
    nodeById = new Map();
    nodes = entries.map((record, index) => {
        const old = previous.get(record.id);
        const position = old || seedPosition(record.id, index, entries.length);
        const node = {
            ...record,
            x: position.x,
            y: position.y,
            vx: old?.vx || 0,
            vy: old?.vy || 0,
            radius: Math.max(3.2, Math.min(8, 3.5 + Math.sqrt(record.total_txns || 1) * 0.15)),
        };
        nodeById.set(node.id, node);
        return node;
    });
    edges = (payload.edges || [])
        .map((edge) => ({ ...edge, sourceNode: nodeById.get(edge.source), targetNode: nodeById.get(edge.target) }))
        .filter((edge) => edge.sourceNode && edge.targetNode);
    rings = payload.rings || [];
    ringNodeIds = new Set(rings.flatMap((ring) => ring.nodes));
    simulationTicks = 0;
    active = true;
    requestAnimationFrame(draw);
}

export function setOnNodeClick(callback) {
    onNodeClick = callback;
}

function updateForces() {
    const cooling = Math.max(0.01, 1 - simulationTicks / 300);
    for (const node of nodes) {
        if (node === draggedNode) continue;
        node.vx *= 0.86;
        node.vy *= 0.86;
    }

    for (let i = 0; i < nodes.length; i += 1) {
        const left = nodes[i];
        for (let j = i + 1; j < nodes.length; j += 1) {
            const right = nodes[j];
            let dx = left.x - right.x;
            let dy = left.y - right.y;
            const distanceSquared = dx * dx + dy * dy + 0.01;
            const distance = Math.sqrt(distanceSquared);
            const force = Math.min(1.8, 900 / distanceSquared) * cooling;
            dx = (dx / distance) * force;
            dy = (dy / distance) * force;
            if (left !== draggedNode) {
                left.vx += dx;
                left.vy += dy;
            }
            if (right !== draggedNode) {
                right.vx -= dx;
                right.vy -= dy;
            }
        }
    }

    for (const edge of edges) {
        const source = edge.sourceNode;
        const target = edge.targetNode;
        let dx = target.x - source.x;
        let dy = target.y - source.y;
        const distance = Math.sqrt(dx * dx + dy * dy) || 1;
        const desired = Math.max(36, Math.min(115, 82 - Math.log1p(edge.weight) * 5));
        const force = (distance - desired) * 0.0017 * cooling;
        dx = (dx / distance) * force;
        dy = (dy / distance) * force;
        if (source !== draggedNode) {
            source.vx += dx;
            source.vy += dy;
        }
        if (target !== draggedNode) {
            target.vx -= dx;
            target.vy -= dy;
        }
    }

    for (const node of nodes) {
        if (node === draggedNode) continue;
        node.vx += -node.x * 0.0007;
        node.vy += -node.y * 0.0007;
        node.x += node.vx;
        node.y += node.vy;
    }
    simulationTicks += 1;
}

function draw() {
    context.clearRect(0, 0, width, height);
    if (!width || !height) return;
    if (simulationTicks < 300) updateForces();

    context.save();
    context.translate(offsetX, offsetY);
    context.scale(scale, scale);

    for (const edge of edges) {
        const flagged = edge.review_count > 0;
        const pulse = flagged ? 0.72 + Math.sin(Date.now() / 260) * 0.22 : 1;
        context.beginPath();
        context.moveTo(edge.sourceNode.x, edge.sourceNode.y);
        context.lineTo(edge.targetNode.x, edge.targetNode.y);
        context.strokeStyle = flagged ? `rgba(251, 113, 133, ${pulse})` : colors.edge;
        context.lineWidth = flagged ? 1.3 + Math.min(2, edge.review_rate * 2) : 0.6 + Math.min(1.5, edge.weight * 0.12);
        context.stroke();
    }

    for (const node of nodes) {
        const review = ringNodeIds.has(node.id) || node.risk_score >= 0.3;
        const color = review ? colors.risk : (colors[node.type] || colors.unknown);
        if (review) {
            context.beginPath();
            context.arc(node.x, node.y, node.radius + 4 + Math.sin(Date.now() / 320 + node.x) * 1.5, 0, Math.PI * 2);
            context.strokeStyle = "rgba(251, 113, 133, 0.27)";
            context.lineWidth = 1;
            context.stroke();
        }
        context.beginPath();
        context.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
        context.fillStyle = color;
        context.shadowColor = color;
        context.shadowBlur = review ? 13 : 5;
        context.fill();
        context.shadowBlur = 0;
    }
    context.restore();

    if (simulationTicks < 300 || rings.length > 0) requestAnimationFrame(draw);
    else active = false;
}

function restart() {
    if (!active) {
        active = true;
        requestAnimationFrame(draw);
    }
}

function graphPoint(event) {
    const bounds = canvas.getBoundingClientRect();
    return {
        x: (event.clientX - bounds.left - offsetX) / scale,
        y: (event.clientY - bounds.top - offsetY) / scale,
    };
}

function hitTest(point) {
    for (let index = nodes.length - 1; index >= 0; index -= 1) {
        const node = nodes[index];
        if (Math.hypot(node.x - point.x, node.y - point.y) <= node.radius + 5) return node;
    }
    return null;
}

function showTooltip(node, event) {
    tooltip.replaceChildren();
    const title = document.createElement("div");
    title.className = "tooltip-title";
    title.textContent = node.id;
    const detail = document.createElement("div");
    detail.className = "tooltip-copy";
    detail.textContent = `${node.type} · ${node.total_txns} transactions · ${(node.risk_score * 100).toFixed(1)}% review signal`;
    tooltip.append(title, detail);
    const bounds = graphSection.getBoundingClientRect();
    tooltip.style.left = `${Math.max(8, Math.min(event.clientX - bounds.left + 12, bounds.width - 285))}px`;
    tooltip.style.top = `${Math.max(12, event.clientY - bounds.top - 14)}px`;
    tooltip.classList.remove("hidden");
}

canvas.addEventListener("pointerdown", (event) => {
    pointerDown = { x: event.clientX, y: event.clientY };
    const node = hitTest(graphPoint(event));
    if (node) {
        draggedNode = node;
        canvas.setPointerCapture(event.pointerId);
    }
});

canvas.addEventListener("pointermove", (event) => {
    const point = graphPoint(event);
    if (draggedNode) {
        draggedNode.x = point.x;
        draggedNode.y = point.y;
        draggedNode.vx = 0;
        draggedNode.vy = 0;
        restart();
        return;
    }
    if (pointerDown && (Math.abs(event.clientX - pointerDown.x) > 2 || Math.abs(event.clientY - pointerDown.y) > 2)) {
        pointerDown = null;
    }
    const node = hitTest(point);
    canvas.style.cursor = node ? "pointer" : "grab";
    if (node) showTooltip(node, event);
    else tooltip.classList.add("hidden");
});

canvas.addEventListener("pointerup", (event) => {
    const node = hitTest(graphPoint(event));
    const click = pointerDown && Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y) < 5;
    draggedNode = null;
    if (click && node) onNodeClick(node.id);
    pointerDown = null;
    restart();
});

canvas.addEventListener("pointercancel", () => {
    draggedNode = null;
    pointerDown = null;
});

canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const factor = event.deltaY < 0 ? 1.1 : 0.9;
    scale = Math.max(0.45, Math.min(2.8, scale * factor));
    restart();
}, { passive: false });

document.getElementById("reset-view-btn")?.addEventListener("click", () => {
    scale = 1;
    offsetX = width / 2;
    offsetY = height / 2;
    restart();
});

const resizeObserver = new ResizeObserver(resizeCanvas);
resizeObserver.observe(canvas);
resizeCanvas();
requestAnimationFrame(draw);
