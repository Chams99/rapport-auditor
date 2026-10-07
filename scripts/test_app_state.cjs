const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this.dataset = {};
    this.attributes = new Map();
    this.listeners = new Map();
    this.children = new Map();
    this.hidden = true;
    this.disabled = false;
    this.textContent = "";
    this.value = "";
    this.files = [];
    this.focused = false;
    this.classes = new Set();
    this.classList = {
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
      target: this,
      preventDefault() { prevented = true; },
      ...detail,
    };
    for (const callback of this.listeners.get(type) || []) callback(event);
    return { event, prevented };
  }

  querySelector(selector) {
    return this.children.get(selector) || null;
  }

  querySelectorAll(selector) {
    if (selector === 'button[type="submit"]') return this.submitButtons || [];
    if (selector === "[data-review-filter]") return this.filterButtons || [];
    return [];
  }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }
  focus() { this.focused = true; }
}

class FakeButton extends FakeElement {}

function makeButton(label, loadingEn, loadingFr) {
  const button = new FakeButton();
  button.dataset.loadingLabelEn = loadingEn;
  button.dataset.loadingLabelFr = loadingFr;
  button.children.set(".button-label", Object.assign(new FakeElement(), { textContent: label }));
  button.children.set(".button-spinner", Object.assign(new FakeElement(), { hidden: true }));
  button.children.set(".button-arrow", Object.assign(new FakeElement(), { hidden: false }));
  return button;
}

function boot(locale = "en", categories = ["writing", "source"], mode = "audit", options = {}) {
  const elements = new Map();
  const add = (id, element = new FakeElement(id)) => { elements.set(id, element); return element; };
  const form = add("report-form");
  form.dataset.maxChars = "5";
  const text = add("report-text");
  const language = add("content-language");
  language.value = locale;
  const file = add("report-file");
  Object.defineProperty(file, "value", {
    get() { return this._value || ""; },
    set(value) { this._value = value; if (!value) this.files = []; },
  });
  const format = add("source-format");
  format.value = "tex";
  const count = add("character-count");
  const clear = options.includeHelpers === false ? null : add("clear-text");
  const example = options.includeHelpers === false ? null : add("load-example");
  const sampleDisclosure = add("copy-sample");
  sampleDisclosure.hidden = false;
  if (example) {
    example.dataset.sampleEn = options.invalidExample ? " " : "Synthetic sample.";
    example.dataset.sampleFr = options.invalidExample ? "" : "Exemple fictif.";
  }
  const filename = add("file-name");
  const fileError = add("file-error");
  const textError = add("text-error");
  const status = add("submission-status");
  const editorState = add("editor-state");
  const editorText = add("editor-state-text");
  const removeFile = add("remove-file");
  const stale = add("results-stale");
  const filters = add("review-filters");
  const filterStatus = add("filter-status");
  const filterEmpty = add("filter-empty");
  const allButton = new FakeButton();
  allButton.dataset.reviewFilter = "all";
  const writingButton = new FakeButton();
  writingButton.dataset.reviewFilter = "writing";
  const sourceButton = new FakeButton();
  sourceButton.dataset.reviewFilter = "source";
  filters.filterButtons = [allButton, writingButton, sourceButton];
  const cards = categories.map((category) => {
    const card = new FakeElement();
    card.dataset.reviewCategory = category;
    return card;
  });
  const auditButton = makeButton("Review", "Reviewing…", "Analyse…");
  const reviseButton = makeButton("Revise", "Preparing…", "Préparation…");
  form.submitButtons = [auditButton, reviseButton];
  const page = new FakeElement();
  page.dataset.mode = mode;
  const windowListeners = new Map();
  let nextConfirm = true;
  const document = {
    documentElement: { lang: locale },
    activeElement: null,
    getElementById: (id) => elements.get(id) || null,
    querySelector: (selector) => selector === ".page-content" ? page
      : selector === ".editor-state" ? editorState
        : null,
    querySelectorAll: (selector) => selector === '.evidence-card[data-review-category]' ? cards
      : selector === "[data-download]" ? []
        : [],
    createElement: () => new FakeElement(),
  };
  const window = {
    confirm: () => nextConfirm,
    setTimeout,
    addEventListener(type, callback) {
      const listeners = windowListeners.get(type) || [];
      listeners.push(callback);
      windowListeners.set(type, listeners);
    },
    dispatch(type, event = {}) {
      const dispatched = { preventDefault() {}, ...event };
      for (const callback of windowListeners.get(type) || []) callback(dispatched);
      return dispatched;
    },
  };
  const source = fs.readFileSync(path.join(__dirname, "..", "apps", "web", "rapport_web", "static", "app.js"), "utf8");
  vm.runInNewContext(source, {
    document,
    window,
    HTMLButtonElement: FakeButton,
    Intl,
    URL: {},
    Blob: class Blob {},
    console,
  }, { filename: "app.js" });
  window.dispatch("pageshow", { persisted: false });
  return {
    elements, form, text, language, file, format, count, clear, example, filename, fileError, textError, status,
    editorState, editorText, removeFile, sampleDisclosure, stale, filters, filterStatus, filterEmpty, allButton, writingButton,
    sourceButton, cards, auditButton, reviseButton, window, setConfirm(value) { nextConfirm = value; },
  };
}

