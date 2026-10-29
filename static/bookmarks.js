/*
 * bookmarks.js (Profile page only)
 * --------------------------------
 * The bookmark manager:
 *   - Reload   : send the sequence to the Analysis page
 *   - Rename   : edit the name in place (Enter or clicking away saves, Esc cancels)
 *   - Delete   : remove one bookmark
 *   - Sort     : newest / oldest / name A-Z / name Z-A / "my own order" (drag)
 *   - Groups   : create, rename, delete, and move bookmarks between them
 *
 * Everything the user typed (bookmark and group names) is put on the page with textContent, never innerHTML, so a name like <b>hi</b>
 * shows up as plain text.
 */

const sectionsEl = document.getElementById("bookmark-sections");
const sortSelect = document.getElementById("bookmark-sort");
const messageEl = document.getElementById("bookmark-message");
const newGroupInput = document.getElementById("new-group-name");

let bookmarks = [];           // [{id, name, group_id, position, created_at, input_type, length, snippet}]
let groups = [];              // [{id, name}]
let sortMode = "date-desc";
const collapsed = new Set();  // sections the user folded away (this visit only)
let messageTimer = null;

try {
  sortMode = localStorage.getItem("dptlite-bookmark-sort") || "date-desc";
} catch (err) { /* storage can be blocked; the default is fine */ }
sortSelect.value = sortMode;

const UNITS = { DNA: "bp", RNA: "nt", PROTEIN: "aa" };

// ---------- tiny helpers ----------
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(method, url, body) {
  const options = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) options.body = JSON.stringify(body);
  const res = await fetch(url, options);
  let data = {};
  try { data = await res.json(); } catch (err) { /* empty body */ }
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

function showMessage(text, isError) {
  messageEl.textContent = text;
  messageEl.classList.toggle("error-text", !!isError);
  messageEl.hidden = false;
  clearTimeout(messageTimer);
  messageTimer = setTimeout(() => { messageEl.hidden = true; }, 4000);
}

async function loadAll() {
  try {
    [bookmarks, groups] = await Promise.all([
      api("GET", "/api/bookmarks"),
      api("GET", "/api/bookmark-groups"),
    ]);
    render();
  } catch (err) {
    sectionsEl.replaceChildren(el("p", "muted small", "Could not load your bookmarks."));
  }
}

// ---------- sorting ----------
function sortList(list) {
  const byName = (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
  const copy = [...list];
  switch (sortMode) {
    case "date-asc":  return copy.sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id - b.id);
    case "name-asc":  return copy.sort((a, b) => byName(a, b) || a.id - b.id);
    case "name-desc": return copy.sort((a, b) => byName(b, a) || a.id - b.id);
    case "custom":    return copy.sort((a, b) => a.position - b.position || a.id - b.id);
    default:          return copy.sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
  }
}

sortSelect.addEventListener("change", () => {
  sortMode = sortSelect.value;
  try { localStorage.setItem("dptlite-bookmark-sort", sortMode); } catch (err) { /* ignore */ }
  render();
});

// ---------- rendering ----------
function render() {
  sectionsEl.replaceChildren();
  sectionsEl.classList.toggle("custom-mode", sortMode === "custom");

  if (!bookmarks.length && !groups.length) {
    sectionsEl.append(el("p", "muted small", "No bookmarks yet \u2014 save one from the Analysis page."));
    return;
  }
  if (sortMode === "custom") {
    sectionsEl.append(el("p", "muted small", "Drag the \u283F handle to arrange bookmarks. Order is kept inside each group."));
  }

  const sortedGroups = [...groups].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  sortedGroups.forEach((group) => {
    sectionsEl.append(buildSection(group, bookmarks.filter((b) => b.group_id === group.id)));
  });
  const ungrouped = bookmarks.filter((b) => b.group_id === null || b.group_id === undefined);
  if (ungrouped.length || !groups.length) {
    sectionsEl.append(buildSection(null, ungrouped));
  }
}

