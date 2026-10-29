/*
 * script.js (analysis.html only)
 * -------------------------------
 * Everything the sequence analyzer page needs:
 *   - colorized live preview, with invalid characters flagged in red
 *   - FASTA/text file upload straight into the textarea
 *   - calling /api/analyze, /api/plots, /api/report, /api/bookmarks
 *   - rendering every results tab, including the Chart.js charts
 */

const seqInput = document.getElementById("sequence-input");
const livePreview = document.getElementById("live-preview");
const detectedType = document.getElementById("detected-type");
const detectedLength = document.getElementById("detected-length");
const analyzeBtn = document.getElementById("analyze-btn");
const errorBox = document.getElementById("error-box");
const tabsNav = document.getElementById("tabs");
const emptyState = document.getElementById("empty-state");
const fastaUpload = document.getElementById("fasta-upload");
const analysisTime = document.getElementById("analysis-time");

let hydropathyChart = null;
let chargeChart = null;
let disorderChart = null;
let structureBarChart = null;
let lastAnalyzedSequence = ""; // used by export/report/plot buttons

// ---------- example sequences ----------
const EXAMPLES = {
  dna: ">example DNA ORF\nATGGCTAAACTGGAACGCATTGCTAAACGTGGTGAAAAAGGCAGCCTGGCTCTGAAATTCTGGGATGTTCGTCGCCGTAAATATGATATCACCAGCTATTAA",
  rna: ">example mRNA fragment\nAUGGCUAAACUGGAACGCAUUGCUAAACGUGGUGAAAAAGGCAGCCUGGCUCUGAAAUUCUGGGAUGUUCGUCGCCGUAAAUAUGAUAUCACCAGCUAUUAA",
  protein: ">example protein\nMALKRIAKRGEKGSLALKFWDVRRRKYDITSY",
};

const NUCLEIC_ALPHABET = new Set("ACGTUN".split(""));
const PROTEIN_ALPHABET = new Set("ACDEFGHIKLMNPQRSTVWYX*".split(""));

// ---------- live colorized preview (valid bases colored, invalid = red) ----------
function baseClass(ch, looksLikeProtein) {
  if (looksLikeProtein) {
    return PROTEIN_ALPHABET.has(ch) ? "b-x" : "b-invalid";
  }
  switch (ch) {
    case "A": return "b-a";
    case "T": case "U": return "b-t";
    case "C": return "b-c";
    case "G": return "b-g";
    case "N": return "b-n";
    default: return NUCLEIC_ALPHABET.has(ch) ? "b-x" : "b-invalid";
  }
}

function colorizeSequence(seq, looksLikeProtein) {
  return seq
    .split("")
    .map((ch) => `<span class="${baseClass(ch, looksLikeProtein)}">${ch}</span>`)
    .join("");
}

function quickDetect(seq) {
  const s = seq.toUpperCase();
  if (!s) return null;
  if (/^[ACGTN]+$/.test(s)) return "DNA";
  if (/^[ACGUN]+$/.test(s)) return "RNA";
  if (/^[ACDEFGHIKLMNPQRSTVWYX*]+$/.test(s)) return "PROTEIN";
  // Guess the "closest" alphabet so invalid-char highlighting still makes sense.
  const proteinOnlyCount = s.split("").filter((c) => "EFILPQZJB".includes(c)).length;
  return proteinOnlyCount > 0 ? "UNKNOWN_PROTEIN_LIKE" : "UNKNOWN";
}

function cleanForPreview(raw) {
  return raw
    .split("\n")
    .filter((line) => !line.startsWith(">"))
    .join("")
    .replace(/[\s0-9]/g, "")
    .toUpperCase();
}

function updateBadge(type, length) {
  detectedType.className = "badge";
  if (!type) {
    detectedType.classList.add("badge-empty");
    detectedType.textContent = "no sequence yet";
    detectedLength.textContent = "";
    return;
  }
  const map = {
    DNA: ["badge-dna", "DNA detected"],
    RNA: ["badge-rna", "RNA detected"],
    PROTEIN: ["badge-protein", "Protein detected"],
    UNKNOWN: ["badge-unknown", "unrecognized characters"],
    UNKNOWN_PROTEIN_LIKE: ["badge-unknown", "unrecognized characters"],
  };
  const [cls, label] = map[type];
  detectedType.classList.add(cls);
  detectedType.textContent = label;
  detectedLength.textContent = `${length} letter${length === 1 ? "" : "s"}`;
}

