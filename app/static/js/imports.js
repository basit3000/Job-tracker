"use strict";

const importSource = document.getElementById("source");
if (importSource) {
  const importMode = document.getElementById("import_mode");
  const readButton = document.getElementById("read-source");
  const updateSource = () => {
    const canSync = ["google", "notion"].includes(importSource.value);
    const syncing = canSync && importMode?.value === "sync";
    for (const section of document.querySelectorAll("[data-import-source]")) {
      section.hidden = !section.dataset.importSource.split(" ").includes(importSource.value)
        || (section.dataset.importMode === "sync" && !syncing);
      for (const field of section.querySelectorAll("input, select, textarea")) {
        field.disabled = section.hidden;
      }
    }
    const connectionName = document.getElementById("name");
    if (connectionName) connectionName.required = syncing;
    if (readButton) readButton.textContent = syncing ? "Connect and review" : "Read source";
  };
  importSource.addEventListener("change", updateSource);
  importMode?.addEventListener("change", updateSource);
  updateSource();
}