function buildSection(group, items) {
  const key = group ? String(group.id) : "ungrouped";
  const section = el("div", "bookmark-section");

  // A header is only needed once groups exist.
  if (group || groups.length) {
    const header = el("div", "bookmark-section-header");
    const toggle = el("button", "bookmark-toggle", collapsed.has(key) ? "\u25B8" : "\u25BE");
    toggle.type = "button";
    toggle.title = "Fold / unfold";
    const title = el("strong", "bookmark-section-title", group ? group.name : "Ungrouped");
    const count = el("span", "muted small", `${items.length} bookmark${items.length === 1 ? "" : "s"}`);
    header.append(toggle, title, count);

    if (group) {
      const actions = el("div", "bookmark-actions");
      const renameBtn = el("button", "btn-ghost btn-small", "Rename");
      const deleteBtn = el("button", "btn-ghost btn-small", "Delete group");
      renameBtn.type = deleteBtn.type = "button";
      renameBtn.addEventListener("click", () =>
        startInlineEdit(title, group.name, async (value) => {
          await api("PATCH", `/api/bookmark-groups/${group.id}`, { name: value });
          group.name = value;
        })
      );
      deleteBtn.addEventListener("click", () => deleteGroup(group));
      actions.append(renameBtn, deleteBtn);
      header.append(actions);
    }
    section.append(header);
    toggle.addEventListener("click", () => {
      collapsed.has(key) ? collapsed.delete(key) : collapsed.add(key);
      render();
    });
  }

  const body = el("div", "bookmark-list");
  body.hidden = collapsed.has(key);
  if (!items.length) {
    body.append(el("p", "muted small bookmark-empty",
      group ? "Nothing in this group yet \u2014 move a bookmark here with its group menu." : "Nothing here."));
  }
  sortList(items).forEach((b) => body.append(buildRow(b)));
  enableDropZone(body);
  section.append(body);
  return section;
}

function buildRow(b) {
  const row = el("div", "bookmark-entry");
  row.dataset.id = b.id;

  // name + details (the drag handle only shows in "my own order" mode)
  const nameCell = el("div", "bookmark-name-cell");
  const handle = el("span", "bookmark-handle", "\u283F");
  handle.title = "Drag to reorder";
  const text = el("div");
  const nameEl = el("strong", "bookmark-name", b.name);
  const unit = UNITS[b.input_type] || "letters";
  const meta = el("div", "muted small",
    `${b.input_type} \u00B7 ${b.length.toLocaleString()} ${unit} \u00B7 saved ${b.created_at.slice(0, 10)}`);
  text.append(nameEl, meta);
  nameCell.append(handle, text);

  const snippet = el("code", "mono snippet bookmark-snippet", b.snippet + (b.length > b.snippet.length ? "\u2026" : ""));

  const cells = [nameCell, snippet];

  if (groups.length) {
    const select = el("select", "bookmark-group-select");
    select.setAttribute("aria-label", "Group");
    select.append(new Option("No group", ""));
    [...groups]
      .sort((x, y) => x.name.localeCompare(y.name, undefined, { sensitivity: "base" }))
      .forEach((g) => select.append(new Option(g.name, g.id)));
    select.value = b.group_id === null || b.group_id === undefined ? "" : String(b.group_id);
    select.addEventListener("change", () => moveToGroup(b, select.value === "" ? null : Number(select.value)));
    cells.push(select);
  }

  const actions = el("div", "bookmark-actions");
  const reloadBtn = el("button", "btn-ghost btn-small", "Reload");
  const renameBtn = el("button", "btn-ghost btn-small", "Rename");
  const deleteBtn = el("button", "btn-ghost btn-small", "Delete");
  reloadBtn.type = renameBtn.type = deleteBtn.type = "button";
  reloadBtn.addEventListener("click", () => reloadBookmark(b));
  renameBtn.addEventListener("click", () =>
    startInlineEdit(nameEl, b.name, async (value) => {
      await api("PATCH", `/api/bookmarks/${b.id}`, { name: value });
      b.name = value;
    })
  );
  deleteBtn.addEventListener("click", () => deleteBookmark(b));
  actions.append(reloadBtn, renameBtn, deleteBtn);
  cells.push(actions);

  row.append(...cells);
  if (sortMode === "custom") enableDrag(row, handle);
  return row;
}