seqInput.addEventListener("input", () => {
  const cleaned = cleanForPreview(seqInput.value);
  const type = quickDetect(cleaned);
  updateBadge(type, cleaned.length);

  if (!cleaned) {
    livePreview.innerHTML = "";
  } else {
    const looksLikeProtein = type === "PROTEIN" || type === "UNKNOWN_PROTEIN_LIKE";
    livePreview.innerHTML = colorizeSequence(cleaned, looksLikeProtein);
  }
});

// ---------- clear ----------
document.getElementById("clear-btn").addEventListener("click", () => {
  seqInput.value = "";
  fastaUpload.value = "";
  lastAnalyzedSequence = "";
  seqInput.dispatchEvent(new Event("input"));
  errorBox.hidden = true;
  tabsNav.hidden = true;
  analysisTime.hidden = true;
  emptyState.hidden = false;
  document.getElementById("bookmark-msg").hidden = true;
  activateTab("overview");
  seqInput.focus();
});

// ---------- example buttons ----------
document.querySelectorAll(".example-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    seqInput.value = EXAMPLES[btn.dataset.kind];
    seqInput.dispatchEvent(new Event("input"));
    seqInput.focus();
  });
});

// ---------- FASTA / text file upload ----------
fastaUpload.addEventListener("change", () => {
  const file = fastaUpload.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    seqInput.value = reader.result;
    seqInput.dispatchEvent(new Event("input"));
  };
  reader.onerror = () => {
    errorBox.textContent = "Could not read that file.";
    errorBox.hidden = false;
  };
  reader.readAsText(file);
});

// ---------- reload a sequence sent over from History ----------
window.addEventListener("DOMContentLoaded", () => {
  const preload = sessionStorage.getItem("dptlite-preload-sequence");
  if (preload) {
    seqInput.value = preload;
    seqInput.dispatchEvent(new Event("input"));
    sessionStorage.removeItem("dptlite-preload-sequence");
  }
  loadBookmarks();
});

// ---------- analysis time ("Completed in 42 ms" / "... (cache hit)") ----------
function showAnalysisTime(data) {
  const ms = data.elapsed_ms;
  const shown = ms < 1 ? "<1" : Math.round(ms);
  analysisTime.textContent = `Completed in ${shown} ms` + (data.from_cache ? " (cache hit)" : "");
  analysisTime.hidden = false;
}

// ---------- tabs ----------
function activateTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => {
    p.hidden = p.id !== `panel-${tabName}`;
  });
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    activateTab(btn.dataset.tab);
    document.getElementById(`panel-${btn.dataset.tab}`).scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

// ---------- analyze ----------
analyzeBtn.addEventListener("click", async () => {
  const sequence = seqInput.value;
  errorBox.hidden = true;
  analyzeBtn.disabled = true;
  analyzeBtn.textContent = "Analyzing...";

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sequence }),
    });
    const data = await res.json();

    if (!res.ok) {
      errorBox.textContent = data.error || "Something went wrong.";
      errorBox.hidden = false;
      return;
    }

    lastAnalyzedSequence = data.cleaned_sequence;
    renderResults(data);
    emptyState.hidden = true;
    tabsNav.hidden = false;
    // Show whichever tab was already selected (e.g. re-analyzing while on "Domains"), or default to Overview the first time results appear.
    // Without this, a freshly-analyzed Overview panel stayed hidden until the user clicked away to another tab and back.
    const currentTab = document.querySelector(".tab-btn.active")?.dataset.tab || "overview";
    activateTab(currentTab);
    showAnalysisTime(data);
  } catch (err) {
    errorBox.textContent = "Could not reach the server. Is the Flask app running?";
    errorBox.hidden = false;
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = "Analyze sequence";
  }
});

// ---------- bookmarking ----------
document.getElementById("bookmark-btn").addEventListener("click", async () => {
  const name = document.getElementById("bookmark-name").value.trim();
  const msg = document.getElementById("bookmark-msg");
  const sequence = seqInput.value;

  if (!name || !sequence.trim()) {
    msg.textContent = "Enter a name and a sequence first.";
    msg.hidden = false;
    return;
  }

  const res = await fetch("/api/bookmarks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, sequence }),
  });
  const data = await res.json();
  msg.textContent = res.ok ? "Saved!" : (data.error || "Could not save bookmark.");
  msg.hidden = false;
  if (res.ok) {
    document.getElementById("bookmark-name").value = "";
    loadBookmarks();
  }
});

