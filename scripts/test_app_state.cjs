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

    removeEventListener(type, callback) {
      this.listeners.set(type, (this.listeners.get(type) || []).filter((listener) => listener !== callback));
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
    if (selector === "textarea, input[type='file'], select, button[type='button']") return this.controls || [];
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

function makeResponseDocument({ locale = "en", mode = "audit", text = "server result draft", error = false, unsafe = false, unsafeAttributes = false, unsafeStyleElement = false, unsafeStyleAttribute = false, unsafeSvgHref = false, safeSvgFragment = false, unsafeFormAction = false, replaceBody }) {
  const elements = new Map();
  const add = (id, element = new FakeElement(id)) => { elements.set(id, element); return element; };
  const form = add("report-form");
  form.action = "/audit";
  form.method = "post";
  form.dataset.maxChars = "5";
  form.controls = [];
  const responseAuditButton = new FakeButton("Review", "button");
  responseAuditButton.formAction = "/audit";
  const responseReviseButton = new FakeButton("Revise", "button");
  responseReviseButton.formAction = unsafeFormAction ? "https://other.test/revise" : "/revise";
  form.submitButtons = [responseAuditButton, responseReviseButton];
  const csrf = add("csrf-token", new FakeElement("csrf-token", "input"));
  form.selectors.set('input[name="csrf_token"]', csrf);
  const textField = add("report-text", new FakeElement("report-text", "textarea"));
  textField.value = text;
  const language = add("content-language", new FakeElement("content-language", "select"));
  language.value = locale;
  const file = add("report-file", new FakeElement("report-file", "input"));
  const format = add("source-format", new FakeElement("source-format", "select"));
  format.value = "txt";
  const count = add("character-count");
  const status = add("submission-status");
  const dropZone = add("drop-zone");
  const page = add("page-content");
  page.dataset.mode = mode;
  form.controls = [textField, file, language, format];
  const main = add("main-content", new FakeElement("main-content", "main"));
  const alert = error ? new FakeElement("form-alert") : null;
  const body = new FakeElement("body", "body");
  const html = new FakeElement("html", "html");
  html.lang = locale;
  const queries = new Map([
    [".page-content", page],
    ["[data-dropzone]", dropZone],
    [".form-alert", alert],
    [".results-scroll", null],
    [".results-heading-row .status-pill", null],
  ]);
  body.responseElements = elements;
  body.responseQueries = queries;
  body.responseLang = locale;
  body.selectors.set("#report-file", file);
  body.replaceWith = replaceBody;
  let dangerousNode = null;
  let unsafeAttributeNode = null;
  let styleNode = null;
  let svgResourceNode = null;
  let safeSvgNode = null;
  if (unsafe || unsafeAttributes || unsafeStyleElement || unsafeStyleAttribute || unsafeSvgHref || safeSvgFragment) {
    if (unsafe) {
      dangerousNode = new FakeElement("unexpected-script", "script");
      dangerousNode.wasRemoved = false;
      dangerousNode.remove = () => { dangerousNode.wasRemoved = true; };
    }
    if (unsafeStyleElement) styleNode = new FakeElement("unexpected-style", "style");
    if (unsafeAttributes) {
      unsafeAttributeNode = {
        attributes: [
          { name: "onclick", value: "alert(1)" },
          { name: "href", value: "javascript:alert(1)" },
          { name: "src", value: "https://other.test/asset" },
        ],
        removedAttributes: [],
        removeAttribute(name) { this.removedAttributes.push(name); },
      };
    }
    if (unsafeStyleAttribute) {
      unsafeAttributeNode = {
        attributes: [{ name: "style", value: "background-image:url(https://other.test/track)" }],
        removedAttributes: [],
        removeAttribute(name) { this.removedAttributes.push(name); },
      };
    }
    if (unsafeSvgHref || safeSvgFragment) {
      const svgNode = {
        localName: unsafeSvgHref ? "image" : "use",
        namespaceURI: "http://www.w3.org/2000/svg",
        attributes: [{ name: "href", value: unsafeSvgHref ? "https://other.test/sprite.svg#icon" : "#icon" }],
      };
      if (unsafeSvgHref) svgResourceNode = svgNode;
      else safeSvgNode = svgNode;
    }
    body.selectorLists = new Map([
      ["script, iframe, object, embed, audio, video, source, track, img, base, link, style, meta[http-equiv]", [dangerousNode, styleNode].filter(Boolean)],
      ["*", [unsafeAttributeNode, svgResourceNode, safeSvgNode].filter(Boolean)],
    ]);
  }
  return {
    body,
    documentElement: html,
    title: "Synthetic response",
    unsafeNodes: { dangerousNode, unsafeAttributeNode, styleNode, svgResourceNode },
    getElementById: (id) => elements.get(id) || null,
    querySelector: (selector) => queries.get(selector) || null,
    querySelectorAll: () => [],
  };
}

function fakeHtmlResponse({ status = 200, ok = status < 400, url = "https://rapport.test/audit", redirect = false } = {}) {
  return {
    status,
    ok,
    url,
    redirected: redirect,
    headers: { get: (name) => (name.toLowerCase() === "content-type" ? "text/html; charset=utf-8" : "100") },
    text: async () => "<synthetic server response>",
  };
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

function boot({ locale = "en", optionalFormHelpers = true, fileControls = true, results = false, downloads = false, initialText = "", formError = false, enhanced = false, fetchHandler = null } = {}) {
  const elements = new Map();
  const add = (id, element = new FakeElement(id)) => { elements.set(id, element); return element; };
  const form = add("report-form");
  form.dataset.maxChars = "5";
  form.action = "/audit";
  const text = add("report-text");
  text.value = initialText;
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
  form.controls = [text, file, language, format, clear, example, removeFile].filter(Boolean);
  const fileError = add("file-error");
  fileError.hidden = true;
  const textError = add("text-error");
  textError.hidden = true;
  const status = add("submission-status");
  const page = add("page-content");
  page.dataset.mode = "input";
  const dropZone = add("drop-zone");
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
  const formAlert = formError ? add("form-alert") : null;

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
    ["[data-dropzone]", dropZone],
    [".form-alert", formAlert],
    [".results-scroll", resultsScroll],
    [".results-heading-row .status-pill", statusPill],
    ["[data-export-notes]", downloads ? exportButton : null],
    [".source-name", downloads ? sourceHeading : null],
    ['[data-download-source="cleaned"]', downloads ? cleanedSource : null],
  ]);
  const documentListeners = new Map();
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
    importNode: (node) => node,
    addEventListener(type, callback) {
      const listeners = documentListeners.get(type) || [];
      listeners.push(callback);
      documentListeners.set(type, listeners);
    },
    removeEventListener(type, callback) {
      documentListeners.set(type, (documentListeners.get(type) || []).filter((listener) => listener !== callback));
    },
    title: "Synthetic home",
  };
  const replaceBody = (newBody) => {
    document.body = newBody;
    elements.clear();
    newBody.responseElements?.forEach((element, id) => elements.set(id, element));
    queryOne.clear();
    newBody.responseQueries?.forEach((element, selector) => queryOne.set(selector, element));
    document.documentElement.lang = newBody.responseLang || "en";
  };
  body.replaceWith = replaceBody;

  let nextConfirm = true;
  let nextTimer = 0;
  const windowTimers = new Map();
  const windowListeners = new Map();
  const window = {
    isSecureContext: false,
    location: { href: "https://rapport.test/" },
    confirm: () => nextConfirm,
    setTimeout(callback, delay = 0) {
      const id = ++nextTimer;
      windowTimers.set(id, { callback, delay });
      return id;
    },
    clearTimeout(id) { windowTimers.delete(id); },
    requestAnimationFrame: () => ++nextTimer,
    cancelAnimationFrame() {},
    addEventListener(type, callback) {
      const listeners = windowListeners.get(type) || [];
      listeners.push(callback);
      windowListeners.set(type, listeners);
    },
    removeEventListener(type, callback) {
      windowListeners.set(type, (windowListeners.get(type) || []).filter((listener) => listener !== callback));
    },
    dispatch(type, detail = {}) {
      let prevented = false;
      const event = { type, preventDefault() { prevented = true; }, ...detail };
      for (const callback of windowListeners.get(type) || []) callback(event);
      return { event, prevented };
    },
    runTimers(maxDelay = Infinity) {
      for (const [id, timer] of [...windowTimers]) {
        if (timer.delay > maxDelay) continue;
        windowTimers.delete(id);
        timer.callback();
      }
    },
  };
  const fetchCalls = [];
  class FakeFormData {
    constructor(formElement) { this.form = formElement; this.fields = []; }
    append(name, value) { this.fields.push([name, value]); }
  }
  let responsePage = makeResponseDocument({
    locale,
    mode: "audit",
    text: "Reviewed draft.",
    replaceBody,
  });
  class FakeDOMParser {
    parseFromString() { return responsePage; }
  }
  const fetchMock = async (url, options) => {
    fetchCalls.push({ url, options });
    if (!fetchHandler) throw new Error("unexpected fetch");
    return fetchHandler(url, options);
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
    URL: enhanced ? global.URL : URL,
    fetch: enhanced ? fetchMock : undefined,
    FormData: enhanced ? FakeFormData : undefined,
    DOMParser: enhanced ? FakeDOMParser : undefined,
    AbortController: enhanced ? AbortController : undefined,
    TextEncoder,
    TextDecoder,
    Blob: class Blob {},
    console,
  }, { filename: "app.js" });
  window.dispatch("pageshow", { persisted: false });
  return {
    elements, form, text, language, file, format, count, clear, example, copySample, fileChip, fileName, removeFile,
    fileError, textError, status, auditButton, reviseButton, page, body, documentElement, document, window, downloaded,
    resultsScroll, sourceHeading, exportButton, downloadButton, windowListeners, documentListeners,
    fetchCalls,
    setResponseFactory(factory) { responsePage = factory(); },
    setResponsePage(options) { responsePage = makeResponseDocument({ ...options, replaceBody }); return responsePage; },
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

function testServerRenderedDraftIsCleanUntilEdited() {
  const ui = boot({ results: true, initialText: "Previously analyzed draft." });
  assert.equal(ui.window.dispatch("beforeunload").prevented, false, "server-rendered analysis text is the clean page baseline");

  ui.text.value = "Previously analyzed draft with a new edit.";
  ui.text.dispatch("input");
  assert.equal(ui.window.dispatch("beforeunload").prevented, true, "a change from the server-rendered baseline warns before navigation");

  ui.text.value = "Previously analyzed draft.";
  ui.text.dispatch("input");
  assert.equal(ui.window.dispatch("beforeunload").prevented, false, "restoring the original server-rendered text clears the warning");

  ui.window.dispatch("pageshow", { persisted: true });
  assert.equal(ui.window.dispatch("beforeunload").prevented, false, "BFCache restoration keeps the analyzed text clean");

  ui.text.value = "";
  ui.text.dispatch("input");
  assert.equal(ui.window.dispatch("beforeunload").prevented, true, "clearing a server-rendered draft is still an unsaved change");

  const errorUi = boot({ initialText: "Retained after validation error.", formError: true });
  assert.equal(errorUi.window.dispatch("beforeunload").prevented, true, "a draft retained on a server validation page is not treated as a clean result baseline");
}

function testOriginalSourceNamesDriveDownloadNames() {
  const ui = boot({ downloads: true });
  ui.downloadButton.click();
  assert.equal(ui.downloaded.at(-1).download, "Student Draft-Final_cleaned.txt");
  assert.equal(ui.downloaded.at(-1).clicked, true);
  ui.exportButton.click();
  assert.equal(ui.downloaded.at(-1).download, "Student Draft-Final_review_notes.md", "localized display names must not replace the original source filename");
}

async function testEnhancedSuccessKeepsGetUrlAndReinitializesOnePage() {
  const ui = boot({
    enhanced: true,
    initialText: "Draft",
    fetchHandler: async () => fakeHtmlResponse(),
  });
  ui.setResponsePage({ locale: "fr", mode: "audit", text: "Reviewed draft." });
  ui.auditButton.formAction = "/audit";
  const submitted = ui.form.dispatch("submit", { submitter: ui.auditButton });
  assert.equal(submitted.prevented, true, "enhanced submission prevents POST navigation");
  assert.equal(ui.fetchCalls.length, 1);
  assert.equal(ui.fetchCalls[0].url, "https://rapport.test/audit");
  assert.equal(ui.fetchCalls[0].options.method, "POST");
  assert.equal(ui.fetchCalls[0].options.credentials, "same-origin");
  assert.equal(ui.fetchCalls[0].options.mode, "same-origin");
  assert.equal(ui.fetchCalls[0].options.redirect, "error");
  assert.equal(ui.fetchCalls[0].options.cache, "no-store");
  assert.equal(ui.text.disabled, true, "form controls are locked only while the request is in flight");

  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ui.window.location.href, "https://rapport.test/", "the browser remains on the GET document URL");
  assert.equal(ui.document.title, "Synthetic response");
  assert.equal(ui.document.documentElement.lang, "fr");
  assert.equal(ui.document.body.dataset.enhancedResult, "true");
  assert.equal(ui.elements.get("report-text").value, "Reviewed draft.");
  assert.equal(ui.windowListeners.get("pageshow").length, 1, "the old page's global listeners are disposed before reinitializing");
  assert.equal(ui.documentListeners.get("keydown").length, 1, "document shortcuts do not accumulate after a response swap");
  assert.equal(ui.window.dispatch("beforeunload").prevented, false, "a successful rendered result is the clean baseline");
}

