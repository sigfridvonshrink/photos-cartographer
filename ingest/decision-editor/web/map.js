// Leaflet-based coordinate picker for the side panel (GPS cells). A fixed centre crosshair: the human
// pans/zooms the map under it and "use map center" reads map.getCenter() — exactly the model the design
// note describes. Reference pins (effective / inherited / folder fallback) and the current decision are
// shown for context. Leaflet is vendored under vendor/leaflet/ (global `L`, no CDN, no build); map TILES
// come from OpenStreetMap at runtime — the one external dependency, as any web map needs a tile source.

const round6 = (n) => Math.round(n * 1e6) / 1e6;
const fin = (v) => typeof v === "number" && isFinite(v);

export function mapPicker({ center, zoom = 13, markers = [], onPick }) {
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

  const readout = document.createElement("div");
  readout.className = "map-read";
  const fmt = () => { const c = map.getCenter(); readout.textContent = `center  ${c.lat.toFixed(6)}, ${c.lng.toFixed(6)}`; };
  map.on("move", fmt);
  fmt();
  const pick = document.createElement("button");
  pick.className = "btn primary";
  pick.textContent = "use map center";
  pick.addEventListener("click", () => { const c = map.getCenter(); onPick(round6(c.lat), round6(c.lng)); });
  const bar = document.createElement("div");
  bar.className = "map-bar";
  bar.append(readout, pick);

  return {
    el: wrap,
    bar,
    map,
    setCurrent,
    refresh() { map.invalidateSize(); },          // call after (re)attaching to the DOM
    recenter(c) { if (c && fin(c.lat) && fin(c.lon)) map.setView([c.lat, c.lon], Math.max(map.getZoom(), 13)); },
    destroy() { map.remove(); },
  };
}
