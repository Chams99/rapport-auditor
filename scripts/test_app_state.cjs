const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class FakeElement {
  constructor(id = "", tagName = "div") {
    this.id = id;
    this.tagName = tagName;
    this.dataset = {};
    this.attributes = new Map();
    this.listeners = new Map();
    this.selectors = new Map();
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.value = "";
    this.files = [];
    this.children = [];
    this.parentElement = null;
    this.clicked = false;
    this.focused = false;
    this.classes = new Set();
    Object.defineProperty(this, "className", {
      get: () => [...this.classes].join(" "),
      set: (value) => { this.classes = new Set(String(value).split(/\s+/).filter(Boolean)); },
    });
    this.classList = {
      add: (...names) => names.forEach((name) => this.classes.add(name)),
      remove: (...names) => names.forEach((name) => this.classes.delete(name)),
      contains: (name) => this.classes.has(name),
      toggle: (name, force) => {
        const enabled = force === undefined ? !this.classes.has(name) : force;
        if (enabled) this.classes.add(name);
        else this.classes.delete(name);
        return enabled;
      },
    };
  }

  addEventListener(type, callback) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(callback);
    this.listeners.set(type, listeners);
  }

  dispatch(type, detail = {}) {
    let prevented = false;
    const event = {
      type,
      target: this,
      preventDefault() { prevented = true; },
      ...detail,
    };
    for (const callback of this.listeners.get(type) || []) callback(event);
    return { event, prevented };
  }

  dispatchEvent(event) {
    this.dispatch(event.type, { target: this });
    return true;
  }

  querySelector(selector) { return this.selectors.get(selector) || null; }

  querySelectorAll(selector) {
    if (selector === 'button[type="submit"]') return this.submitButtons || [];
    return this.selectorLists?.get(selector) || [];
  }

  append(...items) {
    for (const item of items) {
      if (typeof item === "string") continue;
      item.parentElement = this;
      this.children.push(item);
    }
  }

  prepend(item) {
    item.parentElement = this;
    this.children.unshift(item);
  }

  after() {}
  replaceWith() {}
  closest() { return null; }
  focus() { this.focused = true; }
  scrollIntoView() {}
  setSelectionRange() {}
  click() { this.clicked = true; this.dispatch("click"); }

  remove() {
    if (!this.parentElement) return;
    this.parentElement.children = this.parentElement.children.filter((item) => item !== this);
    this.parentElement = null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "hidden") this.hidden = true;
  }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) {
    this.attributes.delete(name);
    if (name === "hidden") this.hidden = false;
  }
}

class FakeButton extends FakeElement {}

class FakeEvent {
  constructor(type) { this.type = type; }
}

class FakeFileList {
  constructor(items) {
    this.items = items;
    Object.defineProperty(this, "0", { get: () => this.items[0] });
  }
  get length() { return this.items.length; }
  item(index) { return this.items[index] || null; }
  [Symbol.iterator]() { return this.items[Symbol.iterator](); }
}

class FakeDataTransfer {
  constructor() {
    this._items = [];
    this.files = new FakeFileList(this._items);
    this.items = { add: (file) => this._items.push(file) };
  }
}

function makeButton(label, loadingEn, loadingFr) {
  const button = new FakeButton("", "button");
  button.dataset.loadingLabelEn = loadingEn;
  button.dataset.loadingLabelFr = loadingFr;
  button.children = [];
  button.selectors.set(".button-label", Object.assign(new FakeElement(), { textContent: label }));
  button.selectors.set(".button-spinner", Object.assign(new FakeElement(), { hidden: true }));
  button.selectors.set(".button-arrow", Object.assign(new FakeElement(), { hidden: false }));
  return button;
}