async function testEnhancedNetworkFailureKeepsDraftAndNeverRetries() {
  const ui = boot({
    enhanced: true,
    initialText: "Draft",
    fetchHandler: async () => { throw new Error("synthetic network failure"); },
  });
  ui.file.files = [{ name: "chapter.tex", size: 64 }];
  ui.file.dispatch("change");
  const submitted = ui.form.dispatch("submit", { submitter: ui.auditButton });
  assert.equal(submitted.prevented, true);
  assert.equal(ui.fetchCalls.length, 1);
  assert.equal(ui.text.disabled, true);
  assert.equal(ui.file.disabled, true);
  assert.equal(ui.example.disabled, true, "other form actions are locked during a request");
  const dropped = ui.form.dispatch("drop", {
    dataTransfer: { types: ["Files"], files: [{ name: "replacement.txt", size: 16 }] },
  });
  assert.equal(dropped.prevented, true, "drop navigation remains blocked during a request");
  assert.equal(ui.file.files[0].name, "chapter.tex", "a drop cannot replace the submitted file while the request is in flight");

  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ui.fetchCalls.length, 1, "a failed fetch must never trigger a duplicate native POST");
  assert.equal(ui.elements.get("report-text").value, "Draft");
  assert.equal(ui.file.files[0].name, "chapter.tex");
  assert.equal(ui.text.disabled, false);
  assert.equal(ui.file.disabled, false);
  assert.equal(ui.example.disabled, false);
  assert.equal(ui.auditButton.disabled, false);
  assert.equal(ui.body.children.some((child) => child.classList.contains("top-progress")), false);
  assert.equal(ui.status.getAttribute("role"), "alert");
  ui.window.runTimers(30);
  assert.match(ui.status.textContent, /still here/);
  assert.equal(ui.window.dispatch("beforeunload").prevented, true, "the retained draft remains protected after failure");
}

