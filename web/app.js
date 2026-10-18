// Britannica · Wikipedia Cross-Era Lens Application Logic

let state = {
  pages: [],
  drift: null,
  cases: [],
  selectedPageIndex: 0,
  selectedEntryId: null,
  selectedCaseId: null,
  isLatexRawView: false,
};

// Initialization
document.addEventListener("DOMContentLoaded", async () => {
  setupTabs();
  await loadData();
  renderAll();
});

// Setup Navigation Tabs
function setupTabs() {
  const tabs = document.querySelectorAll("#nav-tabs .tab-btn");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const view = tab.getAttribute("data-view");
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");

      document.querySelectorAll(".view-panel").forEach(panel => {
        panel.classList.add("hidden");
      });
      const activePanel = document.getElementById(`view-${view}`);
      if (activePanel) {
        activePanel.classList.remove("hidden");
      }
    });
  });

  // Handle deep-link hashtag (e.g. #entry?e=e0013-01)
  window.addEventListener("hashchange", handleHashRouting);
}

function handleHashRouting() {
  const hash = window.location.hash;
  if (hash.startsWith("#entry?e=")) {
    const entryId = hash.replace("#entry?e=", "");
    selectEntryById(entryId);
    // Switch to match view
    const matchTab = document.querySelector('[data-view="match"]');
    if (matchTab) matchTab.click();
  }
}

// Data Fetching
async function loadData() {
  try {
    const [pagesRes, driftRes, casesRes] = await Promise.all([
      fetch("data/pages.json"),
      fetch("data/drift.json"),
      fetch("data/cases.json"),
    ]);

    state.pages = await pagesRes.json();
    state.drift = await driftRes.json();
    state.cases = await casesRes.json();

    // Check if any non-fixture data is loaded to control MOCK DATA badge
    const hasOnlyFixtures = state.pages.every(p => 
      p.entries.every(e => e.quality && e.quality.fixture)
    );
    const badge = document.getElementById("fixture-badge");
    if (badge && !hasOnlyFixtures) {
      badge.remove();
    }
  } catch (err) {
    console.error("Failed to load mock data:", err);
  }
}

function renderAll() {
  if (!state.pages || state.pages.length === 0) return;
  renderArchiveView();
  renderMatchView();
  renderAnalyticsView();
  renderAgentView();
  handleHashRouting();
}

// --- VIEW 1: ARCHIVE VIEWER ---
function renderArchiveView() {
  const pageSelect = document.getElementById("page-select");
  pageSelect.innerHTML = "";
  state.pages.forEach((page, idx) => {
    const opt = document.createElement("option");
    opt.value = idx;
    opt.textContent = `Page ${page.row_index} (${page.entries.length} entries) - ${page.filename}`;
    pageSelect.appendChild(opt);
  });

  pageSelect.addEventListener("change", (e) => {
    state.selectedPageIndex = parseInt(e.target.value, 10);
    updateArchivePage();
  });

  document.getElementById("toggle-latex-src").addEventListener("click", () => {
    state.isLatexRawView = !state.isLatexRawView;
    const rendered = document.getElementById("latex-rendered-pane");
    const raw = document.getElementById("latex-raw-pane");
    const btn = document.getElementById("toggle-latex-src");
    if (state.isLatexRawView) {
      rendered.classList.add("hidden");
      raw.classList.remove("hidden");
      btn.textContent = "View Rendered Document";
    } else {
      rendered.classList.remove("hidden");
      raw.classList.add("hidden");
      btn.textContent = "View LaTeX Source";
    }
  });

  updateArchivePage();
}