function boot({ locale = "en", optionalFormHelpers = true, fileControls = true, results = false, downloads = false } = {}) {
  const elements = new Map();
  const add = (id, element = new FakeElement(id)) => { elements.set(id, element); return element; };
  const form = add("report-form");
  form.dataset.maxChars = "5";
  const text = add("report-text");
  const language = add("content-language");
  language.value = locale;
  const file = add("report-file");
  const liveFileItems = [];
  const liveFiles = new FakeFileList(liveFileItems);
  Object.defineProperty(file, "files", {
    get() { return liveFiles; },
    set(value) { liveFileItems.splice(0, liveFileItems.length, ...Array.from(value || [])); },
  });
  Object.defineProperty(file, "value", {
    get() { return this._value || ""; },
    set(value) { this._value = value; if (!value) liveFileItems.length = 0; },
  });
  const format = add("source-format");
  format.value = "tex";
  const count = add("character-count");
  const clear = optionalFormHelpers ? add("clear-text", new FakeButton("clear-text", "button")) : null;
  const example = optionalFormHelpers ? add("load-example", new FakeButton("load-example", "button")) : null;
  const copySample = add("copy-sample");
  copySample.hidden = false;
  if (example) {
    example.hidden = true;
    example.dataset.sampleEn = "Synthetic example.";
    example.dataset.sampleFr = "Exemple fictif.";
  }
  if (clear) {
    clear.hidden = true;
    clear.disabled = true;
    clear.selectors.set("span", Object.assign(new FakeElement(), { textContent: "Clear" }));
  }
  const fileChip = fileControls ? add("file-chip") : null;
  if (fileChip) fileChip.hidden = true;
  const fileName = fileControls ? add("file-name") : null;
  const removeFile = fileControls ? add("remove-file", new FakeButton("remove-file", "button")) : null;
  if (removeFile) { removeFile.hidden = true; removeFile.disabled = true; }
  const fileError = add("file-error");
  fileError.hidden = true;
  const textError = add("text-error");
  textError.hidden = true;
  const status = add("submission-status");
  const page = add("page-content");
  page.dataset.mode = "input";
  const auditButton = makeButton("Review", "Reviewing…", "Analyse…");
  const reviseButton = makeButton("Revise", "Preparing…", "Préparation…");
  form.submitButtons = [auditButton, reviseButton];
  form.selectors.set(".button-primary", auditButton);

  const downloaded = [];
  const body = new FakeElement("body", "body");
  body.append = (...items) => {
    FakeElement.prototype.append.apply(body, items);
    items.filter((item) => item.tagName === "a").forEach((anchor) => downloaded.push(anchor));
  };
  const documentElement = new FakeElement("html", "html");
  documentElement.lang = locale;
  documentElement.dataset = {};
  const created = [];
  const queryResults = new Map();
  let resultsScroll = null;
  let statusPill = null;
  if (results) {
    resultsScroll = new FakeElement("", "div");
    const visibleResult = new FakeElement("visible-result");
    const alreadyHidden = new FakeElement("hidden-result");
    alreadyHidden.hidden = true;
    resultsScroll.append(visibleResult, alreadyHidden);
    statusPill = new FakeElement("", "span");
    statusPill.lastChild = { textContent: "Ready" };
  }

  const sourceHeading = new FakeElement("", "h3");
  sourceHeading.dataset.sourceName = "Student Draft/Final.txt";
  sourceHeading.textContent = locale === "fr" ? "Texte collé" : "Pasted text";
  const cleanedSource = new FakeElement("", "textarea");
  cleanedSource.value = "Synthetic cleaned text.";
  const downloadButton = new FakeButton("", "button");
  downloadButton.dataset.download = "cleaned";
  downloadButton.hidden = true;
  const exportButton = new FakeButton("", "button");
  exportButton.hidden = true;

  const queryOne = new Map([
    [".page-content", page],
    [".results-scroll", resultsScroll],
    [".results-heading-row .status-pill", statusPill],
    ["[data-export-notes]", downloads ? exportButton : null],
    [".source-name", downloads ? sourceHeading : null],
    ['[data-download-source="cleaned"]', downloads ? cleanedSource : null],
  ]);
  const document = {
    documentElement,
    body,
    activeElement: null,
    getElementById: (id) => elements.get(id) || null,
    querySelector: (selector) => queryOne.get(selector) || null,
    querySelectorAll(selector) {
      if (selector === ".js-only" || selector === "[data-mod-key]" || selector === "data[data-number]"
        || selector === ".line-reference[data-line]" || selector === ".form-alert-list a[href^='#']"
        || selector === ".finding-list > .finding-card" || selector === ".edit-compare" || selector === ".copy-button"
        || selector === ".stat-value data[data-number]" || selector === "[data-open-shortcuts]"
        || selector === ".results-scroll .content-section" || selector === ".document-stat") return [];
      if (selector === "[data-download]") return downloads ? [downloadButton] : [];
      if (selector === ".top-progress, .results-skeleton") {
        return created.filter((element) => element.classList.contains("top-progress") || element.classList.contains("results-skeleton"));
      }
      return queryResults.get(selector) || [];
    },
    createElement(tagName) {
      const element = new FakeElement("", tagName);
      created.push(element);
      return element;
    },
    addEventListener() {},
  };

  let nextConfirm = true;
  let nextTimer = 0;
  const windowListeners = new Map();
  const window = {
    isSecureContext: false,
    confirm: () => nextConfirm,
    setTimeout: () => ++nextTimer,
    clearTimeout() {},
    addEventListener(type, callback) {
      const listeners = windowListeners.get(type) || [];
      listeners.push(callback);
      windowListeners.set(type, listeners);
    },
    dispatch(type, detail = {}) {
      let prevented = false;
      const event = { type, preventDefault() { prevented = true; }, ...detail };
      for (const callback of windowListeners.get(type) || []) callback(event);
      return { event, prevented };
    },
  };
  const URL = {
    createObjectURL: () => `blob:synthetic-${downloaded.length}`,
    revokeObjectURL() {},
  };
  const source = fs.readFileSync(path.join(__dirname, "..", "apps", "web", "rapport_web", "static", "app.js"), "utf8");
  vm.runInNewContext(source, {
    document,
    window,
    navigator: { platform: "Win32", userAgent: "synthetic-test" },
    matchMedia: () => ({ matches: true }),
    HTMLButtonElement: FakeButton,
    Event: FakeEvent,
    DataTransfer: FakeDataTransfer,
    Intl,
    URL,
    Blob: class Blob {},
    console,
  }, { filename: "app.js" });
  window.dispatch("pageshow", { persisted: false });
  return {
    elements, form, text, language, file, format, count, clear, example, copySample, fileChip, fileName, removeFile,
    fileError, textError, status, auditButton, reviseButton, page, body, documentElement, window, downloaded,
    resultsScroll, sourceHeading, exportButton, downloadButton,
    setConfirm(value) { nextConfirm = value; },
  };
}

