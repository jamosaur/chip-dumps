// Copy-hash buttons, clickable table rows and the image lightbox. The site works without this script.

// Pixel art (fonts, icons, bitmaps) is drawn crisp when shown larger than its native size.
function markPixel(img) {
  const check = () => {
    if (img.naturalWidth && img.clientWidth > img.naturalWidth * 1.2) img.classList.add("pixel");
  };
  if (img.complete) check(); else img.addEventListener("load", check, { once: true });
}
document.querySelectorAll(".gallery img, .prose .inline-shot img").forEach(markPixel);

let lightbox = null;
let items = [];
let index = 0;

function buildLightbox() {
  const d = document.createElement("dialog");
  d.className = "lightbox";
  d.setAttribute("aria-label", "Image viewer");
  d.innerHTML = `
    <div class="lb-bar"><span class="lb-count"></span>
      <div class="lb-actions"><a class="lb-open" target="_blank" rel="noopener">Open original</a><button type="button" class="lb-close" aria-label="Close">Close ✕</button></div></div>
    <div class="lb-stage">
      <button type="button" class="lb-prev" aria-label="Previous image">‹</button>
      <img alt="">
      <button type="button" class="lb-next" aria-label="Next image">›</button>
    </div>
    <figcaption></figcaption>`;
  document.body.appendChild(d);
  d.querySelector(".lb-close").addEventListener("click", () => d.close());
  d.querySelector(".lb-prev").addEventListener("click", () => show(index - 1));
  d.querySelector(".lb-next").addEventListener("click", () => show(index + 1));
  // Clicking the dark area around the image closes it.
  d.addEventListener("click", (ev) => { if (ev.target === d || ev.target.classList.contains("lb-stage")) d.close(); });
  d.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowLeft") { ev.preventDefault(); show(index - 1); }
    if (ev.key === "ArrowRight") { ev.preventDefault(); show(index + 1); }
  });
  d.addEventListener("close", () => { document.documentElement.style.overflow = ""; });
  return d;
}

function show(i) {
  index = (i + items.length) % items.length;
  const a = items[index];
  const img = lightbox.querySelector("img");
  img.classList.remove("pixel");
  img.onload = () => {
    // Scale small images up by a whole number so pixels stay square.
    const box = lightbox.querySelector(".lb-stage");
    const scale = Math.max(1, Math.floor(Math.min((box.clientWidth - 16) / img.naturalWidth, (box.clientHeight - 16) / img.naturalHeight)));
    img.style.width = scale > 1 ? img.naturalWidth * scale + "px" : "";
    if (scale > 1) img.classList.add("pixel");
  };
  img.style.width = "";
  img.src = a.getAttribute("href");
  img.alt = a.dataset.caption || "";
  lightbox.querySelector("figcaption").textContent = a.dataset.caption || "";
  lightbox.querySelector(".lb-count").textContent = items.length > 1 ? `${index + 1} of ${items.length}` : "";
  lightbox.querySelector(".lb-open").href = a.getAttribute("href");
  const multi = items.length > 1;
  lightbox.querySelector(".lb-prev").hidden = !multi;
  lightbox.querySelector(".lb-next").hidden = !multi;
}

document.addEventListener("click", (e) => {
  const copy = e.target.closest("[data-copy]");
  if (copy) {
    const label = copy.textContent;
    const done = () => { copy.textContent = "Copied"; setTimeout(() => (copy.textContent = label), 1400); };
    if (navigator.clipboard) navigator.clipboard.writeText(copy.dataset.copy).then(done, () => {});
    return;
  }
  const shot = e.target.closest("a[data-lightbox]");
  if (shot && typeof HTMLDialogElement === "function" && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
    e.preventDefault();
    // One entry per image: inline copies in the write-up share the gallery's entry.
    const seen = new Map();
    document.querySelectorAll("a[data-lightbox]").forEach((a) => {
      const href = a.getAttribute("href");
      if (!seen.has(href) || a.closest(".gallery")) seen.set(href, a);
    });
    items = [...seen.values()];
    lightbox = lightbox || buildLightbox();
    show(items.indexOf(seen.get(shot.getAttribute("href"))));
    document.documentElement.style.overflow = "hidden";
    lightbox.showModal();
    lightbox.querySelector(".lb-close").focus({ focusVisible: false });
    return;
  }
  const row = e.target.closest("tr[data-href]");
  if (row && !e.target.closest("a")) location.href = row.dataset.href;
});
