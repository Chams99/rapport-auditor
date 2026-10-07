(() => {
  "use strict";

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
  const fileNameLabel = document.getElementById("file-name");
  const fileError = document.getElementById("file-error");
  const textError = document.getElementById("text-error");
  const statusLabel = document.getElementById("submission-status");
  const editorState = document.querySelector(".editor-state");
  const editorStateText = document.getElementById("editor-state-text");
  const removeFileButton = document.getElementById("remove-file");
  const resultsStale = document.getElementById("results-stale");
  const reviewFilters = document.getElementById("review-filters");
  const filterStatus = document.getElementById("filter-status");
  const filterEmpty = document.getElementById("filter-empty");
  const locale = document.documentElement.lang === "fr" ? "fr" : "en";
  const numberFormat = new Intl.NumberFormat(locale);
  const maxChars = Number(form?.dataset.maxChars || 250000);
  const maxFileBytes = Number(form?.dataset.maxFileBytes || 1000000);
  const fileSizeFormat = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  const messages = {
    empty: locale === "fr" ? "Ajoutez du texte ou choisissez un fichier avant de continuer." : "Add some text or choose a file before continuing.",
    textSize: locale === "fr" ? `Le texte dépasse la limite de ${numberFormat.format(maxChars)} caractères. Divisez-le en sections et réessayez.` : `Text exceeds the ${numberFormat.format(maxChars)}-character limit. Split it into sections and try again.`,
    fileType: locale === "fr" ? "Choisissez un fichier .txt ou .tex encodé en UTF-8." : "Choose a UTF-8 .txt or .tex file.",
    fileSize: locale === "fr" ? `Ce fichier dépasse la limite de ${fileSizeFormat.format(maxFileBytes / 1000000)} Mo.` : `This file is larger than the ${fileSizeFormat.format(maxFileBytes / 1000000)} MB limit.`,
    loadedExample: locale === "fr" ? "Exemple chargé. Vous pouvez le modifier avant la revue." : "Example loaded. Edit it before starting your review.",
    clearConfirm: locale === "fr" ? "Effacer le texte et le fichier sélectionné ?" : "Clear the text and selected file?",
    limitReached: locale === "fr" ? `Limite de ${numberFormat.format(maxChars)} caractères dépassée.` : `The ${numberFormat.format(maxChars)}-character limit has been exceeded.`,
    limitRestored: locale === "fr" ? "Le texte est de nouveau dans la limite." : "The text is back within the limit.",
    stateEmpty: locale === "fr" ? "Ajoutez du texte ou choisissez un fichier pour commencer." : "Add text or choose a file to get started.",
    stateReady: locale === "fr" ? "Prêt à analyser." : "Ready to review.",
    stateInvalid: locale === "fr" ? "Vérifiez le champ signalé avant de continuer." : "Check the highlighted field before continuing.",
    stale: locale === "fr" ? "Le texte a changé. Soumettez-le à nouveau pour actualiser les résultats." : "The text has changed. Submit it again to refresh these results.",
    filtersAll: (total) => locale === "fr" ? `${total} ${total === 1 ? "piste affichée." : "pistes affichées."}` : `Showing all ${total} displayed prompts.`,
    filtersWriting: (shown, total) => locale === "fr" ? `Affichage de ${shown} des ${total} pistes affichées dans la catégorie rédactionnelle.` : `Showing ${shown} of ${total} displayed prompts in the writing category.`,
    filtersSource: (shown, total) => locale === "fr" ? `Affichage de ${shown} des ${total} pistes affichées dans la catégorie source.` : `Showing ${shown} of ${total} displayed prompts in the source category.`,
    filterEmpty: locale === "fr" ? "Aucun constat dans cette catégorie." : "No findings in this category.",
  };

  if (form && textField && countLabel) {
    const hasCompleteSample = Boolean(
      exampleButton?.dataset.sampleEn?.trim() && exampleButton?.dataset.sampleFr?.trim(),
    );
    if (exampleButton && hasCompleteSample) {
      exampleButton.hidden = false;
      if (copySampleDisclosure) copySampleDisclosure.hidden = true;
    }
    if (clearButton) clearButton.hidden = false;

    const submitButtons = [...form.querySelectorAll('button[type="submit"]')];
    const originalSubmitStates = new Map(submitButtons.map((button) => [button, {
      disabled: button.disabled,
      label: button.querySelector(".button-label")?.textContent || "",
      spinnerHidden: button.querySelector(".button-spinner")?.hidden ?? true,
      arrowHidden: button.querySelector(".button-arrow")?.hidden ?? false,
    }]));
    const originalStatusText = statusLabel?.textContent || "";
    let isSubmitting = false;
    let loadingStatusText = null;
    let statusBeforeSubmit = originalStatusText;
    let previousOverLimit = false;

    const selectedFile = () => fileField?.files?.[0] || null;
    let pastedFormat = formatField?.value || "txt";
    let hasUnsavedDraft = textField.value.length > 0 || Boolean(selectedFile());
    if (removeFileButton) {
      removeFileButton.hidden = !selectedFile();
      removeFileButton.disabled = !selectedFile();
    }

    const setEditorState = (state, text) => {
      if (editorState) editorState.dataset.state = state;
      if (editorStateText) editorStateText.textContent = text;
    };

    const updateEditorState = () => {
      if (isSubmitting) return;
      const file = selectedFile();
      const isInvalid = file
        ? fileField?.getAttribute("aria-invalid") === "true"
          || !/\.(?:txt|tex)$/i.test(file.name)
          || file.size > maxFileBytes
        : textField.getAttribute("aria-invalid") === "true"
          || Array.from(textField.value).length > maxChars;
      if (isInvalid) setEditorState("invalid", messages.stateInvalid);
      else if (!textField.value.trim() && !file) setEditorState("empty", messages.stateEmpty);
      else setEditorState("ready", messages.stateReady);
    };

    const markResultsStale = () => {
      if (!resultsStale || !page || !["audit", "revise"].includes(page.dataset.mode)) return;
      resultsStale.hidden = false;
      const localeSuffix = `${locale[0].toUpperCase()}${locale.slice(1)}`;
      resultsStale.textContent = resultsStale.dataset[`message${localeSuffix}`] || messages.stale;
    };

    const updateCounter = ({ announce = true } = {}) => {
      const currentLength = Array.from(textField.value).length;
      countLabel.textContent = `${numberFormat.format(currentLength)} / ${numberFormat.format(maxChars)}`;
      const isOverLimit = currentLength > maxChars;
      countLabel.classList.toggle("is-over-limit", isOverLimit);
      if (clearButton) clearButton.disabled = textField.value.length === 0 && !(fileField?.files?.length);
      if (announce && isOverLimit !== previousOverLimit && statusLabel) {
        statusLabel.textContent = isOverLimit ? messages.limitReached : messages.limitRestored;
      }
      previousOverLimit = isOverLimit;
      updateEditorState();
    };

    const setFieldError = (field, label, message) => {
      if (!field || !label) return;
      label.textContent = message || "";
      label.hidden = !message;
      field.setAttribute("aria-invalid", message ? "true" : "false");
    };

    const clearErrors = () => {
      setFieldError(textField, textError, "");
      setFieldError(fileField, fileError, "");
    };

    const syncFileControls = () => {
      const file = selectedFile();
      if (fileNameLabel) fileNameLabel.textContent = file ? file.name : "";
      if (formatField) {
        if (file) {
          formatField.value = file.name.toLowerCase().endsWith(".tex") ? "tex" : "txt";
          formatField.disabled = true;
        } else {
          formatField.value = pastedFormat;
          formatField.disabled = false;
        }
      }
      if (removeFileButton) {
        removeFileButton.hidden = !file;
        removeFileButton.disabled = !file;
      }
    };

    formatField?.addEventListener("change", () => {
      if (selectedFile()) return;
      pastedFormat = formatField.value;
      hasUnsavedDraft = textField.value.length > 0 || Boolean(selectedFile());
      markResultsStale();
      updateEditorState();
    });

    const updateFile = () => {
      const file = selectedFile();
      setFieldError(fileField, fileError, "");
      if (file) setFieldError(textField, textError, "");

      if (file && !/\.(?:txt|tex)$/i.test(file.name)) {
        setFieldError(fileField, fileError, messages.fileType);
      } else if (file && file.size > maxFileBytes) {
        setFieldError(fileField, fileError, messages.fileSize);
      }

      syncFileControls();
      if (file) {
        hasUnsavedDraft = true;
      } else {
        hasUnsavedDraft = textField.value.length > 0;
      }
      updateCounter();
    };

    textField.addEventListener("input", () => {
      setFieldError(textField, textError, "");
      hasUnsavedDraft = textField.value.length > 0 || Boolean(selectedFile());
      markResultsStale();
      updateCounter();
    });

    fileField?.addEventListener("change", () => {
      updateFile();
      markResultsStale();
    });

    contentLanguageField?.addEventListener("change", () => {
      if (textField) textField.lang = contentLanguageField.value === "fr" ? "fr" : "en";
      hasUnsavedDraft = textField.value.length > 0 || Boolean(selectedFile());
      markResultsStale();
      updateEditorState();
    });

    clearButton?.addEventListener("click", () => {
      if ((textField.value.length > 0 || selectedFile()) && !window.confirm(messages.clearConfirm)) return;
      textField.value = "";
      if (fileField) fileField.value = "";
      pastedFormat = "txt";
      syncFileControls();
      hasUnsavedDraft = false;
      clearErrors();
      updateCounter();
      markResultsStale();
      textField.focus();
    });

    removeFileButton?.addEventListener("click", () => {
      if (!selectedFile()) return;
      fileField.value = "";
      updateFile();
      markResultsStale();
      fileField.focus();
    });

    exampleButton?.addEventListener("click", () => {
      if (!hasCompleteSample) return;
      if ((textField.value.trim() || selectedFile()) && !window.confirm(locale === "fr" ? "Remplacer le contenu actuel par l’exemple ?" : "Replace the current content with this example?")) {
        return;
      }
      const sampleKey = contentLanguageField?.value === "fr" ? "sampleFr" : "sampleEn";
      textField.value = exampleButton.dataset[sampleKey] || "";
      textField.lang = contentLanguageField?.value === "fr" ? "fr" : "en";
      if (fileField) fileField.value = "";
      pastedFormat = "txt";
      syncFileControls();
      hasUnsavedDraft = true;
      clearErrors();
      updateCounter();
      markResultsStale();
      textField.focus();
      if (statusLabel) statusLabel.textContent = messages.loadedExample;
    });

    window.addEventListener("beforeunload", (event) => {
      if (!hasUnsavedDraft || isSubmitting) return;
      event.preventDefault();
      event.returnValue = "";
    });

    window.addEventListener("pageshow", () => {
      if (isSubmitting) {
        isSubmitting = false;
        form.removeAttribute("aria-busy");
        submitButtons.forEach((button) => {
          const original = originalSubmitStates.get(button);
          if (!original) return;
          button.disabled = original.disabled;
          const label = button.querySelector(".button-label");
          const spinner = button.querySelector(".button-spinner");
          const arrow = button.querySelector(".button-arrow");
          if (label) label.textContent = original.label;
          if (spinner) spinner.hidden = original.spinnerHidden;
          if (arrow) arrow.hidden = original.arrowHidden;
        });
        if (statusLabel && statusLabel.textContent === loadingStatusText) {
          statusLabel.textContent = statusBeforeSubmit;
        }
        loadingStatusText = null;
      }
      syncFileControls();
      hasUnsavedDraft = textField.value.length > 0 || Boolean(selectedFile());
      updateCounter({ announce: false });
      updateEditorState();
      // Deliberately do not move focus here: this also runs on initial pageshow.
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
        updateEditorState();
        textField.focus();
        return;
      }

      if (!file && Array.from(textField.value).length > maxChars) {
        event.preventDefault();
        setFieldError(textField, textError, messages.textSize);
        updateEditorState();
        textField.focus();
        return;
      }

      if (unsupportedFile || oversizedFile) {
        event.preventDefault();
        setFieldError(fileField, fileError, unsupportedFile ? messages.fileType : messages.fileSize);
        updateEditorState();
        fileField?.focus();
        return;
      }

      isSubmitting = true;
      const submitButton = event.submitter instanceof HTMLButtonElement ? event.submitter : null;
      form.setAttribute("aria-busy", "true");
      submitButtons.forEach((button) => {
        button.disabled = true;
        if (button !== submitButton) return;
        const label = button.querySelector(".button-label");
        const spinner = button.querySelector(".button-spinner");
        const arrow = button.querySelector(".button-arrow");
        const localeSuffix = `${locale[0].toUpperCase()}${locale.slice(1)}`;
        const nextText = button.dataset[`loadingLabel${localeSuffix}`];
        if (label && nextText) label.textContent = nextText;
        if (spinner) spinner.hidden = false;
        if (arrow) arrow.hidden = true;
        loadingStatusText = nextText || (locale === "fr" ? "Préparation…" : "Preparing…");
      });
      loadingStatusText ||= locale === "fr" ? "Préparation…" : "Preparing…";
      setEditorState("working", loadingStatusText || messages.stateReady);
      statusBeforeSubmit = statusLabel?.textContent || "";
      if (statusLabel) {
        statusLabel.textContent = loadingStatusText || (locale === "fr" ? "Préparation…" : "Preparing…");
      }
    });

    updateCounter();
    updateEditorState();

    const findingCards = [...document.querySelectorAll('.evidence-card[data-review-category]')];
    const filterButtons = reviewFilters ? [...reviewFilters.querySelectorAll("[data-review-filter]")] : [];
    if (reviewFilters && filterButtons.length && findingCards.length) {
      reviewFilters.hidden = false;
      const applyReviewFilter = (filter) => {
        const visible = findingCards.filter((card) => {
          const matches = filter === "all" || card.dataset.reviewCategory === filter;
          card.hidden = !matches;
          return matches;
        }).length;
        filterButtons.forEach((button) => {
          button.setAttribute("aria-pressed", button.dataset.reviewFilter === filter ? "true" : "false");
        });
        if (filterEmpty) {
          filterEmpty.hidden = visible > 0;
          if (visible === 0) filterEmpty.textContent = messages.filterEmpty;
        }
        if (filterStatus) {
          filterStatus.hidden = false;
          filterStatus.textContent = filter === "all"
            ? messages.filtersAll(visible)
            : filter === "writing"
              ? messages.filtersWriting(visible, findingCards.length)
              : messages.filtersSource(visible, findingCards.length);
        }
      };
      filterButtons.forEach((button) => {
        button.addEventListener("click", () => {
          const filter = button.dataset.reviewFilter;
          if (["all", "writing", "source"].includes(filter)) applyReviewFilter(filter);
        });
      });
      applyReviewFilter("all");
    }

    const firstInvalid = form.querySelector('[aria-invalid="true"]');
    if (firstInvalid) firstInvalid.focus();
    else document.querySelector(".form-alert")?.focus();
  }

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
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.hidden = true;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  });

  if (page && ["audit", "revise"].includes(page.dataset.mode)) {
    const heading = document.getElementById("results-heading");
    heading?.focus();
  }
})();