function testStateAndDraftControls() {
  const ui = boot();
  assert.equal(ui.example.hidden, false, "a complete sample should enhance the visible sample action");
  assert.equal(ui.sampleDisclosure.hidden, true, "the manual-copy fallback should hide only after enhancement succeeds");
  assert.equal(ui.text.focused, false, "initial pageshow must not move focus");
  assert.equal(ui.editorState.dataset.state, "empty");
  ui.text.value = "draft";
  ui.text.dispatch("input");
  assert.equal(ui.editorState.dataset.state, "ready");
  assert.equal(ui.stale.hidden, false);

  ui.stale.hidden = true;
  ui.language.value = "fr";
  ui.language.dispatch("change");
  assert.equal(ui.stale.hidden, false, "changing document language must stale existing results");
  ui.stale.hidden = true;
  ui.format.value = "txt";
  ui.format.dispatch("change");
  assert.equal(ui.stale.hidden, false, "changing pasted format must stale existing results");

  ui.format.value = "tex";
  ui.format.dispatch("change");
  ui.file.files = [{ name: "source.txt", size: 7 }];
  ui.stale.hidden = true;
  ui.file.dispatch("change");
  assert.equal(ui.stale.hidden, false, "selecting an upload must stale existing results");
  assert.equal(ui.format.value, "txt");
  assert.equal(ui.format.disabled, true);
  assert.equal(ui.editorState.dataset.state, "ready", "a valid selected file takes precedence over an over-limit pasted draft");
  assert.equal(ui.removeFile.hidden, false);
  ui.removeFile.dispatch("click");
  assert.equal(ui.text.value, "draft", "removing an upload must preserve pasted text");
  assert.equal(ui.format.value, "tex", "removing an upload must restore the pasted format");
  assert.equal(ui.format.disabled, false);

  ui.file.files = [{ name: "source.tex", size: 7 }];
  ui.file.dispatch("change");
  ui.setConfirm(false);
  ui.clear.dispatch("click");
  assert.equal(ui.text.value, "draft", "canceling Clear must preserve text");
  assert.equal(ui.file.files.length, 1, "canceling Clear must preserve the selected file");
  ui.setConfirm(true);
  ui.clear.dispatch("click");
  assert.equal(ui.text.value, "");
  assert.equal(ui.file.files.length, 0);
  assert.equal(ui.format.value, "txt");
  assert.equal(ui.removeFile.hidden, true, "Clear must hide the now-empty file action");
  assert.equal(ui.removeFile.disabled, true, "Clear must disable the now-empty file action");
  assert.equal(ui.editorState.dataset.state, "empty");

  ui.text.value = "123456";
  ui.text.dispatch("input");
  const firstLimitNotice = ui.status.textContent;
  assert.match(firstLimitNotice, /limit has been exceeded/);
  ui.text.value = "1234567";
  ui.text.dispatch("input");
  assert.equal(ui.status.textContent, firstLimitNotice, "typing while over the limit must not announce on every keystroke");
  ui.text.value = "12345";
  ui.text.dispatch("input");
  assert.match(ui.status.textContent, /back within the limit/);

  ui.text.value = "keep this draft";
  ui.text.dispatch("input");
  ui.setConfirm(false);
  ui.example.dispatch("click");
  assert.equal(ui.text.value, "keep this draft", "canceling sample replacement must preserve text");
  ui.setConfirm(true);
  ui.example.dispatch("click");
  assert.equal(ui.text.value, "Exemple fictif.", "sample content should follow the selected document language");
  assert.match(ui.status.textContent, /Example loaded/);
  assert.equal(ui.removeFile.hidden, true, "loading a sample must hide the file action after clearing an upload");
}