// ---------- rename in place ----------
// Swaps the name for a text box. Enter or clicking away saves; Esc cancels.
function startInlineEdit(textEl, currentValue, onSave) {
  const input = el("input", "inline-edit");
  input.type = "text";
  input.maxLength = 60;
  input.value = currentValue;
  textEl.replaceWith(input);
  input.focus();
  input.select();

  let finished = false;
  async function finish(save) {
    if (finished) return;
    finished = true;
    const value = input.value.trim();
    if (save && value && value !== currentValue) {
      try {
        await onSave(value);
      } catch (err) {
        showMessage(err.message, true);
      }
    }
    render();
  }
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") finish(true);
    else if (event.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
}

// ---------- actions ----------
async function reloadBookmark(b) {
  try {
    const data = await api("GET", `/api/bookmarks/${b.id}`);
    // Same hand-off the History page uses: the Analysis page reads this on load.
    sessionStorage.setItem("dptlite-preload-sequence", data.sequence);
    window.location.href = "/analysis";
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function deleteBookmark(b) {
  if (!confirm(`Delete the bookmark "${b.name}"?`)) return;
  try {
    await api("DELETE", `/api/bookmarks/${b.id}`);
    bookmarks = bookmarks.filter((x) => x.id !== b.id);
    render();
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function moveToGroup(b, groupId) {
  try {
    await api("PATCH", `/api/bookmarks/${b.id}`, { group_id: groupId });
    b.group_id = groupId;
    // Put it at the end of its new group's "my own order" so it doesn't land somewhere random.
    const others = sortByPosition(bookmarks.filter((x) => x.group_id === groupId && x.id !== b.id));
    await saveOrder([...others, b].map((x) => x.id));
    render();
  } catch (err) {
    showMessage(err.message, true);
    loadAll();
  }
}

function sortByPosition(list) {
  return [...list].sort((a, b) => a.position - b.position || a.id - b.id);
}

async function createGroup() {
  const name = newGroupInput.value.trim();
  if (!name) return;
  try {
    const group = await api("POST", "/api/bookmark-groups", { name });
    groups.push(group);
    newGroupInput.value = "";
    render();
    showMessage(`Group "${group.name}" created. Use the group menu on a bookmark to move it in.`);
  } catch (err) {
    showMessage(err.message, true);
  }
}
document.getElementById("new-group-btn").addEventListener("click", createGroup);
newGroupInput.addEventListener("keydown", (event) => { if (event.key === "Enter") createGroup(); });

async function deleteGroup(group) {
  if (!confirm(`Delete the group "${group.name}"? Its bookmarks are kept and become ungrouped.`)) return;
  try {
    await api("DELETE", `/api/bookmark-groups/${group.id}`);
    groups = groups.filter((g) => g.id !== group.id);
    bookmarks.forEach((b) => { if (b.group_id === group.id) b.group_id = null; });
    render();
  } catch (err) {
    showMessage(err.message, true);
  }
}

// ---------- drag to reorder ("my own order" mode) ----------
let dragged = null;

function enableDrag(row, handle) {
  // Only the handle starts a drag, so selecting text or using the Rename box still works.
  handle.addEventListener("mousedown", () => { row.draggable = true; });
  handle.addEventListener("mouseup", () => { row.draggable = false; });

  row.addEventListener("dragstart", (event) => {
    dragged = row;
    row.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", row.dataset.id);
  });
  row.addEventListener("dragend", async () => {
    row.classList.remove("dragging");
    row.draggable = false;
    const list = row.parentElement;
    dragged = null;
    if (list) await saveOrder([...list.querySelectorAll(".bookmark-entry")].map((r) => Number(r.dataset.id)));
  });
}

// Rows can only be dropped inside the list (group) they came from.
function enableDropZone(list) {
  list.addEventListener("dragover", (event) => {
    if (!dragged || dragged.parentElement !== list) return;
    event.preventDefault();
    const next = [...list.querySelectorAll(".bookmark-entry:not(.dragging)")].find((r) => {
      const box = r.getBoundingClientRect();
      return event.clientY < box.top + box.height / 2;
    });
    if (next) list.insertBefore(dragged, next);
    else list.append(dragged);
  });
  list.addEventListener("drop", (event) => event.preventDefault());
}

async function saveOrder(ids) {
  ids.forEach((id, index) => {
    const b = bookmarks.find((x) => x.id === id);
    if (b) b.position = index;
  });
  try {
    await api("PUT", "/api/bookmarks/order", { ids });
  } catch (err) {
    showMessage(err.message, true);
  }
}

loadAll();
