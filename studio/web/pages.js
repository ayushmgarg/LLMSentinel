/* The two explanatory pages: overview/evidence and how it works.

   They share common.js (helpers, theme, navigation) and need only two live
   things: the measured numbers, and whether the detector on this machine is the
   transformer or the rules-only fallback -- because what the page claims depends
   on which one is running. */

"use strict";

/* Headline numbers come from the evaluation outputs, not from the markup. */
function applyEvidence(evidence) {
  if (!evidence) return;
  const set = (selector, value) => {
    const node = $(selector);
    if (node && value !== undefined && value !== null) node.textContent = Number(value).toFixed(3);
  };
  set("#stat-test-auprc", evidence.test_auprc);
  set("#stat-test-recall", evidence.test_tpr_at_1pct_fpr);
  const recallLabel = $("#stat-test-recall-label");
  if (recallLabel && evidence.test_realised_fpr_at_1pct !== undefined && evidence.test_realised_fpr_at_1pct !== null) {
    const realised = Number(evidence.test_realised_fpr_at_1pct);
    const over = realised > 0.01 ? ", over budget" : "";
    recallLabel.textContent = `test recall at the dev 1%-FPR threshold (realised test FPR ${(realised * 100).toFixed(1)}%${over})`;
  }
  // The seed mean is stored as 0.9515; rounding it to three places would print a
  // different number from the one the docs quote, so show the stored precision.
  const exact = (value) => Number(value).toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  const dev = $("#stat-dev-auprc");
  if (dev && evidence.dev_auprc_mean !== undefined && evidence.dev_auprc_mean !== null) {
    dev.replaceChildren(document.createTextNode(exact(evidence.dev_auprc_mean)));
    if (evidence.dev_auprc_std !== undefined && evidence.dev_auprc_std !== null) {
      dev.append(el("small", { text: ` ± ${exact(evidence.dev_auprc_std)}` }));
    }
  }
}

function applyDetector(detector) {
  const node = $("#detector-note");
  if (!node || !detector) return;
  if (detector.loading) {
    node.textContent = "The detector is still loading on this machine.";
    return;
  }
  if (detector.error) {
    node.textContent = detector.error;
    return;
  }
  node.textContent = detector.transformer_loaded
    ? `Running here now: ${detector.detector}. Flag rule: ${detector.decision_rule || ""}`.trim()
    : "Running here now: the rule engine alone. The transformer checkpoint is not loaded, so this machine "
      + "is using the weaker fallback described above.";
}

async function initPage() {
  try {
    const health = await api("/api/health");
    applyEvidence(health.evidence);
    applyDetector(health.detector);
  } catch (error) {
    const node = $("#detector-note");
    if (node) node.textContent = "The Studio server is not reachable, so the numbers above are the ones last written to the report.";
  }
}

document.addEventListener("DOMContentLoaded", initPage);