async function testEnhancedServerErrorKeepsTextAndSelectedFileDirty() {
  const ui = boot({
    enhanced: true,
    initialText: "Draft",
    fetchHandler: async () => fakeHtmlResponse({ status: 413, ok: false }),
  });
  ui.setResponsePage({ locale: "en", mode: "input", text: "server omitted file", error: true });
  ui.file.files = [{ name: "chapter.tex", size: 64 }];
  ui.file.dispatch("change");
  ui.form.dispatch("submit", { submitter: ui.auditButton });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(ui.fetchCalls.length, 1);
  assert.equal(ui.document.body.dataset.enhancedResult, "false");
  assert.equal(ui.elements.get("report-text").value, "Draft");
  assert.equal(ui.elements.get("report-file").files[0].name, "chapter.tex", "a server error keeps the selected file when FileList transfer is available");
  assert.equal(ui.document.querySelector(".form-alert") !== null, true);
  assert.equal(ui.window.dispatch("beforeunload").prevented, true, "server error submissions remain dirty rather than becoming a clean baseline");
}

async function testEnhancedUnexpected500DoesNotReplaceOrRetry() {
  const ui = boot({
    enhanced: true,
    initialText: "Draft",
    fetchHandler: async () => fakeHtmlResponse({ status: 500, ok: false }),
  });
  ui.setResponsePage({ locale: "en", mode: "input", text: "server error" });
  const originalBody = ui.document.body;
  ui.form.dispatch("submit", { submitter: ui.auditButton });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ui.fetchCalls.length, 1, "an unexpected 500 is not retried automatically");
  assert.equal(ui.document.body, originalBody, "unexpected server pages leave the current form in place");
  assert.equal(ui.text.value, "Draft");
  assert.equal(ui.text.disabled, false);
}

