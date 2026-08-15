(function () {
  "use strict";

  const runDataElement = document.getElementById("run-data");
  const runs = JSON.parse(runDataElement.textContent);
  const errorStateValues = new Set(["error", "errored", "failed", "failure"]);

  function runIdFromHash() {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const candidate = params.get("run");
    if (candidate && runs.some((run) => run.id === candidate)) {
      return candidate;
    }
    return null;
  }

  const state = {
    stateFilter: "ALL",
    resultFilter: "ALL",
    selectedRunId: runIdFromHash() || (runs[0] ? runs[0].id : null),
  };

  const selectors = {
    runList: document.getElementById("run-list"),
    summaryTotal: document.getElementById("summary-total"),
    summaryCompleted: document.getElementById("summary-completed"),
    summaryMismatches: document.getElementById("summary-mismatches"),
    summaryErrors: document.getElementById("summary-errors"),
    detailTitle: document.getElementById("detail-title"),
    detailStatus: document.getElementById("detail-status"),
    metricStatus: document.getElementById("metric-status"),
    metricDuration: document.getElementById("metric-duration"),
    metricSteps: document.getElementById("metric-steps"),
    metricObservations: document.getElementById("metric-observations"),
    metricError: document.getElementById("metric-error"),
    metricCost: document.getElementById("metric-cost"),
    errorSeverity: document.getElementById("error-severity"),
    errorSummary: document.getElementById("error-summary"),
    timeline: document.getElementById("timeline"),
    evaluationResult: document.getElementById("evaluation-result"),
    evaluationDelta: document.getElementById("evaluation-delta"),
  };

  function resultFor(run) {
    if (run.evaluation && run.evaluation.result) {
      return run.evaluation.result;
    }
    return "PENDING";
  }

  function erroredStepsFor(run) {
    return erroredStepSummariesFor(run).map((summary) => summary.stepId);
  }

  function stepNameFor(run, stepId) {
    const step = run.steps.find((candidate) => candidate.id === stepId);
    return step ? step.name : stepId;
  }

  function erroredStepSummariesFor(run) {
    const errored = new Map();
    run.observations.forEach((observation) => {
      Object.entries(observation.observedState || {}).forEach(([key, value]) => {
        const keyToken = String(key).toLowerCase();
        const valueToken = String(value).trim().toLowerCase();
        if (
          observation.stepId &&
          (keyToken.includes("status") || keyToken.includes("result")) &&
          errorStateValues.has(valueToken)
        ) {
          errored.set(observation.stepId, {
            stepId: observation.stepId,
            stepName: stepNameFor(run, observation.stepId),
            fact: observation.fact,
            field: key,
            value: value,
          });
        }
      });
    });
    return Array.from(errored.values()).sort((left, right) => {
      return left.stepId.localeCompare(right.stepId);
    });
  }

  function errorSignalFor(run) {
    const erroredSteps = erroredStepsFor(run);
    if (erroredSteps.length) {
      return {
        label:
          erroredSteps.length === 1
            ? "1 step error"
            : `${erroredSteps.length} step errors`,
        severity: "error",
      };
    }
    if (resultFor(run) === "MISMATCH") {
      return {
        label: "Evaluation mismatch",
        severity: "warning",
      };
    }
    return {
      label: "None",
      severity: "clear",
    };
  }

  function runStateFor(run) {
    if (run.status === "RUNNING") {
      return "RUNNING";
    }
    if (errorSignalFor(run).severity !== "clear") {
      return "FAILED";
    }
    return "SUCCESS";
  }

  function severityForRunState(runState) {
    if (runState === "FAILED") {
      return "error";
    }
    if (runState === "RUNNING") {
      return "warning";
    }
    return "clear";
  }

  function evaluationIssuesFor(run) {
    if (!run.evaluation || resultFor(run) !== "MISMATCH") {
      return [];
    }
    const issues = [];
    run.evaluation.mismatched.forEach((value) => {
      issues.push(
        `${value.key}: expected ${value.expected}, observed ${value.observed}`,
      );
    });
    run.evaluation.missing.forEach((value) => {
      issues.push(`${value}: missing from observed state`);
    });
    run.evaluation.unexpected.forEach((value) => {
      issues.push(`${value}: unexpected observed state`);
    });
    return issues;
  }

  function filteredRuns() {
    return runs.filter((run) => {
      const stateMatches =
        state.stateFilter === "ALL" || runStateFor(run) === state.stateFilter;
      const resultMatches =
        state.resultFilter === "ALL" || resultFor(run) === state.resultFilter;
      return stateMatches && resultMatches;
    });
  }

  function formatDuration(ms) {
    if (typeof ms !== "number") {
      return "--";
    }
    const seconds = Math.round(ms / 1000);
    if (seconds < 60) {
      return `${seconds}s`;
    }
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    return `${minutes}m ${remainder}s`;
  }

  function formatEstimatedCost(value) {
    if (value === null || value === undefined || value === "") {
      return "--";
    }
    const numericValue = Number(value);
    if (Number.isFinite(numericValue)) {
      return `$${numericValue.toFixed(2)}`;
    }
    return `$${value}`;
  }

  function setBadge(element, value) {
    element.textContent = value;
    element.className = "status-badge";
    if (value === "COMPLETED") {
      element.classList.add("is-completed");
    }
    if (value === "SUCCESS" || value === "OBSERVED") {
      element.classList.add("is-match");
    }
    if (value === "MATCH") {
      element.classList.add("is-match");
    }
    if (value === "MISMATCH") {
      element.classList.add("is-mismatch");
    }
    if (value === "ERROR" || value === "FAILED") {
      element.classList.add("is-error");
    }
    if (value === "RUNNING" || value === "PENDING" || value === "ATTENTION") {
      element.classList.add("is-running");
    }
  }

  function setSignalClass(element, severity) {
    element.className = "run-row-value";
    if (severity === "error") {
      element.classList.add("is-error");
    }
    if (severity === "warning") {
      element.classList.add("is-warning");
    }
    if (severity === "clear") {
      element.classList.add("is-clear");
    }
  }

  function renderSummary() {
    selectors.summaryTotal.textContent = String(runs.length);
    selectors.summaryCompleted.textContent = String(
      runs.filter((run) => run.status === "COMPLETED").length,
    );
    selectors.summaryMismatches.textContent = String(
      runs.filter((run) => resultFor(run) === "MISMATCH").length,
    );
    selectors.summaryErrors.textContent = String(
      runs.filter((run) => errorSignalFor(run).severity !== "clear").length,
    );
  }

  function syncHash(runId) {
    const targetHash = `#run=${encodeURIComponent(runId)}`;
    if (window.location.hash !== targetHash) {
      window.history.pushState(null, "", targetHash);
    }
  }

  function selectRun(runId, updateHash) {
    state.selectedRunId = runId;
    if (updateHash && runId) {
      syncHash(runId);
    }
  }

  function runMetric(label, value, severity) {
    const container = document.createElement("div");
    container.className = "run-row-metric";

    const labelElement = document.createElement("span");
    labelElement.className = "run-row-label";
    labelElement.textContent = label;

    const valueElement = document.createElement("span");
    setSignalClass(valueElement, severity);
    valueElement.textContent = value;

    container.append(labelElement, valueElement);
    return container;
  }

  function setMetricValue(element, value, severity) {
    element.textContent = value;
    element.className = "";
    if (severity === "error") {
      element.classList.add("is-error");
    }
    if (severity === "warning") {
      element.classList.add("is-warning");
    }
    if (severity === "clear") {
      element.classList.add("is-clear");
    }
  }

  function runCard(run) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "run-card";
    button.setAttribute("aria-current", String(run.id === state.selectedRunId));
    button.addEventListener("click", () => {
      selectRun(run.id, true);
      render();
    });

    const header = document.createElement("div");
    header.className = "run-card-header";

    const title = document.createElement("p");
    title.className = "run-card-title";
    title.textContent = run.id;

    const route = document.createElement("span");
    route.className = "run-route";
    route.textContent = `#run=${run.id}`;

    const row = document.createElement("dl");
    row.className = "run-row-grid";
    const errorSignal = errorSignalFor(run);
    const runState = runStateFor(run);
    row.append(
      runMetric("State", runState, severityForRunState(runState)),
      runMetric("Duration", formatDuration(run.metadata.durationMs), ""),
      runMetric("Steps", String(run.steps.length), ""),
      runMetric("Error", errorSignal.label, errorSignal.severity),
    );

    header.append(title, route);
    button.append(header, row);
    return button;
  }

  function renderRunList() {
    const visibleRuns = filteredRuns();
    selectors.runList.replaceChildren();
    if (!visibleRuns.some((run) => run.id === state.selectedRunId)) {
      selectRun(visibleRuns[0] ? visibleRuns[0].id : null, true);
    }
    if (!visibleRuns.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "No runs match the active filters.";
      selectors.runList.append(empty);
      return;
    }
    visibleRuns.forEach((run) => {
      selectors.runList.append(runCard(run));
    });
  }

  function observationFor(run, stepId) {
    return run.observations.find((observation) => {
      return observation.stepId === stepId;
    });
  }

  function observedStateSummary(observation) {
    return Object.entries(observation.observedState || {})
      .map(([key, value]) => `${key}=${value}`)
      .join(", ");
  }

  function renderTimeline(run) {
    selectors.timeline.replaceChildren();
    const stepErrors = new Map(
      erroredStepSummariesFor(run).map((stepError) => {
        return [stepError.stepId, stepError];
      }),
    );
    run.steps.forEach((step, index) => {
      const item = document.createElement("li");
      item.className = "timeline-step";

      const marker = document.createElement("span");
      marker.className = "timeline-index";
      marker.textContent = String(index + 1);

      const body = document.createElement("div");
      body.className = "timeline-body";

      const heading = document.createElement("div");
      heading.className = "timeline-step-header";

      const title = document.createElement("h4");
      title.textContent = step.name;

      const observation = observationFor(run, step.id);
      const stepError = stepErrors.get(step.id);
      const stepState = stepError ? "FAILED" : observation ? "OBSERVED" : "PENDING";

      const status = document.createElement("span");
      status.className = "status-badge";
      setBadge(status, stepState);
      heading.append(title, status);

      const detail = document.createElement("p");
      detail.textContent = observation
        ? observation.fact
        : "Observation pending for this step.";

      const events = document.createElement("ul");
      events.className = "timeline-events";
      step.events.forEach((event) => {
        const eventItem = document.createElement("li");
        eventItem.textContent = event;
        events.append(eventItem);
      });

      body.append(heading, detail, events);
      if (observation) {
        const observedState = document.createElement("p");
        observedState.className = "timeline-state";
        observedState.textContent = `Observed: ${observedStateSummary(
          observation,
        )}`;
        body.append(observedState);
      }
      if (stepError) {
        const errorDetail = document.createElement("p");
        errorDetail.className = "timeline-error";
        errorDetail.textContent = `Failure signal: ${stepError.field} reported ${stepError.value}`;
        body.append(errorDetail);
      }
      item.append(marker, body);
      selectors.timeline.append(item);
    });
  }

  function listItems(values, formatter) {
    const list = document.createElement("ul");
    if (!values.length) {
      const item = document.createElement("li");
      item.textContent = "None";
      list.append(item);
      return list;
    }
    values.forEach((value) => {
      const item = document.createElement("li");
      item.textContent = formatter(value);
      list.append(item);
    });
    return list;
  }

  function deltaColumn(title, values, formatter) {
    const column = document.createElement("div");
    column.className = "delta-column";
    const heading = document.createElement("h4");
    heading.textContent = title;
    column.append(heading, listItems(values, formatter));
    return column;
  }

  function renderEvaluation(run) {
    selectors.evaluationDelta.replaceChildren();
    if (!run.evaluation) {
      setBadge(selectors.evaluationResult, "PENDING");
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "Evaluation pending until the run is completed.";
      selectors.evaluationDelta.append(empty);
      return;
    }

    setBadge(selectors.evaluationResult, run.evaluation.result);
    selectors.evaluationDelta.append(
      deltaColumn("Matches", run.evaluation.matches, (value) => value),
      deltaColumn("Unexpected", run.evaluation.unexpected, (value) => value),
      deltaColumn("Mismatched", run.evaluation.mismatched, (value) => {
        return `${value.key}: expected ${value.expected}, observed ${value.observed}`;
      }),
    );
  }

  function errorItem(title, detail) {
    const item = document.createElement("li");
    item.className = "error-item";

    const heading = document.createElement("strong");
    heading.textContent = title;

    const body = document.createElement("span");
    body.textContent = detail;

    item.append(heading, body);
    return item;
  }

  function renderErrorSummary(run) {
    selectors.errorSummary.replaceChildren();
    const stepErrors = erroredStepSummariesFor(run);
    const evaluationIssues = evaluationIssuesFor(run);
    const list = document.createElement("ul");
    list.className = "error-list";

    stepErrors.forEach((stepError) => {
      list.append(
        errorItem(
          stepError.stepName,
          `${stepError.field} reported ${stepError.value}: ${stepError.fact}`,
        ),
      );
    });
    if (!stepErrors.length) {
      evaluationIssues.forEach((issue) => {
        list.append(errorItem("Evaluation mismatch", issue));
      });
    }

    if (stepErrors.length) {
      setBadge(selectors.errorSeverity, "ERROR");
    } else if (evaluationIssues.length) {
      setBadge(selectors.errorSeverity, "ATTENTION");
    } else {
      setBadge(selectors.errorSeverity, "CLEAR");
      list.append(errorItem("No errors", "No step errors or mismatches."));
    }
    selectors.errorSummary.append(list);
  }

  function renderDetail() {
    const run = runs.find((candidate) => candidate.id === state.selectedRunId);
    if (!run) {
      selectors.detailTitle.textContent = "No run selected";
      setBadge(selectors.detailStatus, "Idle");
      selectors.metricStatus.textContent = "--";
      selectors.metricDuration.textContent = "--";
      selectors.metricSteps.textContent = "--";
      selectors.metricObservations.textContent = "--";
      selectors.metricError.textContent = "--";
      selectors.metricCost.textContent = "--";
      setBadge(selectors.errorSeverity, "None");
      selectors.errorSummary.replaceChildren();
      selectors.timeline.replaceChildren();
      selectors.evaluationDelta.replaceChildren();
      return;
    }

    selectors.detailTitle.textContent = run.id;
    setBadge(selectors.detailStatus, run.status);
    setMetricValue(
      selectors.metricStatus,
      run.status,
      run.status === "RUNNING" ? "warning" : "clear",
    );
    selectors.metricDuration.textContent = formatDuration(
      run.metadata.durationMs,
    );
    selectors.metricSteps.textContent = String(run.steps.length);
    selectors.metricObservations.textContent = String(run.observations.length);
    setMetricValue(
      selectors.metricError,
      errorSignalFor(run).label,
      errorSignalFor(run).severity,
    );
    selectors.metricCost.textContent = formatEstimatedCost(
      run.metadata.estimatedCostUsd,
    );
    renderErrorSummary(run);
    renderTimeline(run);
    renderEvaluation(run);
  }

  function syncFilters() {
    document.querySelectorAll("[data-state-filter]").forEach((button) => {
      const active = button.dataset.stateFilter === state.stateFilter;
      button.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll("[data-result-filter]").forEach((button) => {
      const active = button.dataset.resultFilter === state.resultFilter;
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function bindFilters() {
    document.querySelectorAll("[data-state-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        state.stateFilter = button.dataset.stateFilter;
        render();
      });
    });
    document.querySelectorAll("[data-result-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        state.resultFilter = button.dataset.resultFilter;
        render();
      });
    });
  }

  function render() {
    syncFilters();
    renderSummary();
    renderRunList();
    renderDetail();
  }

  bindFilters();
  window.addEventListener("hashchange", () => {
    const nextRunId = runIdFromHash();
    if (nextRunId && nextRunId !== state.selectedRunId) {
      selectRun(nextRunId, false);
      render();
    }
  });
  render();
})();
