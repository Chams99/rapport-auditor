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
  const fileNameLabel = document.getElementById("file-name");
  const fileError = document.getElementById("file-error");
  const textError = document.getElementById("text-error");
  const statusLabel = document.getElementById("submission-status");
  const locale = document.documentElement.lang === "fr" ? "fr" : "en";
  const numberFormat = new Intl.NumberFormat(locale);
  const maxChars = Number(form?.dataset.maxChars || 250000);
  const maxFileBytes = Number(form?.dataset.maxFileBytes || 10485760);
  const fileSizeFormat = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  const messages = {
    empty: locale === "fr" ? "Ajoutez du texte ou choisissez un fichier avant de continuer." : "Add some text or choose a file before continuing.",
    textSize: locale === "fr" ? `Le texte dépasse la limite de ${numberFormat.format(maxChars)} caractères. Divisez-le en sections et réessayez.` : `Text exceeds the ${numberFormat.format(maxChars)}-character limit. Split it into sections and try again.`,
    fileType: locale === "fr" ? "Choisissez un fichier .txt ou .tex encodé en UTF-8." : "Choose a UTF-8 .txt or .tex file.",
    fileSize: locale === "fr" ? `Ce fichier dépasse la limite de ${fileSizeFormat.format(maxFileBytes / 1000000)} Mo.` : `This file is larger than the ${fileSizeFormat.format(maxFileBytes / 1000000)} MB limit.`,
    loadedExample: locale === "fr" ? "Exemple chargé. Vous pouvez le modifier avant la revue." : "Example loaded. Edit it before starting your review.",
  };

  if (form && textField && countLabel && clearButton && exampleButton) {
    exampleButton.hidden = false;
    clearButton.hidden = false;

    const updateCounter = () => {
      const currentLength = Array.from(textField.value).length;
      countLabel.textContent = `${numberFormat.format(currentLength)} / ${numberFormat.format(maxChars)}`;
      countLabel.classList.toggle("is-over-limit", currentLength > maxChars);
      clearButton.disabled = textField.value.length === 0 && !(fileField?.files?.length);
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

    let pastedFormat = formatField?.value || "txt";
    let hasUnsavedDraft = false;
    const selectedFile = () => fileField?.files?.[0] || null;
    hasUnsavedDraft = textField.value.length > 0 || Boolean(selectedFile());

    formatField?.addEventListener("change", () => {
      if (!selectedFile()) pastedFormat = formatField.value;
    });

    const updateFile = () => {
      const file = selectedFile();
      if (fileNameLabel) fileNameLabel.textContent = file ? file.name : "";
      setFieldError(fileField, fileError, "");

      if (file && !/\.(?:txt|tex)$/i.test(file.name)) {
        setFieldError(fileField, fileError, messages.fileType);
      } else if (file && file.size > maxFileBytes) {
        setFieldError(fileField, fileError, messages.fileSize);
      }

      if (file && formatField) {
        formatField.value = file.name.toLowerCase().endsWith(".tex") ? "tex" : "txt";
        hasUnsavedDraft = true;
      } else if (!file && formatField) {
        formatField.value = pastedFormat;
        hasUnsavedDraft = textField.value.length > 0;
      }
      updateCounter();
    };

    textField.addEventListener("input", () => {
      setFieldError(textField, textError, "");
      hasUnsavedDraft = textField.value.length > 0 || Boolean(selectedFile());
      updateCounter();
    });

    fileField?.addEventListener("change", updateFile);

    contentLanguageField?.addEventListener("change", () => {
      if (textField) textField.lang = contentLanguageField.value === "fr" ? "fr" : "en";
    });

    clearButton.addEventListener("click", () => {
      textField.value = "";
      if (fileField) fileField.value = "";
      if (fileNameLabel) fileNameLabel.textContent = "";
      if (formatField) formatField.value = "txt";
      pastedFormat = "txt";
      hasUnsavedDraft = false;
      clearErrors();
      updateCounter();
      textField.focus();
    });

    exampleButton.addEventListener("click", () => {
      if ((textField.value.trim() || selectedFile()) && !window.confirm(locale === "fr" ? "Remplacer le contenu actuel par l’exemple ?" : "Replace the current content with this example?")) {
        return;
      }
      const sampleKey = contentLanguageField?.value === "fr" ? "sampleFr" : "sampleEn";
      textField.value = exampleButton.dataset[sampleKey] || "";
      textField.lang = contentLanguageField?.value === "fr" ? "fr" : "en";
      if (fileField) fileField.value = "";
      if (fileNameLabel) fileNameLabel.textContent = "";
      if (formatField) formatField.value = "txt";
      pastedFormat = "txt";
      hasUnsavedDraft = true;
      clearErrors();
      updateCounter();
      textField.focus();
      if (statusLabel) statusLabel.textContent = messages.loadedExample;
    });

    let isSubmitting = false;
    window.addEventListener("beforeunload", (event) => {
      if (!hasUnsavedDraft || isSubmitting) return;
      event.preventDefault();
      event.returnValue = "";
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

      isSubmitting = true;
      const submitButton = event.submitter instanceof HTMLButtonElement ? event.submitter : null;
      const allSubmitButtons = [...form.querySelectorAll('button[type="submit"]')];
      allSubmitButtons.forEach((button) => {
        button.disabled = true;
        if (button !== submitButton) return;
        const label = button.querySelector(".button-label");
        const spinner = button.querySelector(".button-spinner");
        const arrow = button.querySelector(".button-arrow");
        const nextText = button.dataset[`loadingLabel${locale.toUpperCase()}`];
        if (label && nextText) label.textContent = nextText;
        if (spinner) spinner.hidden = false;
        if (arrow) arrow.hidden = true;
      });
      if (statusLabel) {
        statusLabel.textContent = submitButton?.dataset[`loadingLabel${locale.toUpperCase()}`] || (locale === "fr" ? "Préparation…" : "Preparing…");
      }
    });

    updateCounter();

    const firstInvalid = form.querySelector('[aria-invalid="true"]');
    if (firstInvalid) firstInvalid.focus();
    else document.querySelector(".form-alert")?.focus();
  }

  const downloadButtons = [...document.querySelectorAll("[data-download]")];
  const sourceTitle = document.querySelector(".source-name")?.textContent?.trim() || "rapport";
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