function updateArchivePage() {
  const page = state.pages[state.selectedPageIndex];
  if (!page) return;

  // Metadata
  document.getElementById("meta-row").textContent = page.row_index;
  document.getElementById("meta-vol").textContent = page.volume_id;
  document.getElementById("meta-latency").textContent = page.parse ? page.parse.latency_ms : "N/A";
  document.getElementById("meta-model").textContent = page.parse ? page.parse.model : "nvidia/nemotron-3.5-parse";

  // Scan SVG BBoxes
  const bboxGroup = document.getElementById("svg-bboxes");
  bboxGroup.innerHTML = "";

  page.entries.forEach(entry => {
    entry.blocks.forEach(block => {
      const [x0, y0, x1, y1] = block.bbox;
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", x0);
      rect.setAttribute("y", y0);
      rect.setAttribute("width", x1 - x0);
      rect.setAttribute("height", y1 - y0);
      rect.setAttribute("fill", block.cls === "Picture" ? "rgba(168, 85, 247, 0.15)" : "rgba(56, 189, 248, 0.15)");
      rect.setAttribute("stroke", block.cls === "Picture" ? "#9333ea" : "#0284c7");
      rect.setAttribute("stroke-width", "4");
      rect.setAttribute("class", "cursor-pointer transition-all hover:opacity-80");
      rect.setAttribute("data-entry-id", entry.entry_id);

      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = `${entry.headword || entry.kind} (${block.cls})`;
      rect.appendChild(title);

      rect.addEventListener("click", () => {
        highlightEntryInDoc(entry.entry_id);
      });

      bboxGroup.appendChild(rect);

      // Label text
      const txt = document.createElementNS("http://www.w3.org/2000/svg", "text");
      txt.setAttribute("x", x0 + 10);
      txt.setAttribute("y", y0 + 35);
      txt.setAttribute("font-size", "28");
      txt.setAttribute("font-weight", "bold");
      txt.setAttribute("fill", block.cls === "Picture" ? "#7e22ce" : "#0369a1");
      txt.textContent = entry.headword || `[${entry.kind}]`;
      bboxGroup.appendChild(txt);
    });
  });

  // Rendered LaTeX entries
  const entriesContainer = document.getElementById("latex-entries");
  entriesContainer.innerHTML = "";
  let rawTex = `% Generated from Nemotron Parse 3.5\\n\\documentclass[twocolumn]{article}\\n\\usepackage{graphicx,multicol}\\n\\begin{document}\\n\\title{Encyclopaedia Britannica Page ${page.row_index}}\\n\\maketitle\\n\\n`;

  page.entries.forEach(entry => {
    const div = document.createElement("div");
    div.id = `doc-${entry.entry_id}`;
    div.className = "p-3 rounded transition-colors duration-200 border border-transparent";

    if (entry.kind === "plate") {
      div.innerHTML = `
        <div class="border border-purple-200 bg-purple-50/50 p-4 rounded text-center my-3">
          <div class="text-xs uppercase font-bold tracking-wider text-purple-700 mb-1">Plate Figure</div>
          <p class="text-xs italic text-slate-700">${entry.text}</p>
          <div class="mt-2 text-[10px] text-slate-400 font-mono">Crop: ${entry.crop_path}</div>
        </div>
      `;
      rawTex += `\\begin{figure}[h]\\n\\centering\\n% \\includegraphics[width=\\linewidth]{${entry.crop_path}}\\n\\caption{${escapeLatex(entry.text)}}\\n\\end{figure}\\n\\n`;
    } else {
      const headwordHtml = entry.headword ? `<strong class="font-bold text-slate-900 tracking-wide">${entry.headword}</strong>, ` : "";
      const bodyText = entry.text.replace(new RegExp(`^${entry.headword}[,.]?\\s*`, "i"), "");
      div.innerHTML = `
        <div class="text-xs leading-relaxed">
          ${headwordHtml}
          <span>${bodyText}</span>
        </div>
      `;
      rawTex += `\\section*{${escapeLatex(entry.headword || entry.kind)}}\\n${escapeLatex(entry.text)}\\n\\n`;
    }

    entriesContainer.appendChild(div);
  });

  rawTex += `\\end{document}`;
  document.getElementById("latex-raw-code").textContent = rawTex;
}