async function testEnhancedRejectsCrossOriginResponse() {
  const ui = boot({
    enhanced: true,
    initialText: "Draft",
    fetchHandler: async () => fakeHtmlResponse({ url: "https://other.test/audit" }),
  });
  const originalBody = ui.document.body;
  ui.form.dispatch("submit", { submitter: ui.auditButton });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ui.fetchCalls.length, 1);
  assert.equal(ui.document.body, originalBody, "a response from another origin is never adopted");
  assert.equal(ui.text.value, "Draft");
  assert.equal(ui.auditButton.disabled, false);
}

async function testEnhancedRejectsActiveResponseMarkup() {
  for (const unsafe of [
    { unsafe: true },
    { unsafeAttributes: true },
    { unsafeStyleElement: true },
    { unsafeStyleAttribute: true },
    { unsafeSvgHref: true },
    { unsafeFormAction: true },
  ]) {
    const ui = boot({
      enhanced: true,
      initialText: "Draft",
      fetchHandler: async () => fakeHtmlResponse(),
    });
    const parsed = ui.setResponsePage({ locale: "en", mode: "audit", text: "unsafe result", ...unsafe });
    const originalBody = ui.document.body;
    ui.form.dispatch("submit", { submitter: ui.auditButton });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(ui.document.body, originalBody, "active returned markup is rejected before adoption");
    if (parsed.unsafeNodes.dangerousNode) assert.equal(parsed.unsafeNodes.dangerousNode.wasRemoved, false, "the response is rejected rather than silently modified");
    if (parsed.unsafeNodes.unsafeAttributeNode) assert.deepEqual(parsed.unsafeNodes.unsafeAttributeNode.removedAttributes, []);
    assert.equal(ui.text.value, "Draft");
  }
}