function testFileEnhancementAndUndo() {
  const ui = boot();
  assert.equal(ui.documentElement.classList.contains("js-ready"), true, "custom picker should activate only after its full DOM path exists");
  assert.equal(ui.example.hidden, false, "a complete synthetic example should be exposed");
  assert.equal(ui.copySample.hidden, true, "manual-copy fallback hides only after sample enhancement succeeds");
  assert.equal(ui.removeFile.hidden, true);
  assert.equal(ui.removeFile.disabled, true);
  assert.equal(ui.clear.hidden, false);

  ui.format.value = "txt";
  ui.format.dispatch("change");
  ui.text.value = "keep draft";
  ui.text.dispatch("input");
  assert.equal(ui.count.classList.contains("is-over-limit"), true);
  ui.file.files = [{ name: "chapter.tex", size: 28 }];
  ui.file.dispatch("change");
  assert.equal(ui.fileChip.hidden, false);
  assert.equal(ui.fileName.textContent, "chapter.tex");
  assert.equal(ui.removeFile.hidden, false);
  assert.equal(ui.removeFile.disabled, false);
  assert.equal(ui.format.value, "tex");
  assert.equal(ui.format.disabled, true, "an upload determines its own format");
  assert.equal(ui.count.classList.contains("is-over-limit"), false, "ignored pasted text must not appear invalid while a file takes precedence");

  ui.removeFile.dispatch("click");
  assert.equal(ui.text.value, "keep draft", "removing an upload must preserve pasted text");
  assert.equal(ui.format.value, "txt", "removing an upload restores the pasted format");
  assert.equal(ui.format.disabled, false);
  assert.equal(ui.fileChip.hidden, true);
  assert.equal(ui.removeFile.hidden, true);
  assert.equal(ui.removeFile.disabled, true);
  assert.equal(ui.count.classList.contains("is-over-limit"), true, "the pasted-text limit returns when the upload is removed");

  ui.file.files = [{ name: "too-large.txt", size: 1000001 }];
  ui.file.dispatch("change");
  assert.equal(ui.file.getAttribute("aria-invalid"), "true");
  assert.match(ui.fileError.textContent, /1\.0 MB/);
  const rejected = ui.form.dispatch("submit", { submitter: ui.auditButton });
  assert.equal(rejected.prevented, true, "the browser limit fallback must match the 1,000,000-byte server limit");

  ui.file.files = [{ name: "chapter.txt", size: 32 }];
  ui.file.dispatch("change");
  ui.clear.dispatch("click");
  assert.equal(ui.text.value, "");
  assert.equal(ui.file.files.length, 0);
  assert.equal(ui.clear.querySelector("span").textContent, "Undo");
  assert.equal(ui.removeFile.hidden, true, "Clear must synchronize the optional file action");
  ui.clear.dispatch("click");
  assert.equal(ui.text.value, "keep draft");
  assert.equal(ui.file.files[0].name, "chapter.txt", "Undo restores the original selected file when supported by the browser");
  assert.equal(ui.format.value, "txt");

  ui.setConfirm(false);
  ui.example.dispatch("click");
  assert.equal(ui.text.value, "keep draft", "canceling sample replacement preserves the draft");
  ui.setConfirm(true);
  ui.example.dispatch("click");
  assert.equal(ui.text.value, "Synthetic example.");
}