function escapeLatex(str) {
  if (!str) return "";
  return str
    .replace(/\\/g, "\\textbackslash ")
    .replace(/[%$&_#{}]/g, "\\$&")
    .replace(/~/g, "\\textasciitilde ")
    .replace(/\^/g, "\\textasciicircum ");
}

function highlightEntryInDoc(entryId) {
  document.querySelectorAll("#latex-entries > div").forEach(el => {
    el.classList.remove("bg-amber-100", "border-amber-400");
  });
  const el = document.getElementById(`doc-${entryId}`);
  if (el) {
    el.classList.add("bg-amber-100", "border-amber-400");
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

// --- VIEW 2: MATCH EXPLORER ---
function renderMatchView() {
  const filter = document.getElementById("match-filter");
  filter.addEventListener("change", () => updateMatchList());
  updateMatchList();
}

function getAllEntries() {
  const list = [];
  state.pages.forEach(p => {
    p.entries.forEach(e => {
      list.push({ ...e, page_row: p.row_index });
    });
  });
  return list;
}

function updateMatchList() {
  const filterVal = document.getElementById("match-filter").value;
  const entries = getAllEntries();
  const filtered = entries.filter(e => {
    if (filterVal === "all") return true;
    return e.match && e.match.status === filterVal;
  });

  document.getElementById("entries-count").textContent = `${filtered.length} entries`;
  const container = document.getElementById("entries-list");
  container.innerHTML = "";

  filtered.forEach(entry => {
    const card = document.createElement("div");
    const isSelected = state.selectedEntryId === entry.entry_id;
    const status = entry.match ? entry.match.status : "unmatched";
    
    let statusBadge = "";
    if (status === "matched") statusBadge = `<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-800">MATCHED</span>`;
    else if (status === "rejected") statusBadge = `<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-100 text-rose-800">REJECTED</span>`;
    else statusBadge = `<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-100 text-slate-600">NO CANDIDATES</span>`;

    card.className = `p-3 rounded-lg border text-left cursor-pointer transition-all ${
      isSelected ? "border-indigo-500 bg-indigo-50/50 shadow-sm" : "border-slate-200 bg-white hover:border-slate-300"
    }`;

    card.innerHTML = `
      <div class="flex justify-between items-start mb-1">
        <span class="font-bold text-xs text-slate-900">${entry.headword || `[${entry.kind}]`}</span>
        ${statusBadge}
      </div>
      <div class="text-[11px] text-slate-500 line-clamp-2 mb-2">${entry.text}</div>
      <div class="flex justify-between items-center text-[10px] text-slate-400 font-mono">
        <span>ID: ${entry.entry_id}</span>
        <span>Page: ${entry.page_row}</span>
      </div>
    `;

    card.addEventListener("click", () => {
      selectEntryById(entry.entry_id);
    });

    container.appendChild(card);
  });

  if (!state.selectedEntryId && filtered.length > 0) {
    selectEntryById(filtered[0].entry_id);
  }
}

function selectEntryById(entryId) {
  state.selectedEntryId = entryId;
  const entries = getAllEntries();
  const entry = entries.find(e => e.entry_id === entryId);
  if (!entry) return;

  // Refresh selection visual in list
  updateMatchDetails(entry);
}

function updateMatchDetails(entry) {
  // Update Candidates Column
  const candPane = document.getElementById("candidates-list");
  candPane.innerHTML = "";

  const candidates = entry.match ? entry.match.candidates : [];
  if (candidates.length === 0) {
    candPane.innerHTML = `
      <div class="p-6 text-center text-slate-400 text-xs italic bg-slate-50 rounded-lg border border-dashed border-slate-200">
        No candidates retrieved from BM25 / pre-indexed Wikipedia API.
      </div>
    `;
  } else {
    candidates.forEach((cand, idx) => {
      const item = document.createElement("div");
      item.className = "p-3 bg-white border border-slate-200 rounded-lg space-y-2 shadow-xs";
      item.innerHTML = `
        <div class="flex justify-between items-center text-xs">
          <a href="${cand.url}" target="_blank" class="font-semibold text-indigo-600 hover:underline">
            #${idx + 1} ${cand.title}
          </a>
          <span class="text-[10px] text-slate-400 font-mono">BM25 Rank: ${cand.bm25_rank}</span>
        </div>
        <p class="text-[11px] text-slate-600 line-clamp-2">${cand.excerpt}</p>
        <div class="grid grid-cols-2 gap-2 text-[10px] font-mono pt-1 border-t border-slate-100 text-slate-500">
          <div>Embed Cosine: <strong class="text-slate-700">${cand.embed_cosine ?? "N/A"}</strong></div>
          <div>Rerank Logit: <strong class="text-slate-700">${cand.rerank_logit ?? "N/A"}</strong></div>
        </div>
      `;
      candPane.appendChild(item);
    });
  }

  // Update Decision Column
  const decisionPane = document.getElementById("match-decision-pane");
  const match = entry.match;
  if (!match) {
    decisionPane.innerHTML = `<div class="text-xs text-slate-400 italic">No match record found.</div>`;
    return;
  }

  let statusColor = match.status === "matched" ? "emerald" : (match.status === "rejected" ? "rose" : "slate");
  decisionPane.innerHTML = `
    <div class="p-4 rounded-lg bg-${statusColor}-50 border border-${statusColor}-200 space-y-3">
      <div class="flex justify-between items-center">
        <span class="text-xs font-bold uppercase tracking-wider text-${statusColor}-800">Status: ${match.status}</span>
        <span class="text-[10px] font-mono text-slate-500">${match.method_version}</span>
      </div>
      <div class="text-xs text-slate-700">
        <strong>Decision Rule:</strong>
        <p class="mt-0.5 font-mono text-[11px] text-slate-600 bg-white/70 p-1.5 rounded">${match.reason}</p>
      </div>
      <div class="text-xs text-slate-700">
        <strong>Rerank Margin (Top 1 - Top 2):</strong>
        <span class="ml-1 font-mono font-bold text-slate-900">${match.rerank_margin !== null ? match.rerank_margin : "N/A"}</span>
      </div>
      ${match.matched_wiki ? `
        <div class="p-3 bg-white rounded border border-${statusColor}-300">
          <div class="text-[10px] uppercase font-bold text-slate-400 mb-1">Final Matched Article</div>
          <div class="text-sm font-bold text-slate-900">
            <a href="${match.matched_wiki.url}" target="_blank" class="text-indigo-600 hover:underline">
              ${match.matched_wiki.title}
            </a>
          </div>
          <div class="text-[10px] text-slate-500 font-mono mt-1">
            Page ID: ${match.matched_wiki.page_id} · Rev: ${match.matched_wiki.revision_id}
          </div>
        </div>
      ` : `
        <div class="p-3 bg-white/50 rounded border border-slate-200 text-xs text-slate-500 italic">
          No Wikipedia article accepted under decision policy.
        </div>
      `}
    </div>
  `;
}

// --- VIEW 3: COMPARATIVE ANALYTICS ---
function renderAnalyticsView() {
  if (!state.drift) return;

  document.getElementById("drift-pairs").textContent = state.drift.pairs_used;
  document.getElementById("drift-brit-tokens").textContent = state.drift.brit_tokens.toLocaleString();
  document.getElementById("drift-wiki-tokens").textContent = state.drift.wiki_tokens.toLocaleString();

  const tbody = document.getElementById("drift-table-body");
  tbody.innerHTML = "";

  state.drift.terms.forEach(t => {
    const tr = document.createElement("tr");
    tr.className = "hover:bg-slate-50";

    const isArchaic = t.log_ratio > 0;
    const ratioBadge = isArchaic 
      ? `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-amber-100 text-amber-800 font-mono">+${t.log_ratio.toFixed(2)}</span>`
      : `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-blue-100 text-blue-800 font-mono">${t.log_ratio.toFixed(2)}</span>`;

    tr.innerHTML = `
      <td class="py-3 px-3 font-bold text-slate-900">${t.term}</td>
      <td class="py-3 px-3 text-right font-mono text-slate-700">${t.brit_count}</td>
      <td class="py-3 px-3 text-right font-mono text-slate-500">${t.brit_per_10k.toFixed(1)}</td>
      <td class="py-3 px-3 text-right font-mono text-slate-700">${t.wiki_count}</td>
      <td class="py-3 px-3 text-right font-mono text-slate-500">${t.wiki_per_10k.toFixed(1)}</td>
      <td class="py-3 px-3 text-center">${ratioBadge}</td>
      <td class="py-3 px-3 space-y-1 max-w-md">
        <div class="text-[11px] text-amber-900 bg-amber-50/60 p-1 rounded border-l-2 border-amber-400">
          <strong class="font-semibold text-amber-700">Britannica [${t.brit_example.entry_id}]:</strong> "${t.brit_example.quote}"
        </div>
        <div class="text-[11px] text-blue-900 bg-blue-50/60 p-1 rounded border-l-2 border-blue-400">
          <strong class="font-semibold text-blue-700">Wikipedia:</strong> "${t.wiki_example.quote}"
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

// --- VIEW 4: AGENT CONSOLE ---
function renderAgentView() {
  if (!state.cases || state.cases.length === 0) return;

  const switcher = document.getElementById("case-switcher");
  switcher.innerHTML = "";

  state.cases.forEach((c, idx) => {
    const btn = document.createElement("button");
    const isSuccess = c.type === "success" || c.label === "success";
    btn.className = `px-3 py-1 text-xs font-semibold rounded-md border transition-all ${
      idx === 0 
        ? "bg-slate-900 text-white border-slate-900" 
        : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
    }`;
    btn.textContent = `${isSuccess ? "✓" : "✗"} ${c.run_id}: ${c.category || c.label}`;
    btn.addEventListener("click", () => {
      document.querySelectorAll("#case-switcher button").forEach(b => {
        b.className = "px-3 py-1 text-xs font-semibold rounded-md border bg-white text-slate-700 border-slate-300 hover:bg-slate-50";
      });
      btn.className = "px-3 py-1 text-xs font-semibold rounded-md border bg-slate-900 text-white border-slate-900";
      showCase(c);
    });
    switcher.appendChild(btn);
  });

  showCase(state.cases[0]);
}

function showCase(run) {
  document.getElementById("agent-run-id").textContent = run.run_id;
  document.getElementById("agent-started-at").textContent = run.started_at;
  document.getElementById("agent-model").textContent = run.model;

  const badge = document.getElementById("agent-label-badge");
  const isSuccess = run.label === "success" || run.type === "success";
  badge.textContent = isSuccess ? "SUCCESSFUL GROUNDING" : "CALIBRATED REFUSAL / FAILURE";
  badge.className = `px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wider ${
    isSuccess ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"
  }`;

  document.getElementById("agent-question").textContent = run.question;
  document.getElementById("agent-answer").textContent = run.answer;
  document.getElementById("agent-notes").textContent = run.notes;

  // Tool Calls
  const toolContainer = document.getElementById("agent-tool-calls");
  toolContainer.innerHTML = "";
  if (run.tool_calls && run.tool_calls.length > 0) {
    run.tool_calls.forEach(tc => {
      const box = document.createElement("div");
      box.className = "p-2.5 bg-slate-100 rounded border border-slate-200 text-xs font-mono";
      box.innerHTML = `
        <div class="flex items-center space-x-2 text-indigo-700 font-bold mb-1">
          <span>⚡ Tool Invocation:</span>
          <span>${tc.name}</span>
        </div>
        <div class="text-[11px] text-slate-600">Args: ${JSON.stringify(tc.arguments)}</div>
        <div class="text-[11px] text-slate-800 mt-1">Result: ${tc.result}</div>
      `;
      toolContainer.appendChild(box);
    });
  } else {
    toolContainer.innerHTML = `<div class="text-xs text-slate-400 italic">No tools called.</div>`;
  }

  // Citations
  const citContainer = document.getElementById("agent-citations");
  citContainer.innerHTML = "";
  if (run.citations && run.citations.length > 0) {
    run.citations.forEach(cit => {
      const card = document.createElement("div");
      const isBrit = cit.source.toLowerCase().includes("britannica");
      card.className = `p-3 rounded border text-xs ${
        isBrit ? "bg-amber-50/70 border-amber-200 text-amber-900" : "bg-blue-50/70 border-blue-200 text-blue-900"
      }`;
      card.innerHTML = `
        <div class="font-bold flex justify-between items-center mb-1">
          <span>${cit.source}</span>
          <span class="font-mono text-[10px]">${cit.id}</span>
        </div>
        <p class="italic text-[11px]">"${cit.quote}"</p>
      `;
      citContainer.appendChild(card);
    });
  } else {
    citContainer.innerHTML = `<div class="text-xs text-slate-400 italic">No citations recorded.</div>`;
  }
}