function testSubmissionRestoreAndFilters() {
  const allFilterUi = boot("fr", ["writing", "source", "writing"]);
  assert.equal(allFilterUi.filterStatus.textContent, "3 pistes affichées.");

  const ui = boot("fr");
  ui.text.value = "bonjour";
  ui.text.dispatch("input");
  ui.text.value = "ok";
  ui.text.dispatch("input");
  const focusedBeforePageshow = ui.text.focused;
  const first = ui.form.dispatch("submit", { submitter: ui.reviseButton });
  assert.equal(first.prevented, false);
  assert.equal(ui.reviseButton.children.get(".button-label").textContent, "Préparation…");
  assert.equal(ui.reviseButton.children.get(".button-spinner").hidden, false);
  assert.equal(ui.reviseButton.children.get(".button-arrow").hidden, true);
  assert.equal(ui.auditButton.disabled, true);
  assert.equal(ui.editorState.dataset.state, "working");
  assert.equal(ui.form.getAttribute("aria-busy"), "true");
  assert.equal(ui.form.dispatch("submit", { submitter: ui.auditButton }).prevented, true, "duplicate submit must be canceled");

  ui.window.dispatch("pageshow", { persisted: true });
  assert.equal(ui.reviseButton.disabled, false);
  assert.equal(ui.reviseButton.children.get(".button-label").textContent, "Revise");
  assert.equal(ui.reviseButton.children.get(".button-spinner").hidden, true);
  assert.equal(ui.reviseButton.children.get(".button-arrow").hidden, false);
  assert.equal(ui.form.getAttribute("aria-busy"), null);
  assert.equal(ui.text.focused, focusedBeforePageshow, "pageshow must not steal focus");
  const unload = ui.window.dispatch("beforeunload");
  assert.equal(unload.returnValue, "", "a restored draft should remain protected from accidental loss");

  assert.equal(ui.filters.hidden, false);
  assert.equal(ui.allButton.getAttribute("aria-pressed"), "true");
  ui.sourceButton.dispatch("click");
  assert.equal(ui.cards[0].hidden, true);
  assert.equal(ui.cards[1].hidden, false);
  assert.match(ui.filterStatus.textContent, /Affichage de 1 des 2.*catégorie source/);
  ui.writingButton.dispatch("click");
  assert.equal(ui.cards[0].hidden, false);
  assert.equal(ui.cards[1].hidden, true);
  assert.equal(ui.sourceButton.getAttribute("aria-pressed"), "false");

  const englishUi = boot("en", [], "input");
  englishUi.text.value = "ok";
  englishUi.text.dispatch("input");
  englishUi.form.dispatch("submit", { submitter: englishUi.auditButton });
  assert.equal(englishUi.auditButton.children.get(".button-label").textContent, "Reviewing…");
  assert.equal(englishUi.status.textContent, "Reviewing…", "audit action should announce its localized loading label");

  const emptyUi = boot("en", ["source"]);
  emptyUi.writingButton.dispatch("click");
  assert.equal(emptyUi.filterEmpty.hidden, false);
  assert.equal(emptyUi.filterEmpty.textContent, "No findings in this category.");

  const unavailableSampleUi = boot("en", [], "input", { invalidExample: true });
  assert.equal(unavailableSampleUi.example.hidden, true, "an incomplete sample should not expose an empty action");
  assert.equal(unavailableSampleUi.sampleDisclosure.hidden, false, "an incomplete sample must retain the manual-copy fallback");

  const invalidUi = boot("en", [], "input");
  const emptySubmit = invalidUi.form.dispatch("submit", { submitter: invalidUi.auditButton });
  assert.equal(emptySubmit.prevented, true);
  assert.equal(invalidUi.editorState.dataset.state, "invalid");
  assert.equal(invalidUi.text.getAttribute("aria-invalid"), "true");

  const restoredUi = boot("en", [], "input");
  restoredUi.text.value = "restored draft";
  restoredUi.text.setAttribute("aria-invalid", "true");
  restoredUi.file.files = [{ name: "restored.tex", size: 10 }];
  restoredUi.file.setAttribute("aria-invalid", "true");
  restoredUi.fileError.hidden = false;
  restoredUi.window.dispatch("pageshow", { persisted: true });
  assert.equal(restoredUi.count.textContent, "14 / 5");
  assert.equal(restoredUi.fileError.hidden, false, "pageshow must not clear server-rendered file errors");
  assert.equal(restoredUi.text.getAttribute("aria-invalid"), "true", "pageshow must preserve an existing field error");
  assert.equal(restoredUi.removeFile.hidden, false, "pageshow must re-sync a browser-restored file selection");
  assert.equal(restoredUi.format.disabled, true);
  assert.equal(restoredUi.format.value, "tex");

  const minimalUi = boot("en", [], "input", { includeHelpers: false });
  assert.equal(minimalUi.sampleDisclosure.hidden, false, "the manual-copy fallback remains available without its button hook");
  minimalUi.text.value = "ok";
  minimalUi.text.dispatch("input");
  const minimalSubmit = minimalUi.form.dispatch("submit", { submitter: minimalUi.auditButton });
  assert.equal(minimalSubmit.prevented, false, "validation and submit must work when optional Clear/Sample hooks are absent");
  assert.equal(minimalUi.auditButton.children.get(".button-label").textContent, "Reviewing…");

  const defaultFileLimitUi = boot("en", [], "input");
  defaultFileLimitUi.file.files = [{ name: "large.txt", size: 1000001 }];
  defaultFileLimitUi.file.dispatch("change");
  assert.equal(defaultFileLimitUi.file.getAttribute("aria-invalid"), "true");
  assert.match(defaultFileLimitUi.fileError.textContent, /1\.0 MB/);
}

testStateAndDraftControls();
testSubmissionRestoreAndFilters();
console.log("app state regressions passed");