// The quick-load panel in the sidebar. Names are added with textContent (never innerHTML), and a sequence is fetched only when you press
// Load, because the list itself no longer carries the (possibly huge) sequences.
async function loadBookmarks() {
  const container = document.getElementById("bookmark-quickload");
  const note = (text) => {
    const p = document.createElement("p");
    p.className = "muted small";
    p.textContent = text;
    container.replaceChildren(p);
  };
  try {
    const res = await fetch("/api/bookmarks");
    const bookmarks = await res.json();
    if (!Array.isArray(bookmarks) || !bookmarks.length) {
      note("No bookmarks yet.");
      return;
    }
    container.replaceChildren(
      ...bookmarks.map((b) => {
        const item = document.createElement("div");
        item.className = "bookmark-quick-item";

        const label = document.createElement("span");
        label.textContent = b.name;
        if (b.group_name) {
          const group = document.createElement("span");
          group.className = "muted";
          group.textContent = ` (${b.group_name})`;
          label.append(group);
        }

        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn-ghost btn-small";
        button.textContent = "Load";
        button.addEventListener("click", async () => {
          const response = await fetch(`/api/bookmarks/${b.id}`);
          if (!response.ok) return;
          seqInput.value = (await response.json()).sequence;
          seqInput.dispatchEvent(new Event("input"));
        });

        item.append(label, button);
        return item;
      })
    );
  } catch (err) {
    note("Could not load bookmarks.");
  }
}


// ---------- downloadable report ----------
const REPORT_FILENAMES = {
  txt: "dptlite_report.txt",
  json: "dptlite_report.json",
  pdf: "dptlite_report.pdf",
  fasta: "dptlite_sequences.fasta",
  zip: "dptlite_bundle.zip",
};

async function downloadReport(format) {
  if (!lastAnalyzedSequence) {
    errorBox.textContent = "Analyze a sequence first.";
    errorBox.hidden = false;
    return;
  }
  const res = await fetch("/api/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sequence: lastAnalyzedSequence, format }),
  });
  if (!res.ok) {
    const data = await res.json();
    errorBox.textContent = data.error || "Could not generate the report.";
    errorBox.hidden = false;
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = REPORT_FILENAMES[format];
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// One listener for all five Export buttons (each has data-format="txt|json|pdf|fasta|zip").
// PDF and ZIP take a moment (matplotlib draws the plots), so show a busy label.
document.querySelectorAll(".download-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Preparing...";
    await downloadReport(btn.dataset.format);
    btn.disabled = false;
    btn.textContent = label;
  });
});

// ---------- matplotlib static plots ----------
document.getElementById("generate-plots-btn").addEventListener("click", async () => {
  const container = document.getElementById("static-plots");
  if (!lastAnalyzedSequence) {
    errorBox.textContent = "Analyze a sequence first.";
    errorBox.hidden = false;
    return;
  }
  container.innerHTML = '<p class="muted small">Rendering with matplotlib&hellip;</p>';
  try {
    const res = await fetch("/api/plots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sequence: lastAnalyzedSequence }),
    });
    const data = await res.json();
    if (!res.ok) {
      container.innerHTML = `<p class="muted small">${data.error || "Could not generate images."}</p>`;
      return;
    }
    container.innerHTML = `
      <img src="${data.hydropathy}" alt="Hydropathy plot">
      <img src="${data.charge_ph}" alt="Charge vs pH curve">
      <img src="${data.disorder}" alt="Disorder tendency plot">
    `;
  } catch (err) {
    container.innerHTML = '<p class="muted small">Could not reach the server.</p>';
  }
});

// ---------- rendering ----------
function renderResults(data) {
  renderOverview(data);
  renderTranslation(data);
  renderPlots(data.protein_analysis);
  renderStructure(data.protein_analysis);
  renderDomains(data.protein_analysis);

  const isNucleic = data.input_type === "DNA" || data.input_type === "RNA";
  document.getElementById("nucleic-card").hidden = !isNucleic;
}

function statTile(value, label) {
  return `<div class="stat-tile"><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>`;
}

function renderOverview(data) {
  const stats = document.getElementById("overview-stats");
  const tiles = [statTile(data.input_type, "Sequence type"), statTile(data.length, "Length (nt or aa)")];

  if (data.gc_content_percent !== undefined) {
    tiles.push(statTile(`${data.gc_content_percent}%`, "GC content"));
  }
  const pa = data.protein_analysis;
  if (pa) {
    tiles.push(statTile(pa.length, "Protein length (aa)"));
    tiles.push(statTile(`${pa.molecular_weight_da} Da`, "Molecular weight"));
    tiles.push(statTile(pa.theoretical_pi ?? "—", "Theoretical pI"));
  }
  stats.innerHTML = tiles.join("");

  if (data.input_type === "DNA" || data.input_type === "RNA") {
    document.getElementById("complement-seq").innerHTML = colorizeSequence(data.complement, false);
    document.getElementById("revcomp-seq").innerHTML = colorizeSequence(data.reverse_complement, false);
    document.getElementById("rna-seq").innerHTML = colorizeSequence(data.transcribed_rna, false);
  }

  renderComposition(pa ? pa.composition : {});
}