function testOptionalHooksSubmissionAndBfcache() {
  const ui = boot({ locale: "fr", optionalFormHelpers: false, fileControls: false });
  assert.equal(ui.documentElement.classList.contains("js-ready"), false, "partial picker hooks must retain the native file input");
  assert.equal(ui.text.focused, false, "initial pageshow must not steal focus");
  const empty = ui.form.dispatch("submit", { submitter: ui.auditButton });
  assert.equal(empty.prevented, true, "missing helper buttons must not disable required form validation");
  assert.equal(ui.text.getAttribute("aria-invalid"), "true");

  ui.text.value = "salut";
  ui.text.dispatch("input");
  const submit = ui.form.dispatch("submit", { submitter: ui.reviseButton });
  assert.equal(submit.prevented, false);
  assert.equal(ui.reviseButton.querySelector(".button-label").textContent, "Préparation…");
  assert.equal(ui.reviseButton.querySelector(".button-spinner").hidden, false);
  assert.equal(ui.reviseButton.querySelector(".button-arrow").hidden, true);
  assert.equal(ui.auditButton.disabled, true);
  assert.equal(ui.form.dispatch("submit", { submitter: ui.auditButton }).prevented, true, "duplicate submission is canceled");

  ui.text.value = "restored browser draft";
  ui.text.focused = false;
  ui.window.dispatch("pageshow", { persisted: true });
  assert.equal(ui.reviseButton.disabled, false);
  assert.equal(ui.reviseButton.querySelector(".button-label").textContent, "Revise");
  assert.equal(ui.reviseButton.querySelector(".button-spinner").hidden, true);
  assert.equal(ui.reviseButton.querySelector(".button-arrow").hidden, false);
  assert.equal(ui.count.textContent, "22 / 5");
  assert.equal(ui.text.focused, false, "BFCache restoration must not steal focus");
  assert.equal(ui.window.dispatch("beforeunload").event.returnValue, "", "restored input remains protected from accidental loss");

  const restoredUi = boot();
  restoredUi.text.value = "browser-restored";
  restoredUi.file.files = [{ name: "restored.tex", size: 11 }];
  restoredUi.text.setAttribute("aria-invalid", "true");
  restoredUi.fileError.hidden = false;
  restoredUi.window.dispatch("pageshow", { persisted: true });
  assert.equal(restoredUi.count.textContent, "16 / 5");
  assert.equal(restoredUi.fileName.textContent, "restored.tex");
  assert.equal(restoredUi.format.disabled, true);
  assert.equal(restoredUi.format.value, "tex");
  assert.equal(restoredUi.fileError.hidden, false, "pageshow must preserve server-rendered upload errors");
  assert.equal(restoredUi.text.getAttribute("aria-invalid"), "true", "pageshow must preserve server-rendered text errors");

  const resultsUi = boot({ results: true });
  resultsUi.text.value = "valid";
  resultsUi.text.dispatch("input");
  resultsUi.form.dispatch("submit", { submitter: resultsUi.auditButton });
  assert.deepEqual(resultsUi.resultsScroll.children.map((child) => child.hidden), [false, true, true]);
  resultsUi.window.dispatch("pageshow", { persisted: true });
  assert.deepEqual(resultsUi.resultsScroll.children.map((child) => child.hidden), [false, true], "BFCache restores only the original result visibility states");
}

function testOriginalSourceNamesDriveDownloadNames() {
  const ui = boot({ downloads: true });
  ui.downloadButton.click();
  assert.equal(ui.downloaded.at(-1).download, "Student Draft-Final_cleaned.txt");
  assert.equal(ui.downloaded.at(-1).clicked, true);
  ui.exportButton.click();
  assert.equal(ui.downloaded.at(-1).download, "Student Draft-Final_review_notes.md", "localized display names must not replace the original source filename");
}

testFileEnhancementAndUndo();
testOptionalHooksSubmissionAndBfcache();
testOriginalSourceNamesDriveDownloadNames();
console.log("app state regressions passed");
