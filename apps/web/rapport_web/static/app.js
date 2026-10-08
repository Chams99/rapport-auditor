(() => {
  "use strict";

  let disposeCurrentPage = () => {};

  const initializePage = ({ forceDirty = false } = {}) => {
    disposeCurrentPage();
    const globalCleanups = [];
    const timers = new Set();
    const animationFrames = new Set();
    const observers = new Set();
    const objectUrls = new Set();
    let activeRequest = null;
    let activeRequestTimeout = 0;

    const listenGlobally = (target, type, callback, options) => {
      target.addEventListener(type, callback, options);
      globalCleanups.push(() => target.removeEventListener(type, callback, options));
    };
    const setPageTimeout = (callback, delay) => {
      let id = 0;
      id = window.setTimeout(() => {
        timers.delete(id);
        callback();
      }, delay);
      timers.add(id);
      return id;
    };
    const clearPageTimeout = (id) => {
      window.clearTimeout(id);
      timers.delete(id);
    };
    const requestPageFrame = (callback) => {
      let id = 0;
      id = window.requestAnimationFrame((time) => {
        animationFrames.delete(id);
        callback(time);
      });
      animationFrames.add(id);
      return id;
    };
    const createPageObjectUrl = (blob) => {
      const url = URL.createObjectURL(blob);
      objectUrls.add(url);
      return url;
    };
    const revokePageObjectUrl = (url) => {
      URL.revokeObjectURL(url);
      objectUrls.delete(url);
    };

    disposeCurrentPage = () => {
      activeRequest?.abort();
      activeRequest = null;
      if (activeRequestTimeout) clearPageTimeout(activeRequestTimeout);
      activeRequestTimeout = 0;
      globalCleanups.splice(0).forEach((cleanup) => cleanup());
      timers.forEach((id) => window.clearTimeout(id));
      timers.clear();
      animationFrames.forEach((id) => window.cancelAnimationFrame(id));
      animationFrames.clear();
      observers.forEach((observer) => observer.disconnect());
      observers.clear();
      objectUrls.forEach((url) => URL.revokeObjectURL(url));
      objectUrls.clear();
    };

    const run = () => {

  const page = document.querySelector(".page-content");
  const form = document.getElementById("report-form");
  const textField = document.getElementById("report-text");
  const contentLanguageField = document.getElementById("content-language");
  const fileField = document.getElementById("report-file");
  const formatField = document.getElementById("source-format");
  const countLabel = document.getElementById("character-count");
  const clearButton = document.getElementById("clear-text");
  const exampleButton = document.getElementById("load-example");
  const copySampleDisclosure = document.getElementById("copy-sample");
  const fileChip = document.getElementById("file-chip");
  const fileNameLabel = document.getElementById("file-name");
  const removeFileButton = document.getElementById("remove-file");
  const dropZone = document.querySelector("[data-dropzone]");
  const fileError = document.getElementById("file-error");
  const textError = document.getElementById("text-error");
  const statusLabel = document.getElementById("submission-status");
  const locale = document.documentElement.lang === "fr" ? "fr" : "en";
  const isFr = locale === "fr";
  const numberFormat = new Intl.NumberFormat(locale);
  const maxChars = Number(form?.dataset.maxChars || 250000);
  const maxFileBytes = Number(form?.dataset.maxFileBytes || 1000000);
  const fileSizeFormat = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

  const messages = {
    empty: isFr ? "Ajoutez du texte ou choisissez un fichier avant de continuer." : "Add some text or choose a file before continuing.",
    textSize: isFr ? `Le texte dépasse la limite de ${numberFormat.format(maxChars)} caractères. Divisez-le en sections et réessayez.` : `Text exceeds the ${numberFormat.format(maxChars)}-character limit. Split it into sections and try again.`,
    fileType: isFr ? "Choisissez un fichier .txt ou .tex encodé en UTF-8." : "Choose a UTF-8 .txt or .tex file.",
    fileSize: isFr ? `Ce fichier dépasse la limite de ${fileSizeFormat.format(maxFileBytes / 1000000)} Mo.` : `This file is larger than the ${fileSizeFormat.format(maxFileBytes / 1000000)} MB limit.`,
    loadedExample: isFr ? "Exemple chargé. Vous pouvez le modifier avant la revue." : "Example loaded. Edit it before starting your review.",
    fileRemoved: isFr ? "Fichier retiré." : "File removed.",
    oneFile: isFr ? "Déposez un seul fichier à la fois." : "Drop one file at a time.",
    copied: isFr ? "Suggestion copiée." : "Suggestion copied.",
    copyFailed: isFr ? "La copie a échoué ; sélectionnez le texte manuellement." : "Copy failed; select the text manually.",
    showLine: (line) => (isFr ? `Afficher la ligne ${line} dans l’éditeur` : `Show line ${line} in the editor`),
    lineSelected: (line) => (isFr ? `Ligne ${line} sélectionnée dans l’éditeur.` : `Line ${line} selected in the editor.`),
    filtered: (count) => (isFr ? `${count} pistes affichées.` : `${count} prompts shown.`),
    words: (count) => (isFr ? `${numberFormat.format(count)} mots` : `${numberFormat.format(count)} ${count === 1 ? "word" : "words"}`),
    overLimit: isFr ? "Le texte dépasse la limite de caractères." : "The text is over the character limit.",
    cleared: isFr ? "Saisie effacée. Utilisez « Annuler » pour la restaurer." : "Input cleared. Use Undo to restore it.",
    restored: isFr ? "Saisie restaurée." : "Input restored.",
    undo: isFr ? "Annuler" : "Undo",
    reviewed: (done, total) => (isFr ? `${done} sur ${total} pistes examinées` : `${done} of ${total} prompts reviewed`),
    markReviewed: isFr ? "Marquer comme examinée" : "Mark as reviewed",
    isReviewed: isFr ? "Examinée" : "Reviewed",
    clearedShort: isFr ? "Saisie effacée" : "Draft cleared",
    fileAdded: (name) => (isFr ? `Fichier ajouté : ${name}` : `File added: ${name}`),
    exported: isFr ? "Notes exportées" : "Review notes exported",
    submitFailed: isFr
      ? "Le résultat n’a pas pu être chargé. Votre texte et votre fichier sont toujours ici ; vérifiez la connexion avant de réessayer."
      : "The result could not be loaded. Your text and file are still here; check the connection before retrying.",
    reducedMotion: matchMedia("(prefers-reduced-motion: reduce)"),
  };

  const announce = (message) => {
    if (!statusLabel) return;
    statusLabel.textContent = "";
    setPageTimeout(() => { statusLabel.textContent = message; }, 30);
  };

  // Short-lived confirmations with an optional action (Undo). The region is a
  // polite live region, so screen readers hear the same message.
  const toastRegion = document.getElementById("toast-region");
  const toast = (message, { action, onAction, duration = 4000 } = {}) => {
    if (!toastRegion) { announce(message); return; }
    const item = document.createElement("div");
    item.className = "toast";
    const text = document.createElement("span");
    text.textContent = message;
    item.append(text);
    let timer = 0;
    const dismiss = () => {
      clearPageTimeout(timer);
      item.classList.add("is-leaving");
      setPageTimeout(() => item.remove(), 200);
    };
    if (action && onAction) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "toast-action";
      button.textContent = action;
      button.addEventListener("click", () => { onAction(); dismiss(); });
      item.append(button);
    }
    toastRegion.append(item);
    timer = setPageTimeout(dismiss, duration);
    item.addEventListener("mouseenter", () => clearPageTimeout(timer));
    item.addEventListener("mouseleave", () => { timer = setPageTimeout(dismiss, 1500); });
  };

  // Theme: system → light → dark, remembered on this device only.
  const themeToggle = document.querySelector("[data-theme-toggle]");
  if (themeToggle) {
    const root = document.documentElement;
    const modes = ["system", "light", "dark"];
    const apply = (mode) => {
      if (mode === "system") delete root.dataset.theme;
      else root.dataset.theme = mode;
      themeToggle.dataset.mode = mode;
      themeToggle.setAttribute("aria-label", themeToggle.dataset[`label${mode[0].toUpperCase()}${mode.slice(1)}`] || mode);
      themeToggle.title = themeToggle.getAttribute("aria-label");
    };
    apply(root.dataset.theme || "system");
    themeToggle.hidden = false;
    themeToggle.addEventListener("click", () => {
      const next = modes[(modes.indexOf(themeToggle.dataset.mode) + 1) % modes.length];
      apply(next);
      try {
        if (next === "system") localStorage.removeItem("ra-theme");
        else localStorage.setItem("ra-theme", next);
      } catch {
        // Not remembered when storage is unavailable; the choice still applies now.
      }
    });
  }

  // Hints that only make sense with this script running.
  document.querySelectorAll(".js-only").forEach((element) => { element.hidden = false; });
  if (isMac) document.querySelectorAll("[data-mod-key]").forEach((key) => { key.textContent = "⌘"; });

  if (form && textField && countLabel) {
    const refreshNote = document.querySelector("[data-refresh-note]");
    if (refreshNote && document.body.dataset.enhancedResult === "true") refreshNote.hidden = false;
    const hasCompleteSample = Boolean(
      exampleButton?.dataset.sampleEn?.trim() && exampleButton?.dataset.sampleFr?.trim(),
    );
    if (exampleButton && hasCompleteSample) {
      exampleButton.hidden = false;
      if (copySampleDisclosure) copySampleDisclosure.hidden = true;
    }
    if (clearButton) clearButton.hidden = false;

    const selectedFile = () => fileField?.files?.[0] || null;

    const wordLabel = document.getElementById("word-count");
    let wasOverLimit = false;
    const updateCounter = ({ announceLimit = true } = {}) => {
      const currentLength = Array.from(textField.value).length;
      const isOverLimit = !selectedFile() && currentLength > maxChars;
      countLabel.textContent = `${numberFormat.format(currentLength)} / ${numberFormat.format(maxChars)}`;
      countLabel.classList.toggle("is-over-limit", isOverLimit);
      if (wordLabel) wordLabel.textContent = messages.words(textField.value.split(/\s+/).filter(Boolean).length);
      // Announce only on crossing the limit, not on every keystroke (GOV.UK character count).
      if (announceLimit && isOverLimit && !wasOverLimit) announce(messages.overLimit);
      wasOverLimit = isOverLimit;
      if (!undoState && clearButton) clearButton.disabled = textField.value.length === 0 && !selectedFile();
    };
    let undoState = null;

    const setFieldError = (field, label, message) => {
      if (!field || !label) return;
      label.textContent = message || "";
      label.hidden = !message;
      field.setAttribute("aria-invalid", message ? "true" : "false");
    };

    const clearErrors = () => {
      setFieldError(textField, textError, "");
      setFieldError(fileField, fileError, "");
      if (statusLabel?.getAttribute("role") === "alert") {
        statusLabel.setAttribute("role", "status");
        statusLabel.setAttribute("aria-live", "polite");
        statusLabel.classList.add("visually-hidden");
        statusLabel.textContent = "";
      }
    };

    let pastedFormat = formatField?.value || "txt";
    // Successful audit/revision text is the clean baseline. A server-rendered
    // validation response with retained input remains an unsaved draft.
    const retainedErrorDraft = Boolean(document.querySelector(".form-alert"))
      && Boolean(textField.value || selectedFile());
    const dirtyBaseline = forceDirty || retainedErrorDraft;
    const initialDraftText = dirtyBaseline ? "" : textField.value;
    const initialDraftFile = dirtyBaseline ? null : selectedFile();
    let hasUnsavedDraft = false;
    const updateUnsavedDraft = () => {
      hasUnsavedDraft = textField.value !== initialDraftText || selectedFile() !== initialDraftFile;
      syncBeforeUnload();
    };

    formatField?.addEventListener("change", () => {
      if (!selectedFile()) pastedFormat = formatField.value;
    });

    const updateFile = ({ preserveErrors = false, announceLimit = true } = {}) => {
      const file = selectedFile();
      if (fileNameLabel) fileNameLabel.textContent = file ? file.name : "";
      if (fileChip) fileChip.hidden = !file;
      if (removeFileButton) {
        removeFileButton.hidden = !file;
        removeFileButton.disabled = !file;
      }
      if (!preserveErrors) setFieldError(fileField, fileError, "");

      if (file && !/\.(?:txt|tex)$/i.test(file.name)) {
        setFieldError(fileField, fileError, messages.fileType);
      } else if (file && file.size > maxFileBytes) {
        setFieldError(fileField, fileError, messages.fileSize);
      }

      if (file && formatField) {
        formatField.value = file.name.toLowerCase().endsWith(".tex") ? "tex" : "txt";
        formatField.disabled = true;
      } else if (!file && formatField) {
        formatField.value = pastedFormat;
        formatField.disabled = false;
      }
      updateUnsavedDraft();
      updateCounter({ announceLimit });
    };

    const resetFile = () => {
      if (fileField) fileField.value = "";
      updateFile();
    };

    const snapshotFiles = () => {
      const files = fileField?.files;
      if (!files?.length) return null;
      const copies = Array.from(files);
      if (typeof DataTransfer !== "function") return copies;
      const transfer = new DataTransfer();
      copies.forEach((file) => transfer.items.add(file));
      return transfer.files;
    };

    const restoreFiles = (files) => {
      if (!fileField || !files?.length || typeof DataTransfer !== "function") return;
      const transfer = new DataTransfer();
      Array.from(files).forEach((file) => transfer.items.add(file));
      fileField.files = transfer.files;
    };

    textField.addEventListener("input", () => {
      setFieldError(textField, textError, "");
      updateUnsavedDraft();
      updateCounter();
    });

    fileField?.addEventListener("change", () => {
      updateFile();
      const file = selectedFile();
      if (file && fileError?.hidden) toast(messages.fileAdded(file.name));
    });

    removeFileButton?.addEventListener("click", () => {
      resetFile();
      announce(messages.fileRemoved);
      fileField?.focus();
    });

    // Drag and drop is an enhancement over the native picker, which stays the
    // keyboard and no-JavaScript path.
    if (dropZone && fileField && typeof DataTransfer === "function") {
      const hasFiles = (event) => Array.from(event.dataTransfer?.types || []).includes("Files");
      let dragDepth = 0;

      form.addEventListener("dragenter", (event) => {
        if (!hasFiles(event)) return;
        if (isSubmitting) { event.preventDefault(); return; }
        event.preventDefault();
        dragDepth += 1;
        dropZone.classList.add("is-dragover");
      });
      form.addEventListener("dragover", (event) => {
        if (!hasFiles(event)) return;
        if (isSubmitting) { event.preventDefault(); return; }
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      });
      form.addEventListener("dragleave", (event) => {
        if (!hasFiles(event)) return;
        dragDepth = Math.max(0, dragDepth - 1);
        if (dragDepth === 0) dropZone.classList.remove("is-dragover");
      });
      form.addEventListener("drop", (event) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        if (isSubmitting) return;
        dragDepth = 0;
        dropZone.classList.remove("is-dragover");
        const dropped = Array.from(event.dataTransfer.files || []);
        if (dropped.length === 0) return;
        if (dropped.length > 1) announce(messages.oneFile);
        const transfer = new DataTransfer();
        transfer.items.add(dropped[0]);
        fileField.files = transfer.files;
        updateFile();
        fileField.focus();
      });
    }

    // A file dropped outside the form would otherwise navigate away and lose the draft.
    listenGlobally(window, "dragover", (event) => event.preventDefault());
    listenGlobally(window, "drop", (event) => event.preventDefault());

    contentLanguageField?.addEventListener("change", () => {
      textField.lang = contentLanguageField.value === "fr" ? "fr" : "en";
    });

    // Clearing is destructive, so the button offers Undo for a few seconds.
    const clearLabel = clearButton?.querySelector("span");
    const clearText = clearLabel?.textContent || "";
    let undoTimer = 0;
    const endUndo = () => {
      clearPageTimeout(undoTimer);
      undoState = null;
      if (clearLabel) clearLabel.textContent = clearText;
      updateCounter();
    };

    clearButton?.addEventListener("click", () => {
      if (undoState) {
        const saved = undoState;
        textField.value = saved.text;
        restoreFiles(saved.files);
        pastedFormat = saved.pastedFormat;
        updateFile();
        if (formatField) formatField.value = saved.format;
        endUndo();
        textField.dispatchEvent(new Event("ra:content"));
        textField.focus();
        announce(messages.restored);
        return;
      }
      undoState = {
        text: textField.value,
        files: snapshotFiles(),
        format: formatField?.value || "txt",
        pastedFormat,
      };
      textField.value = "";
      if (fileField) fileField.value = "";
      if (formatField) formatField.value = "txt";
      pastedFormat = "txt";
      updateFile();
      clearErrors();
      textField.dispatchEvent(new Event("ra:content"));
      clearButton.disabled = false;
      if (clearLabel) clearLabel.textContent = messages.undo;
      undoTimer = setPageTimeout(endUndo, 8000);
      toast(messages.clearedShort, { action: messages.undo, onAction: () => { if (undoState) clearButton.click(); }, duration: 8000 });
      textField.focus();
    });
    textField.addEventListener("input", () => { if (undoState) endUndo(); });

    exampleButton?.addEventListener("click", () => {
      if (!hasCompleteSample) return;
      if ((textField.value.trim() || selectedFile()) && !window.confirm(isFr ? "Remplacer le contenu actuel par l’exemple ?" : "Replace the current content with this example?")) {
        return;
      }
      const sampleKey = contentLanguageField?.value === "fr" ? "sampleFr" : "sampleEn";
      textField.value = exampleButton.dataset[sampleKey] || "";
      textField.lang = contentLanguageField?.value === "fr" ? "fr" : "en";
      textField.dispatchEvent(new Event("ra:content"));
      if (fileField) fileField.value = "";
      if (formatField) formatField.value = "txt";
      pastedFormat = "txt";
      updateFile();
      clearErrors();
      updateCounter();
      textField.focus();
      announce(messages.loadedExample);
    });

    // Ctrl/⌘ + Enter runs the primary review from anywhere in the form.
    form.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey) || event.isComposing) return;
      const primary = form.querySelector(".button-primary");
      if (!primary || primary.disabled) return;
      event.preventDefault();
      form.requestSubmit(primary);
    });

    // While the server works: a thin progress bar and a skeleton of the results,
    // so the wait reads as "results are coming" instead of a frozen page.
    let resultsHiddenState = null;
    let loadingSnapshot = null;
    const showLoading = (label) => {
      restoreLoading();
      const bar = document.createElement("div");
      bar.className = "top-progress";
      bar.setAttribute("aria-hidden", "true");
      document.body.append(bar);
      const pill = document.querySelector(".results-heading-row .status-pill");
      const exportNotes = document.querySelector("[data-export-notes]");
      loadingSnapshot = {
        pill,
        pillClass: pill?.className || "",
        pillText: pill?.lastChild?.textContent,
        exportNotes,
        exportHidden: exportNotes?.hidden,
      };
      if (pill) {
        pill.className = "status-pill status-busy";
        if (pill.lastChild) pill.lastChild.textContent = label;
      }
      const scroll = document.querySelector(".results-scroll");
      if (!scroll) return;
      const skeleton = document.createElement("div");
      skeleton.className = "results-skeleton";
      skeleton.setAttribute("aria-hidden", "true");
      for (const kind of ["summary", "chips", "card", "card"]) {
        const block = document.createElement("div");
        block.className = `skeleton-block skeleton-${kind}`;
        skeleton.append(block);
      }
      resultsHiddenState = [...scroll.children].map((child) => ({ child, hidden: child.hidden }));
      resultsHiddenState.forEach(({ child }) => { child.hidden = true; });
      scroll.prepend(skeleton);
      if (exportNotes) exportNotes.hidden = true;
    };

    const restoreLoading = () => {
      document.querySelectorAll(".top-progress, .results-skeleton").forEach((node) => node.remove());
      resultsHiddenState?.forEach(({ child, hidden }) => { child.hidden = hidden; });
      resultsHiddenState = null;
      if (loadingSnapshot?.pill) {
        loadingSnapshot.pill.className = loadingSnapshot.pillClass;
        if (loadingSnapshot.pill.lastChild && loadingSnapshot.pillText !== undefined) {
          loadingSnapshot.pill.lastChild.textContent = loadingSnapshot.pillText;
        }
      }
      if (loadingSnapshot?.exportNotes) loadingSnapshot.exportNotes.hidden = loadingSnapshot.exportHidden;
      loadingSnapshot = null;
    };

    let isSubmitting = false;
    let isEnhancedSubmitting = false;
    const beforeUnloadHandler = (event) => {
      if (!hasUnsavedDraft || (isSubmitting && !isEnhancedSubmitting)) return;
      event.preventDefault();
      event.returnValue = "";
    };
    let beforeUnloadAttached = false;
    globalCleanups.push(() => window.removeEventListener("beforeunload", beforeUnloadHandler));
    const syncBeforeUnload = () => {
      const shouldWarn = hasUnsavedDraft && (!isSubmitting || isEnhancedSubmitting);
      if (shouldWarn && !beforeUnloadAttached) {
        window.addEventListener("beforeunload", beforeUnloadHandler);
        beforeUnloadAttached = true;
      } else if (!shouldWarn && beforeUnloadAttached) {
        window.removeEventListener("beforeunload", beforeUnloadHandler);
        beforeUnloadAttached = false;
      }
    };

    const submitControls = [...form.querySelectorAll("textarea, input[type='file'], select, button[type='button']")];
    let pendingControlStates = null;
    const restoreSubmitControls = () => {
      pendingControlStates?.forEach(({ control, disabled }) => { control.disabled = disabled; });
      pendingControlStates = null;
    };
    let pendingButtonStates = null;
    const restoreSubmitButtons = () => {
      pendingButtonStates?.forEach(({ button, disabled, ariaBusy, labelText, idleLabel, spinnerHidden, arrowHidden }) => {
        button.disabled = disabled;
        if (ariaBusy === null) button.removeAttribute("aria-busy");
        else button.setAttribute("aria-busy", ariaBusy);
        const label = button.querySelector(".button-label");
        if (label) {
          label.textContent = labelText;
          if (idleLabel === undefined) delete label.dataset.idleLabel;
          else label.dataset.idleLabel = idleLabel;
        }
        const spinner = button.querySelector(".button-spinner");
        const arrow = button.querySelector(".button-arrow");
        if (spinner) spinner.hidden = spinnerHidden;
        if (arrow) arrow.hidden = arrowHidden;
      });
      pendingButtonStates = null;
    };
    const showSubmitFailure = () => {
      if (!statusLabel) return;
      statusLabel.setAttribute("role", "alert");
      statusLabel.setAttribute("aria-live", "assertive");
      statusLabel.classList.remove("visually-hidden");
      statusLabel.textContent = "";
      setPageTimeout(() => { statusLabel.textContent = messages.submitFailed; }, 30);
    };

    const enhancedFetchAvailable = () => (
      typeof fetch === "function"
      && typeof FormData === "function"
      && typeof DOMParser === "function"
      && typeof AbortController === "function"
      && typeof URL === "function"
      && typeof window.location?.href === "string"
    );

    const readBoundedResponse = async (response, isCurrentRequest) => {
      const limit = 8_000_000;
      const declared = Number(response.headers?.get("content-length") || 0);
      if (declared > limit) throw new Error("response-too-large");
      if (response.body?.getReader && typeof TextDecoder === "function") {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let bytes = 0;
        let output = "";
        while (true) {
          const part = await reader.read();
          if (!isCurrentRequest()) {
            await reader.cancel();
            throw new Error("stale-request");
          }
          if (part.done) break;
          bytes += part.value.byteLength;
          if (bytes > limit) {
            await reader.cancel();
            throw new Error("response-too-large");
          }
          output += decoder.decode(part.value, { stream: true });
        }
        return output + decoder.decode();
      }
      const output = await response.text();
      if (!isCurrentRequest()) throw new Error("stale-request");
      if (new TextEncoder().encode(output).byteLength > limit) throw new Error("response-too-large");
      return output;
    };

    const isSafeResponseBody = (parsed) => {
      if (parsed.body.querySelectorAll("script, iframe, object, embed, audio, video, source, track, img, base, link, style, meta[http-equiv]").length) return false;
      for (const node of parsed.body.querySelectorAll("*")) {
        const attributes = [...node.attributes];
        if (attributes.some((attribute) => {
          const name = attribute.name.toLowerCase();
          const value = attribute.value.trim();
          if (name.startsWith("on") || name === "style" || name === "srcdoc" || /^(?:javascript|data|vbscript):/i.test(value)) return true;
          const isSvgElement = node.namespaceURI?.toLowerCase() === "http://www.w3.org/2000/svg";
          if (isSvgElement && ["href", "xlink:href"].includes(name)) return !value.startsWith("#");
          const activeUrl = ["src", "srcset", "action", "formaction", "xlink:href"].includes(name)
            || (name === "href" && node.localName?.toLowerCase() === "use");
          if (!activeUrl || value.startsWith("#")) return false;
          try {
            const url = new URL(value, window.location.href);
            return url.origin !== new URL(window.location.href).origin
              || !["http:", "https:"].includes(url.protocol)
              || Boolean(url.username || url.password);
          } catch {
            return true;
          }
        })) return false;
      }
      return true;
    };

    const isAllowedFormResponse = (returnedForm, responseUrl) => {
      const method = (returnedForm.getAttribute("method") || returnedForm.method || "").toLowerCase();
      if (method !== "post") return false;
      const rawAction = returnedForm.getAttribute("action") || returnedForm.action;
      let action;
      try { action = new URL(rawAction, responseUrl); } catch { return false; }
      const responseOrigin = new URL(responseUrl).origin;
      if (action.origin !== responseOrigin || action.pathname !== "/audit" || action.username || action.password || action.search || action.hash) return false;

      const submitters = [...returnedForm.querySelectorAll('button[type="submit"]')];
      const paths = submitters.map((button) => {
        try {
          const destination = new URL(button.getAttribute("formaction") || button.formAction || rawAction, responseUrl);
          if (destination.origin !== responseOrigin || destination.username || destination.password || destination.search || destination.hash) return "";
          return destination.pathname;
        } catch {
          return "";
        }
      });
      return paths.includes("/audit") && paths.includes("/revise")
        && paths.every((path) => path === "/audit" || path === "/revise");
    };

    const copySelectedFile = (from, to) => {
      const file = from?.files?.[0];
      if (!file || !to || typeof DataTransfer !== "function") return;
      try {
        const transfer = new DataTransfer();
        transfer.items.add(file);
        to.files = transfer.files;
      } catch {
        // Browsers that do not permit FileList transfer retain the server's error page.
      }
    };

    const adoptResponse = (parsed, { preserveDraft, forceDirty }) => {
      const incomingText = parsed.getElementById("report-text");
      if (preserveDraft && incomingText) incomingText.value = textField.value;
      const newBody = document.importNode(parsed.body, true);
      if (preserveDraft) copySelectedFile(fileField, newBody.querySelector("#report-file"));
      document.documentElement.lang = parsed.documentElement.lang || "en";
      if (parsed.title) document.title = parsed.title;
      newBody.dataset.enhancedResult = forceDirty ? "false" : "true";
      document.body.replaceWith(newBody);
      initializePage({ forceDirty });
    };

    const submitWithFetch = async (submitButton, formData, actionUrl) => {
      const controller = new AbortController();
      const isCurrentRequest = () => activeRequest === controller;
      activeRequest = controller;
      const timeout = setPageTimeout(() => controller.abort(), 20000);
      activeRequestTimeout = timeout;
      const priorControlStates = submitControls.map((control) => ({ control, disabled: control.disabled }));
      pendingControlStates = priorControlStates;
      submitControls.forEach((control) => { control.disabled = true; });
      try {
        const response = await fetch(actionUrl.href, {
          method: "POST",
          body: formData,
          credentials: "same-origin",
          mode: "same-origin",
          redirect: "error",
          cache: "no-store",
          headers: { Accept: "text/html" },
          signal: controller.signal,
        });
        if (!isCurrentRequest()) return;
        if (response.redirected) throw new Error("unexpected-redirect");
        const responseUrl = new URL(response.url || actionUrl.href, window.location.href);
        if (responseUrl.origin !== new URL(window.location.href).origin || responseUrl.username || responseUrl.password) throw new Error("cross-origin-response");
        if (!["/audit", "/revise"].includes(responseUrl.pathname) || responseUrl.search || responseUrl.hash) throw new Error("unexpected-response-route");
        if ((response.headers?.get("content-type") || "").toLowerCase().split(";")[0].trim() !== "text/html") {
          throw new Error("unexpected-content-type");
        }
        const html = await readBoundedResponse(response, isCurrentRequest);
        if (!isCurrentRequest()) return;
        const parsed = new DOMParser().parseFromString(html, "text/html");
        if (!isSafeResponseBody(parsed)) throw new Error("unsafe-app-response");
        const returnedForm = parsed.getElementById("report-form");
        const returnedPage = parsed.querySelector(".page-content");
        const returnedText = parsed.getElementById("report-text");
        const csrf = returnedForm?.querySelector('input[name="csrf_token"]');
        const isResult = ["audit", "revise"].includes(returnedPage?.dataset.mode);
        const isFormError = Boolean(parsed.querySelector(".form-alert") && returnedForm && returnedText && csrf);
        if (!returnedForm || !returnedText || !csrf || !parsed.getElementById("main-content")
          || !isAllowedFormResponse(returnedForm, responseUrl)) {
          throw new Error("unexpected-app-response");
        }
        if (response.ok && isResult) {
          activeRequest = null;
          clearPageTimeout(timeout);
          activeRequestTimeout = 0;
          adoptResponse(parsed, { preserveDraft: false, forceDirty: false });
          return;
        }
        if (response.status >= 400 && response.status < 500 && isFormError) {
          activeRequest = null;
          clearPageTimeout(timeout);
          activeRequestTimeout = 0;
          adoptResponse(parsed, { preserveDraft: true, forceDirty: true });
          return;
        }
        throw new Error("request-not-accepted");
      } catch {
        if (!isCurrentRequest()) return;
        activeRequest = null;
        clearPageTimeout(timeout);
        activeRequestTimeout = 0;
        restoreLoading();
        restoreSubmitControls();
        restoreSubmitButtons();
        isEnhancedSubmitting = false;
        isSubmitting = false;
        syncBeforeUnload();
        showSubmitFailure();
      }
    };

    // A page restored from the back/forward cache must not keep its buttons locked.
    listenGlobally(window, "pageshow", (event) => {
      if (event.persisted) {
        activeRequest?.abort();
        activeRequest = null;
        if (activeRequestTimeout) clearPageTimeout(activeRequestTimeout);
        activeRequestTimeout = 0;
        isSubmitting = false;
        isEnhancedSubmitting = false;
        restoreLoading();
        restoreSubmitControls();
        restoreSubmitButtons();
      }
      updateFile({ preserveErrors: true, announceLimit: false });
      syncBeforeUnload();
    });

    form.addEventListener("submit", (event) => {
      if (isSubmitting) {
        event.preventDefault();
        return;
      }

      clearErrors();
      const file = selectedFile();
      const unsupportedFile = file && !/\.(?:txt|tex)$/i.test(file.name);
      const oversizedFile = file && file.size > maxFileBytes;

      if (!file && !textField.value.trim()) {
        event.preventDefault();
        setFieldError(textField, textError, messages.empty);
        textField.focus();
        return;
      }

      if (!file && Array.from(textField.value).length > maxChars) {
        event.preventDefault();
        setFieldError(textField, textError, messages.textSize);
        textField.focus();
        return;
      }

      if (unsupportedFile || oversizedFile) {
        event.preventDefault();
        setFieldError(fileField, fileError, unsupportedFile ? messages.fileType : messages.fileSize);
        fileField?.focus();
        return;
      }

      const submitButton = event.submitter instanceof HTMLButtonElement ? event.submitter : null;
      let formData = null;
      let actionUrl = null;
      let useFetch = enhancedFetchAvailable();
      if (useFetch) {
        try {
          actionUrl = new URL(submitButton?.formAction || form.action, window.location.href);
          formData = new FormData(form);
          if (submitButton?.name) formData.append(submitButton.name, submitButton.value);
        } catch {
          // Leave the browser's native POST path available if request setup is unsupported.
          useFetch = false;
        }
      }
      if (useFetch && (actionUrl.origin !== new URL(window.location.href).origin
        || actionUrl.username || actionUrl.password || actionUrl.search || actionUrl.hash
        || !["/audit", "/revise"].includes(actionUrl.pathname))) {
        event.preventDefault();
        showSubmitFailure();
        return;
      }
      if (useFetch) event.preventDefault();

      isSubmitting = true;
      isEnhancedSubmitting = useFetch;
      syncBeforeUnload();
      const allSubmitButtons = [...form.querySelectorAll('button[type="submit"]')];
      pendingButtonStates = allSubmitButtons.map((button) => ({
        button,
        disabled: button.disabled,
        ariaBusy: button.getAttribute("aria-busy"),
        labelText: button.querySelector(".button-label")?.textContent || "",
        idleLabel: button.querySelector(".button-label")?.dataset.idleLabel,
        spinnerHidden: button.querySelector(".button-spinner")?.hidden,
        arrowHidden: button.querySelector(".button-arrow")?.hidden,
      }));
      allSubmitButtons.forEach((button) => {
        button.disabled = true;
        if (button !== submitButton) return;
        button.setAttribute("aria-busy", "true");
        const label = button.querySelector(".button-label");
        const spinner = button.querySelector(".button-spinner");
        const arrow = button.querySelector(".button-arrow");
        const nextText = button.dataset[`loadingLabel${locale === "fr" ? "Fr" : "En"}`];
        if (label && nextText) {
          label.dataset.idleLabel = label.textContent;
          label.textContent = nextText;
        }
        if (spinner) spinner.hidden = false;
        if (arrow) arrow.hidden = true;
      });
      const busyLabel = submitButton?.dataset[`loadingLabel${locale === "fr" ? "Fr" : "En"}`] || (isFr ? "Préparation…" : "Preparing…");
      announce(busyLabel);
      showLoading(busyLabel);
      if (useFetch) void submitWithFetch(submitButton, formData, actionUrl);
    });

    updateFile({ preserveErrors: true, announceLimit: false });
    if (fileField && fileChip && fileNameLabel && removeFileButton) {
      document.documentElement.classList.add("js-ready");
    }

    const firstInvalid = form.querySelector('[aria-invalid="true"]');
    if (firstInvalid) firstInvalid.focus();
    else document.querySelector(".form-alert")?.focus();
  }

  // Server-rendered counts get locale grouping (1 234 / 1,234).
  document.querySelectorAll("data[data-number]").forEach((node) => {
    const value = Number(node.value);
    if (Number.isFinite(value)) node.textContent = numberFormat.format(value);
  });

  // Line references become buttons that select the matching line in the editor,
  // linking each prompt back to its passage.
  if (textField && textField.value) {
    const lines = textField.value.split("\n");
    document.querySelectorAll(".line-reference[data-line]").forEach((reference) => {
      const line = Number(reference.dataset.line);
      if (!Number.isInteger(line) || line < 1 || line > lines.length) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "line-link";
      button.textContent = reference.textContent;
      button.setAttribute("aria-label", messages.showLine(line));
      button.addEventListener("click", () => {
        let start = 0;
        for (let index = 0; index < line - 1; index += 1) start += lines[index].length + 1;
        const end = start + lines[line - 1].length;
        textField.focus({ preventScroll: true });
        textField.setSelectionRange(start, end);
        // Scroll the textarea by the selection's share of the text (wrapping makes
        // exact line offsets unknowable without measuring), then show the editor.
        const share = textField.value.length ? start / textField.value.length : 0;
        textField.scrollTop = Math.max(0, share * textField.scrollHeight - textField.clientHeight / 3);
        textField.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
        announce(messages.lineSelected(line));
      });
      reference.replaceWith(button);
    });
  }

  // Error-summary links move focus to the field, not just scroll to it.
  document.querySelectorAll(".form-alert-list a[href^='#']").forEach((link) => {
    link.addEventListener("click", (event) => {
      const target = document.getElementById(link.hash.slice(1));
      if (!target) return;
      event.preventDefault();
      (target.closest(".field") || target).scrollIntoView({ block: "center" });
      target.focus({ preventScroll: true });
    });
  });

  // Empty state: one primary next step.
  const tryExample = document.querySelector("[data-try-example]");
  if (tryExample && exampleButton) {
    tryExample.hidden = false;
    tryExample.addEventListener("click", () => exampleButton.click());
  }
  document.querySelector("[data-focus-editor]")?.addEventListener("click", (event) => {
    if (!textField) return;
    event.preventDefault();
    textField.scrollIntoView({ block: "center" });
    textField.focus({ preventScroll: true });
  });

  // Check overview: each type with matches becomes a filter for the prompt list,
  // and each prompt can be marked as reviewed. State lives only in this page.
  const overview = document.querySelector("[data-type-overview]");
  const promptCards = overview ? [...overview.parentElement.querySelectorAll(".finding-list > .finding-card")] : [];
  if (overview && promptCards.length) {
    const showAll = overview.querySelector("[data-show-all]");
    const progressText = overview.querySelector("[data-progress-text]");
    const progressBar = document.createElement("span");
    progressBar.className = "review-progress-bar";
    progressBar.setAttribute("aria-hidden", "true");
    progressBar.append(document.createElement("span"));
    progressText?.after(progressBar);

    const rows = [];
    let activeCode = "";
    const applyFilter = (code) => {
      activeCode = code;
      let shown = 0;
      promptCards.forEach((card) => {
        const visible = !code || card.dataset.code === code;
        if (visible && card.hidden) {
          card.classList.remove("is-revealed");
          void card.offsetWidth;
          card.classList.add("is-revealed");
        }
        card.hidden = !visible;
        if (visible) shown += 1;
      });
      rows.forEach((row) => row.setAttribute("aria-pressed", String(row.dataset.code === code)));
      if (showAll) showAll.hidden = !code;
      announce(messages.filtered(shown));
    };

    overview.querySelectorAll(".type-item").forEach((item) => {
      const content = [...item.childNodes];
      const row = document.createElement(Number(item.dataset.count) > 0 ? "button" : "div");
      row.className = "type-row";
      row.append(...content);
      if (row instanceof HTMLButtonElement) {
        row.type = "button";
        row.dataset.code = item.dataset.code;
        row.setAttribute("aria-pressed", "false");
        row.addEventListener("click", () => applyFilter(activeCode === row.dataset.code ? "" : row.dataset.code));
        rows.push(row);
      }
      item.append(row);
    });
    showAll?.addEventListener("click", () => applyFilter(""));

    const updateProgress = () => {
      const done = promptCards.filter((card) => card.classList.contains("is-reviewed")).length;
      if (progressText) progressText.textContent = messages.reviewed(done, promptCards.length);
      progressBar.firstChild.style.transform = `scaleX(${done / promptCards.length})`;
    };

    promptCards.forEach((card) => {
      const actions = document.createElement("div");
      actions.className = "finding-actions";
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "text-button review-toggle";
      toggle.setAttribute("aria-pressed", "false");
      const svgNs = "http://www.w3.org/2000/svg";
      const icon = document.createElementNS(svgNs, "svg");
      icon.setAttribute("class", "icon");
      icon.setAttribute("aria-hidden", "true");
      const use = document.createElementNS(svgNs, "use");
      use.setAttribute("href", "#i-check");
      icon.append(use);
      const toggleLabel = document.createElement("span");
      toggleLabel.textContent = messages.markReviewed;
      toggle.append(icon, toggleLabel);
      toggle.addEventListener("click", () => {
        const reviewed = card.classList.toggle("is-reviewed");
        toggle.setAttribute("aria-pressed", String(reviewed));
        toggle.lastChild.textContent = reviewed ? messages.isReviewed : messages.markReviewed;
        updateProgress();
        announce(progressText?.textContent || "");
      });
      actions.append(toggle);
      card.append(actions);
    });
    updateProgress();
  }

  // Highlight the changed words inside each before/after pair. Tokens are
  // compared with a longest-common-subsequence pass; text goes in via textContent.
  const tokenize = (text) => text.match(/\s+|[\p{L}\p{N}’'_-]+|[^\s\p{L}\p{N}]/gu) || [];
  const markChanges = (paragraph, tokens, keep, className, tagName) => {
    const fragment = document.createDocumentFragment();
    tokens.forEach((token, index) => {
      if (keep[index] || /^\s+$/.test(token)) {
        fragment.append(token);
      } else {
        const mark = document.createElement(tagName);
        mark.className = className;
        mark.textContent = token;
        fragment.append(mark);
      }
    });
    paragraph.replaceChildren(fragment);
  };
  document.querySelectorAll(".edit-compare").forEach((pair) => {
    const before = pair.querySelector(".edit-before p");
    const after = pair.querySelector(".edit-after p");
    if (!before || !after) return;
    const a = tokenize(before.textContent);
    const b = tokenize(after.textContent);
    if (a.length * b.length > 250000) return;
    const table = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
    for (let i = a.length - 1; i >= 0; i -= 1) {
      for (let j = b.length - 1; j >= 0; j -= 1) {
        table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
      }
    }
    const keepA = new Array(a.length).fill(false);
    const keepB = new Array(b.length).fill(false);
    for (let i = 0, j = 0; i < a.length && j < b.length;) {
      if (a[i] === b[j]) { keepA[i] = true; keepB[j] = true; i += 1; j += 1; }
      else if (table[i + 1][j] >= table[i][j + 1]) i += 1;
      else j += 1;
    }
    markChanges(before, a, keepA, "word-del", "del");
    markChanges(after, b, keepB, "word-ins", "ins");
  });

  // Colour unified-diff lines. Built with textContent only; skipped for very
  // large diffs to keep the page responsive.
  const diffPreview = document.querySelector(".diff-preview");
  if (diffPreview) {
    const diffLines = diffPreview.textContent.split("\n");
    if (diffLines.length <= 4000) {
      const fragment = document.createDocumentFragment();
      diffLines.forEach((text, index) => {
        const span = document.createElement("span");
        span.className = "diff-line";
        if (text.startsWith("+++") || text.startsWith("---") || text.startsWith("@@")) span.classList.add("diff-meta");
        else if (text.startsWith("+")) span.classList.add("diff-add");
        else if (text.startsWith("-")) span.classList.add("diff-remove");
        span.textContent = index < diffLines.length - 1 ? `${text}\n` : text;
        fragment.append(span);
      });
      diffPreview.replaceChildren(fragment);
    }
  }

  // Copy a single suggested line.
  if (navigator.clipboard && window.isSecureContext) {
    document.querySelectorAll(".copy-button").forEach((button) => {
      const source = button.parentElement?.querySelector("p");
      const label = button.querySelector("span");
      if (!source || !label) return;
      button.hidden = false;
      const idle = label.textContent;
      let resetTimer = 0;
      button.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(source.textContent);
          label.textContent = isFr ? "Copié" : "Copied";
          toast(messages.copied);
        } catch {
          announce(messages.copyFailed);
        }
        clearPageTimeout(resetTimer);
        resetTimer = setPageTimeout(() => { label.textContent = idle; }, 1800);
      });
    });
  }

  // Counts settle from zero so the summary reads as fresh results.
  if (!messages.reducedMotion.matches) {
    document.querySelectorAll(".stat-value data[data-number]").forEach((node) => {
      const target = Number(node.value);
      if (!Number.isFinite(target) || target < 2) return;
      const started = performance.now();
      const step = (now) => {
        const progress = Math.min(1, (now - started) / 650);
        const eased = 1 - (1 - progress) ** 3;
        node.textContent = numberFormat.format(Math.round(target * eased));
        if (progress < 1) requestPageFrame(step);
      };
      requestPageFrame(step);
    });
  }

  // Highlight flagged sentences inside the editor. A backdrop with the same
  // metrics sits behind the transparent textarea; marks follow edits and vanish
  // once a sentence has been rewritten.
  const findingCards = [...document.querySelectorAll(".finding-list > .finding-card")];
  const wrap = textField?.closest(".textarea-wrap");
  if (textField && wrap && findingCards.length && textField.value) {
    const backdrop = document.createElement("div");
    backdrop.className = "editor-highlights";
    backdrop.setAttribute("aria-hidden", "true");
    const inner = document.createElement("div");
    inner.className = "editor-highlights-inner";
    backdrop.append(inner);
    wrap.prepend(backdrop);
    wrap.classList.add("has-highlights");

    const targets = findingCards.map((card, index) => ({
      card,
      index,
      sentence: card.querySelector(".excerpt")?.textContent || "",
      line: Number(card.querySelector("[data-line], .line-link")?.dataset.line || 0),
      kind: card.dataset.category === "source" ? "kind-source" : "kind-writing",
    }));

    const syncBox = () => {
      const style = getComputedStyle(textField);
      for (const property of ["fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "wordSpacing", "tabSize", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft"]) {
        backdrop.style[property] = style[property];
      }
      backdrop.style.top = `${textField.offsetTop}px`;
      backdrop.style.left = `${textField.offsetLeft}px`;
      backdrop.style.width = `${textField.clientWidth}px`;
      backdrop.style.height = `${textField.clientHeight}px`;
      inner.style.transform = `translateY(${-textField.scrollTop}px)`;
    };

    const paint = () => {
      const value = textField.value;
      const lineStarts = [0];
      for (let i = 0; i < value.length; i += 1) if (value[i] === "\n") lineStarts.push(i + 1);
      const ranges = [];
      for (const target of targets) {
        if (target.sentence.length < 8) continue;
        let start = value.indexOf(target.sentence, lineStarts[Math.max(0, target.line - 1)] || 0);
        if (start < 0) start = value.indexOf(target.sentence);
        if (start < 0) continue;
        ranges.push({ start, end: start + target.sentence.length, target });
      }
      ranges.sort((a, b) => a.start - b.start || (a.target.kind === "kind-source" ? -1 : 1));
      const fragment = document.createDocumentFragment();
      let cursor = 0;
      for (const range of ranges) {
        if (range.start < cursor) {
          // Overlap: tag the existing mark so either card can light it up.
          const last = fragment.lastChild;
          if (last?.dataset) last.dataset.cards += ` ${range.target.index}`;
          continue;
        }
        fragment.append(value.slice(cursor, range.start));
        const mark = document.createElement("mark");
        mark.className = range.target.kind;
        mark.dataset.cards = String(range.target.index);
        mark.textContent = value.slice(range.start, range.end);
        fragment.append(mark);
        cursor = range.end;
      }
      fragment.append(`${value.slice(cursor)}\n`);
      inner.replaceChildren(fragment);
      syncBox();
    };

    const setActive = (index, active) => {
      inner.querySelectorAll("mark").forEach((mark) => {
        if (mark.dataset.cards.split(" ").includes(String(index))) mark.classList.toggle("is-active", active);
      });
    };
    targets.forEach(({ card, index }) => {
      card.addEventListener("mouseenter", () => setActive(index, true));
      card.addEventListener("mouseleave", () => setActive(index, false));
      card.addEventListener("focusin", () => setActive(index, true));
      card.addEventListener("focusout", () => setActive(index, false));
    });

    let paintTimer = 0;
    const schedulePaint = () => {
      clearPageTimeout(paintTimer);
      paintTimer = setPageTimeout(paint, 120);
    };
    textField.addEventListener("input", schedulePaint);
    textField.addEventListener("ra:content", schedulePaint);
    textField.addEventListener("scroll", () => { inner.style.transform = `translateY(${-textField.scrollTop}px)`; });
    if (typeof ResizeObserver === "function") {
      const observer = new ResizeObserver(syncBox);
      observer.observe(textField);
      observers.add(observer);
    }
    paint();
  }

  // Export the review as Markdown so a student can keep it next to the draft.
  const exportButton = document.querySelector("[data-export-notes]");
  if (exportButton && typeof URL.createObjectURL === "function") {
    exportButton.hidden = false;
    exportButton.addEventListener("click", () => {
      const text = (node) => node?.textContent.replace(/\s+/g, " ").trim() || "";
      const lines = [`# ${isFr ? "Notes de relecture" : "Review notes"} — ${text(document.querySelector(".source-name"))}`, ""];
      lines.push(`${text(document.querySelector(".summary-row .meta-label"))}`, "");
      document.querySelectorAll(".document-stat").forEach((stat) => {
        lines.push(`- ${text(stat.querySelector(".stat-label"))}: ${stat.querySelector("data")?.value ?? ""}`);
      });
      lines.push("", `> ${text(document.querySelector(".summary-caveat"))}`, "");
      document.querySelectorAll(".results-scroll .content-section").forEach((section) => {
        lines.push(`## ${text(section.querySelector("h3"))}`, "");
        section.querySelectorAll(".finding-card").forEach((card, index) => {
          const badge = text(card.querySelector(".kind-badge"));
          const where = text(card.querySelector(".line-link, .line-reference"));
          lines.push(`### ${index + 1}. ${badge} — ${where}${card.classList.contains("is-reviewed") ? ` ✓ ${messages.isReviewed}` : ""}`, "");
          if (card.querySelector(".excerpt")) lines.push(`> ${text(card.querySelector(".excerpt"))}`, "");
          if (card.querySelector(".finding-reason")) lines.push(text(card.querySelector(".finding-reason")), "");
          if (card.querySelector(".finding-prompt")) lines.push(`**${text(card.querySelector(".finding-prompt strong"))}** ${text(card.querySelector(".finding-prompt span"))}`, "");
          card.querySelectorAll(".fact-list li").forEach((fact) => lines.push(`- ${text(fact)}`));
          lines.push("");
        });
        section.querySelectorAll(".note-list li").forEach((note) => lines.push(`- ${text(note)}`));
        section.querySelectorAll(".section-note").forEach((note) => lines.push(`_${text(note)}_`, ""));
      });
      const url = createPageObjectUrl(new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${baseName}_review_notes.md`;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setPageTimeout(() => revokePageObjectUrl(url), 1000);
      toast(messages.exported);
    });
  }

  // Keyboard: J/K move between prompts, X marks reviewed, G shows the passage,
  // ? opens the shortcut sheet. Ignored while typing in a field.
  const shortcutsDialog = document.getElementById("shortcuts-dialog");
  const openShortcuts = () => {
    if (shortcutsDialog && typeof shortcutsDialog.showModal === "function" && !shortcutsDialog.open) shortcutsDialog.showModal();
  };
  document.querySelectorAll("[data-open-shortcuts]").forEach((button) => button.addEventListener("click", openShortcuts));
  let currentCard = -1;
  const visibleCards = () => findingCards.filter((card) => !card.hidden);
  const focusCard = (card) => {
    findingCards.forEach((other) => other.classList.toggle("is-current", other === card));
    card.tabIndex = -1;
    card.focus({ preventScroll: true });
    card.scrollIntoView({ block: "nearest", behavior: messages.reducedMotion.matches ? "auto" : "smooth" });
  };
  listenGlobally(document, "keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;
    const field = event.target.closest?.("input, textarea, select, [contenteditable]");
    if (field || shortcutsDialog?.open) return;
    const key = event.key.toLowerCase();
    if (event.key === "?") {
      event.preventDefault();
      openShortcuts();
      return;
    }
    const cards = visibleCards();
    if (!cards.length) return;
    if (key === "j" || key === "k") {
      event.preventDefault();
      const position = cards.indexOf(findingCards[currentCard]);
      const next = key === "j" ? Math.min(cards.length - 1, position + 1) : Math.max(0, position - 1);
      currentCard = findingCards.indexOf(cards[next]);
      focusCard(cards[next]);
    } else if ((key === "x" || key === "g") && currentCard >= 0) {
      event.preventDefault();
      const card = findingCards[currentCard];
      card.querySelector(key === "x" ? ".review-toggle" : ".line-link")?.click();
    }
  });

  const downloadButtons = [...document.querySelectorAll("[data-download]")];
  const sourceHeading = document.querySelector(".source-name");
  const sourceTitle = sourceHeading?.dataset.sourceName?.trim() || sourceHeading?.textContent?.trim() || "rapport";
  const baseName = sourceTitle
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, "-")
    .replace(/\.+$/g, "")
    .replace(/\.(?:txt|tex)$/i, "")
    .trim() || "rapport";

  downloadButtons.forEach((button) => {
    const source = document.querySelector(`[data-download-source="${button.dataset.download}"]`);
    if (!source || typeof URL.createObjectURL !== "function") return;
    button.hidden = false;
    button.addEventListener("click", () => {
      const kind = button.dataset.download;
      const extension = kind === "cleaned" ? "txt" : (button.dataset.sourceFormat || "txt").replace(/^\./, "");
      const filename = kind === "cleaned" ? `${baseName}_cleaned.txt` : `${baseName}_revision_preview.${extension}`;
      const blob = new Blob([source.value], { type: "text/plain;charset=utf-8" });
      const url = createPageObjectUrl(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.hidden = true;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setPageTimeout(() => revokePageObjectUrl(url), 1000);
    });
  });

  if (page && ["audit", "revise"].includes(page.dataset.mode)) {
    // Bring the results to the top of the screen (not just barely into view) so a
    // stacked layout shows the summary and first prompts, then move focus there.
    const heading = document.getElementById("results-heading");
    heading?.scrollIntoView({ block: "start" });
    heading?.focus({ preventScroll: true });
  }
    };

    run();
  };

  initializePage();
})();
