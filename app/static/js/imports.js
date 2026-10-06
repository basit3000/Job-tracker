"use strict";

const importSource = document.getElementById("source");
if (importSource) {
  const updateSource = () => {
    for (const section of document.querySelectorAll("[data-import-source]")) {
      section.hidden = !section.dataset.importSource.split(" ").includes(importSource.value);
    }
  };
  importSource.addEventListener("change", updateSource);
  updateSource();
}
