// Tiny hash router: '#/batches' -> the batch list, '#/batches/{id}' -> the
// entry grid for that batch. No build step, no framework -- this file is
// the entire routing layer.

import { renderAnalysis } from "./analysis.js";
import { renderBatchList } from "./batches.js";
import { renderConfig } from "./config.js";
import { EntryGrid } from "./entrygrid.js";
import { renderSets } from "./sets.js";
import { hideTooltip } from "./tooltip.js";

const root = document.getElementById("app");
let currentGrid = null;

function parseRoute() {
  const hash = location.hash.replace(/^#\/?/, "");
  const parts = hash.split("/").filter(Boolean);
  if (parts.length >= 2 && parts[0] === "batches") {
    return { view: "batch-detail", batchId: Number(parts[1]), tab: "batches" };
  }
  if (parts[0] === "sets") return { view: "sets", tab: "sets" };
  if (parts[0] === "analysis") return { view: "analysis", tab: "analysis" };
  if (parts[0] === "config") return { view: "config", tab: "config" };
  return { view: "batches", tab: "batches" };
}

function updateActiveTab(tab) {
  document.querySelectorAll("header.top-nav nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.tab === tab);
  });
}

async function render() {
  const route = parseRoute();
  if (currentGrid) {
    currentGrid.destroy();
    currentGrid = null;
  }
  root.innerHTML = "";
  hideTooltip(); // the shared hover tooltip lives outside root; a hidden view can't hide it itself
  updateActiveTab(route.tab);

  try {
    if (route.view === "batches") {
      await renderBatchList(root);
    } else if (route.view === "batch-detail") {
      currentGrid = new EntryGrid(root);
      await currentGrid.mount(route.batchId);
    } else if (route.view === "sets") {
      await renderSets(root);
    } else if (route.view === "analysis") {
      await renderAnalysis(root);
    } else if (route.view === "config") {
      await renderConfig(root);
    }
  } catch (e) {
    const errorEl = document.createElement("p");
    errorEl.className = "form-error";
    errorEl.textContent = e.message || "Something went wrong loading this page.";
    root.appendChild(errorEl);
  }
}

window.addEventListener("hashchange", render);
window.addEventListener("DOMContentLoaded", render);
