// A custom hover tooltip with no artificial delay -- the native `title`
// attribute carries a fixed OS/browser hover delay that CSS can't shorten.
// One shared element for the whole page, appended to document.body (not
// inside whatever cell or scroll container triggered it) so it can never
// get clipped by that container's own overflow box (see the `table {
// overflow-x: auto }` rule in app.css).

let tooltipEl = null;

function ensureTooltipEl() {
  if (!tooltipEl) {
    tooltipEl = document.createElement("div");
    tooltipEl.className = "hover-tooltip";
    tooltipEl.hidden = true;
    document.body.appendChild(tooltipEl);
  }
  return tooltipEl;
}

export function showTooltip(anchorRect, text) {
  const el = ensureTooltipEl();
  el.textContent = text;
  el.hidden = false;

  const tipRect = el.getBoundingClientRect();
  const top =
    anchorRect.bottom + tipRect.height + 4 > window.innerHeight
      ? anchorRect.top - tipRect.height - 4
      : anchorRect.bottom + 4;
  const left = Math.min(anchorRect.left, window.innerWidth - tipRect.width - 8);
  el.style.top = `${Math.max(4, top)}px`;
  el.style.left = `${Math.max(4, left)}px`;
}

export function hideTooltip() {
  if (tooltipEl) tooltipEl.hidden = true;
}

// Delegated mouseover/mouseout on `container`, so any element matching
// `selector` shows its tooltip on hover with no per-element listener.
// `getText` pulls the full (untruncated) text off the hovered element --
// an input's live `.value`, or a CSS-ellipsis-truncated cell's own
// `.textContent` (truncation is purely visual; the DOM text is never cut).
export function attachHoverTooltip(container, selector, getText) {
  container.addEventListener("mouseover", (ev) => {
    const el = ev.target.closest(selector);
    if (!el) return;
    const text = getText(el);
    if (!text) return;
    showTooltip(el.getBoundingClientRect(), text);
  });
  container.addEventListener("mouseout", (ev) => {
    if (!ev.target.closest(selector)) return;
    hideTooltip();
  });
}
