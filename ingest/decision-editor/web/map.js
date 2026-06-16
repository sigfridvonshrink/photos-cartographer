// Leaflet-based coordinate picker for the side panel (GPS cells). A fixed centre crosshair: the human
// pans/zooms the map under it and "use map center" reads map.getCenter() — exactly the model the design
// note describes. Reference pins (effective / inherited / folder fallback) and the current decision are
// shown for context. Leaflet is vendored under vendor/leaflet/ (global `L`, no CDN, no build); map TILES
// come from OpenStreetMap at runtime (as does the Nominatim place-search below) — the two external
// runtime dependencies, as any web map needs a tile source and geocoding needs a service.

const round6 = (n) => Math.round(n * 1e6) / 1e6;
const fin = (v) => typeof v === "number" && isFinite(v);

export function mapPicker({ center, zoom = 13, markers = [], onPick, onMove, track = null, scrubIndex = 0, onScrub }) {
  const map_el = document.createElement("div");
  map_el.className = "map";
  const cross = document.createElement("div");
  cross.className = "crosshair";          // CSS overlay, not a Leaflet layer; pointer-events: none
  const wrap = document.createElement("div");
  wrap.className = "mapwrap";
  wrap.append(map_el, cross);

  const map = L.map(map_el, { worldCopyJump: true })
    .setView(center ? [center.lat, center.lon] : [20, 0], center ? zoom : 2);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: "© OpenStreetMap contributors" }).addTo(map);

  // Static reference pins — circle markers so no marker-image assets are needed.
  for (const m of markers) {
    if (!fin(m.lat) || !fin(m.lon)) continue;
    L.circleMarker([m.lat, m.lon], { radius: 6, color: m.color || "#9aa3af", weight: 2, fillOpacity: 0.45 })
      .addTo(map).bindTooltip(m.label || "", { direction: "top" });
  }
  // The current decision (distinct from the crosshair, which is just the viewport centre).
  let current = null;
  function setCurrent(c) {
    if (current) { map.removeLayer(current); current = null; }
    if (c && fin(c.lat) && fin(c.lon)) {
      current = L.circleMarker([c.lat, c.lon],
        { radius: 7, color: "#6cc06c", weight: 3, fillColor: "#6cc06c", fillOpacity: 0.6 })
        .addTo(map).bindTooltip("your decision", { direction: "top" });
    }
  }

  // Place search (Nominatim / OpenStreetMap) — relocate the map to a named place, Google-Maps style.
  // Manual submit only (Enter or the button), never per-keystroke, to respect Nominatim's usage policy
  // (≤1 req/s). Picking a result moves the map (fitBounds to the result's box, else a mid zoom); it does
  // NOT set the decision — the operator still pans under the crosshair and "use map center". Nominatim is
  // a second runtime OSM dependency alongside the tiles; it degrades to a message when offline/blocked.
  const search_inp = document.createElement("input");
  search_inp.type = "text"; search_inp.className = "map-search"; search_inp.placeholder = "search a place (press Enter)…";
  const results = document.createElement("div"); results.className = "map-search-results"; results.hidden = true;
  async function doSearch() {
    const q = search_inp.value.trim(); if (!q) { results.hidden = true; return; }
    results.hidden = false; results.replaceChildren(document.createTextNode("searching…"));
    try {
      const r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=6&q=${encodeURIComponent(q)}`,
        { headers: { Accept: "application/json" } });
      const data = await r.json();
      results.replaceChildren();
      if (!Array.isArray(data) || !data.length) { results.append(document.createTextNode("no matches")); return; }
      for (const it of data) {
        const hit = document.createElement("button");
        hit.type = "button"; hit.className = "map-search-hit"; hit.textContent = it.display_name;
        hit.addEventListener("click", () => {
          results.hidden = true; search_inp.value = it.display_name;
          const bb = it.boundingbox && it.boundingbox.map(Number);
          if (bb && bb.every(fin)) map.fitBounds([[bb[0], bb[2]], [bb[1], bb[3]]]);
          else if (fin(+it.lat) && fin(+it.lon)) map.setView([+it.lat, +it.lon], 14);
        });
        results.append(hit);
      }
    } catch { results.replaceChildren(document.createTextNode("search failed (offline?)")); }
  }
  search_inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); doSearch(); } });
  search_inp.addEventListener("input", () => { if (!search_inp.value.trim()) results.hidden = true; });
  const search_btn = document.createElement("button");
  search_btn.className = "btn"; search_btn.textContent = "search"; search_btn.addEventListener("click", doSearch);
  const search_bar = document.createElement("div"); search_bar.className = "map-search-bar"; search_bar.append(search_inp, search_btn);
  const search = document.createElement("div"); search.className = "map-search-wrap"; search.append(search_bar, results);

  const readout = document.createElement("div");
  readout.className = "map-read";
  const fmt = () => { const c = map.getCenter(); readout.textContent = `center  ${c.lat.toFixed(6)}, ${c.lng.toFixed(6)}`; };
  // Only USER pans mirror into the pinned decision box (onMove); the initial fit must not clobber an
  // empty/seeded coord field, so it just paints the readout.
  map.on("move", () => { fmt(); if (onMove) { const c = map.getCenter(); onMove(round6(c.lat), round6(c.lng)); } });
  fmt();
  const pick = document.createElement("button");
  pick.className = "btn primary";
  pick.textContent = "use map center";
  pick.addEventListener("click", () => { const c = map.getCenter(); onPick(round6(c.lat), round6(c.lng)); });
  const bar = document.createElement("div");
  bar.className = "map-bar";
  bar.append(readout, pick);

  const api = {
    el: wrap,
    bar,
    search,
    map,
    setCurrent,
    refresh() { map.invalidateSize(); },          // call after (re)attaching to the DOM
    recenter(c) { if (c && fin(c.lat) && fin(c.lon)) map.panTo([c.lat, c.lon]); },   // keep the current zoom
    jumpMax(c) { if (c && fin(c.lat) && fin(c.lon)) map.setView([c.lat, c.lon], map.getMaxZoom()); },  // a pasted exact coord -> go there, zoom in fully
    destroy() { map.remove(); },
  };

  // Scrub-on-track (GPS-drift validation): draw the GPX segment and move a marker ALONG it with the
  // scroll wheel — the photo conceptually slides under the fixed centre crosshair (the map pans to keep
  // the chosen point centred). Each step reports the chosen point so the caller can compute the
  // corrected offset = (chosen track time) − (photo camera-naive).
  if (track && track.length) {
    L.polyline(track.map((p) => [p.lat, p.lon]), { color: "#e0a85e", weight: 3, opacity: 0.85 }).addTo(map);
    let idx = Math.max(0, Math.min(track.length - 1, scrubIndex | 0));
    const dot = L.circleMarker([track[idx].lat, track[idx].lon],
      { radius: 8, color: "#6cc06c", weight: 3, fillColor: "#6cc06c", fillOpacity: 0.7 })
      .addTo(map).bindTooltip("scrub point", { direction: "top" });
    const place = (i, fire) => {
      idx = Math.max(0, Math.min(track.length - 1, i));
      const pt = track[idx];
      dot.setLatLng([pt.lat, pt.lon]);
      map.panTo([pt.lat, pt.lon]);
      if (fire && onScrub) onScrub(idx, pt);
    };
    map_el.addEventListener("wheel", (e) => { e.preventDefault(); place(idx + (e.deltaY < 0 ? -1 : 1), true); }, { passive: false });
    map.setView([track[idx].lat, track[idx].lon], map.getMaxZoom());
    api.setScrub = (i) => place(i, false);        // reposition without firing (e.g. re-seed after re-render)
    api.scrubIndex = () => idx;
  }
  return api;
}