function renderComposition(composition) {
  const el = document.getElementById("aa-composition");
  const entries = Object.entries(composition);
  if (!entries.length) {
    el.innerHTML = '<p class="muted">No protein composition to show.</p>';
    return;
  }
  entries.sort((a, b) => b[1].percent - a[1].percent);
  el.innerHTML = entries
    .map(
      ([aa, info]) => `
      <div class="aa-row">
        <span class="aa-code">${aa}</span>
        <span class="aa-bar-track"><span class="aa-bar-fill" style="width:${info.percent}%"></span></span>
        <span class="aa-pct">${info.percent}%</span>
      </div>`
    )
    .join("");
}

function renderTranslation(data) {
  const framesEl = document.getElementById("six-frames");
  const orfEl = document.getElementById("orf-list");

  if (!data.six_frame_translation) {
    framesEl.innerHTML = '<p class="muted">Six-frame translation only applies to DNA/RNA input.</p>';
    orfEl.innerHTML = "";
    return;
  }

  framesEl.innerHTML = data.six_frame_translation
    .map(
      (f) => `
      <div class="frame-block">
        <div class="frame-title">${f.label}</div>
        <code class="frame-seq mono">${colorizeProteinFrame(f.protein)}</code>
      </div>`
    )
    .join("");

  if (!data.orfs.length) {
    orfEl.innerHTML = '<p class="muted">No ORFs of meaningful length (&ge;20 aa) were found.</p>';
  } else {
    orfEl.innerHTML = data.orfs
      .map(
        (o) => `
        <div class="orf-item">
          <div class="orf-item-head"><span>${o.frame}, starts at residue ${o.start_residue}</span><span>${o.length_aa} aa</span></div>
          <code class="mono">${o.protein}</code>
        </div>`
      )
      .join("");
  }
}

function colorizeProteinFrame(protein) {
  return protein
    .split("")
    .map((ch) => (ch === "*" ? `<span class="b-stop">*</span>` : ch))
    .join("");
}

function renderPlots(pa) {
  const numbers = document.getElementById("protein-numbers");
  if (!pa) {
    numbers.innerHTML = "";
    return;
  }
  numbers.innerHTML = [
    statTile(`${pa.molecular_weight_da} Da`, "Molecular weight"),
    statTile(pa.theoretical_pi ?? "—", "Theoretical pI"),
    statTile(pa.length, "Residues plotted"),
  ].join("");

  const labels = pa.hydropathy_profile.map((_, i) => i + 1);
  const gridColor = getComputedStyle(document.documentElement).getPropertyValue("--chart-grid").trim() || "#24332c";
  const tickColor = getComputedStyle(document.documentElement).getPropertyValue("--chart-tick").trim() || "#8fa398";

  if (hydropathyChart) hydropathyChart.destroy();
  hydropathyChart = new Chart(document.getElementById("hydropathy-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Hydropathy (Kyte-Doolittle)",
        data: pa.hydropathy_profile,
        borderColor: "#2f8f68",
        backgroundColor: "rgba(76,224,160,0.12)",
        pointRadius: 0,
        borderWidth: 1.5,
        fill: true,
        tension: 0.15,
      }],
    },
    options: chartOptions("Residue position", "Hydropathy score", gridColor, tickColor),
  });

  if (chargeChart) chargeChart.destroy();
  chargeChart = new Chart(document.getElementById("charge-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Net charge (windowed)",
        data: pa.charge_profile,
        borderColor: "#e0654c",
        backgroundColor: "rgba(224,101,76,0.12)",
        pointRadius: 0,
        borderWidth: 1.5,
        fill: true,
        tension: 0.15,
      }],
    },
    options: chartOptions("Residue position", "Net charge", gridColor, tickColor),
  });
}

function chartOptions(xLabel, yLabel, gridColor, tickColor) {
  return {
    responsive: true,
    animation: false,
    plugins: {
      legend: { labels: { color: tickColor } },
    },
    scales: {
      x: {
        title: { display: !!xLabel, text: xLabel, color: tickColor },
        ticks: { color: tickColor, maxTicksLimit: 12 },
        grid: { color: gridColor },
      },
      y: {
        title: { display: !!yLabel, text: yLabel, color: tickColor },
        ticks: { color: tickColor },
        grid: { color: gridColor },
      },
    },
  };
}