async function testEnhancedAllowsFragmentSvgReferences() {
  const ui = boot({
    enhanced: true,
    initialText: "Draft",
    fetchHandler: async () => fakeHtmlResponse(),
  });
  const parsed = ui.setResponsePage({ locale: "en", mode: "audit", text: "safe result", safeSvgFragment: true });
  ui.form.dispatch("submit", { submitter: ui.auditButton });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ui.document.body, parsed.body, "same-document SVG fragment references remain valid");
}

async function testEnhancedRequestHasBoundedAbortTimeout() {
  let abortObserved = false;
  const ui = boot({
    enhanced: true,
    initialText: "Draft",
    fetchHandler: async (_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => {
        abortObserved = true;
        reject(new Error("synthetic timeout"));
      }, { once: true });
    }),
  });
  ui.form.dispatch("submit", { submitter: ui.auditButton });
  assert.equal(ui.fetchCalls.length, 1);
  ui.window.runTimers(20000);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(abortObserved, true, "the request controller aborts at the bounded timeout");
  assert.equal(ui.text.disabled, false, "the timeout restores form controls");
  assert.equal(ui.auditButton.disabled, false);
  assert.equal(ui.window.dispatch("beforeunload").prevented, false, "the clean baseline remains clean after timeout");
}

async function testStaleRequestCannotResetNewSubmission() {
  let resolveFirst;
  let resolveSecond;
  const ui = boot({
    enhanced: true,
    initialText: "Draft",
    fetchHandler: () => new Promise((resolve, reject) => {
      if (ui.fetchCalls.length === 1) resolveFirst = resolve;
      else resolveSecond = resolve;
    }),
  });
  ui.setResponsePage({ locale: "en", mode: "audit", text: "Latest result." });
  const first = ui.form.dispatch("submit", { submitter: ui.auditButton });
  assert.equal(first.prevented, true);
  assert.equal(ui.fetchCalls.length, 1);

  ui.window.dispatch("pageshow", { persisted: true });
  ui.form.dispatch("submit", { submitter: ui.reviseButton });
  assert.equal(ui.fetchCalls.length, 2);
  assert.equal(ui.text.disabled, true, "the second request owns the disabled controls");
  assert.equal(ui.reviseButton.disabled, true);

  resolveFirst(fakeHtmlResponse());
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ui.text.disabled, true, "a late first response cannot restore controls owned by the second request");
  assert.equal(ui.reviseButton.disabled, true);
  assert.equal(ui.document.body.dataset.enhancedResult, undefined, "a stale result cannot replace the active page");

  resolveSecond(fakeHtmlResponse());
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ui.document.body.dataset.enhancedResult, "true", "the active response still replaces the page normally");
  assert.equal(ui.elements.get("report-text").value, "Latest result.");
}

async function run() {
  testFileEnhancementAndUndo();
  testOptionalHooksSubmissionAndBfcache();
  testServerRenderedDraftIsCleanUntilEdited();
  testOriginalSourceNamesDriveDownloadNames();
  await testEnhancedSuccessKeepsGetUrlAndReinitializesOnePage();
  await testEnhancedNetworkFailureKeepsDraftAndNeverRetries();
  await testEnhancedServerErrorKeepsTextAndSelectedFileDirty();
  await testEnhancedUnexpected500DoesNotReplaceOrRetry();
  await testEnhancedRejectsCrossOriginResponse();
  await testEnhancedRejectsActiveResponseMarkup();
  await testEnhancedAllowsFragmentSvgReferences();
  await testEnhancedRequestHasBoundedAbortTimeout();
  await testStaleRequestCannotResetNewSubmission();
  console.log("app state regressions passed");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