function renderStructure(pa) {
  const summaryEl = document.getElementById("structure-summary");
  const trackEl = document.getElementById("structure-track");
  if (!pa) {
    summaryEl.innerHTML = "";
    trackEl.innerHTML = "";
    return;
  }
  const s = pa.structure_summary;
  summaryEl.innerHTML = `
    <span class="st-helix">Helix <b>${s.helix_percent}%</b></span>
    <span class="st-sheet">Sheet <b>${s.sheet_percent}%</b></span>
    <span class="st-coil">Coil <b>${s.coil_percent}%</b></span>
  `;
  trackEl.innerHTML = pa.secondary_structure
    .split("")
    .map((code) => {
      const cls = code === "H" ? "st-helix" : code === "E" ? "st-sheet" : "st-coil";
      return `<span class="${cls}">${code}</span>`;
    })
    .join("");

  // This chart lives at the bottom of the Secondary structure tab, since it visualizes the same H/E/C call.
  const gridColor = getComputedStyle(document.documentElement).getPropertyValue("--chart-grid").trim() || "#24332c";
  const tickColor = getComputedStyle(document.documentElement).getPropertyValue("--chart-tick").trim() || "#8fa398";

  if (structureBarChart) structureBarChart.destroy();
  structureBarChart = new Chart(document.getElementById("structure-bar-chart"), {
    type: "bar",
    data: {
      labels: ["Helix", "Sheet", "Coil"],
      datasets: [{
        label: "% of residues",
        data: [s.helix_percent, s.sheet_percent, s.coil_percent],
        backgroundColor: ["#e0654c", "#4c9fe0", "#566b62"],
      }],
    },
    options: {
      ...chartOptions("", "% of residues", gridColor, tickColor),
      indexAxis: "y",
      plugins: { legend: { display: false } },
    },
  });
}

function renderDomains(pa) {
  const signalEl = document.getElementById("signal-peptide-result");
  const tmEl = document.getElementById("tm-list");
  const disorderEl = document.getElementById("disorder-result");

  if (!pa) {
    signalEl.textContent = "";
    tmEl.innerHTML = "";
    disorderEl.innerHTML = "";
    return;
  }

  if (pa.signal_peptide) {
    const sp = pa.signal_peptide;
    signalEl.innerHTML = `Likely hydrophobic core between residues <b>${sp.start}&ndash;${sp.end}</b> (avg hydropathy ${sp.avg_hydropathy}) &mdash; consistent with a cleavable N-terminal signal peptide.`;
  } else {
    signalEl.textContent = "No strong N-terminal hydrophobic core found; unlikely to have a classic signal peptide.";
  }

  if (pa.transmembrane_helices.length) {
    tmEl.innerHTML = pa.transmembrane_helices
      .map((tm) => `<span class="domain-pill">Residues ${tm.start}&ndash;${tm.end} (${tm.length} aa)</span>`)
      .join("");
  } else {
    tmEl.innerHTML = '<p class="muted">No transmembrane-length hydrophobic stretches detected.</p>';
  }

  const od = pa.order_disorder;
  disorderEl.innerHTML = `
    <p><b>${od.call}</b></p>
    <p class="muted">Mean scaled hydropathy: ${od.mean_hydropathy} &middot; |net charge| per residue: ${od.abs_net_charge} &middot; boundary: ${od.boundary} &middot; margin: ${od.margin > 0 ? "+" : ""}${od.margin}</p>
    <p class="muted">Ordered if the margin is above +${od.borderline_margin}, disordered if below &minus;${od.borderline_margin}; in between the rule can't decide, so it says borderline.</p>
  `;

  // This chart lives at the bottom of the Domains tab, alongside the order/disorder call it's visualizing.
  const gridColor = getComputedStyle(document.documentElement).getPropertyValue("--chart-grid").trim() || "#24332c";
  const tickColor = getComputedStyle(document.documentElement).getPropertyValue("--chart-tick").trim() || "#8fa398";
  const labels = (pa.disorder_profile || []).map((_, i) => i + 1);

  if (disorderChart) disorderChart.destroy();
  disorderChart = new Chart(document.getElementById("disorder-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Order (+) / disorder (-)",
        data: pa.disorder_profile || [],
        borderColor: "#4c9fe0",
        backgroundColor: "rgba(76,159,224,0.12)",
        pointRadius: 0,
        borderWidth: 1.5,
        fill: true,
        tension: 0.15,
      }],
    },
    options: chartOptions("Residue position", "Score", gridColor, tickColor),
  });
}
