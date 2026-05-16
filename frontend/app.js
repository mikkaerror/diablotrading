import { enrichRow } from "./modules/dataProcessor.js";
import {
  getFilteredRows,
  initializeState,
  setLatestArtifacts,
  setSelectedDistrict,
  setSelectedTicker,
  state,
} from "./modules/state.js";
import { sampleData } from "./modules/sampleData.js";
import { ui } from "./modules/ui/dom.js";
import {
  bindControlEvents,
  copyExecutionTicket,
  hydratePersistedControls,
  populateFilters,
  refreshBackendStatus,
  renderOAuthGuide,
  setSheetStatus,
  startBackendHeartbeat,
  updateApprovalStatus,
  updateSyncLabel,
  resetApprovalQueue,
} from "./modules/ui/sheetControls.js";
import { renderOverview, renderCampaignBoard, renderSignalRibbon, renderTownBoard } from "./modules/ui/landscapes.js";
import { renderAccumulationDesk, renderConvictionEngine, renderExecutionDesk, renderMorningBrief, renderOpsWatch } from "./modules/ui/desks.js";
import { renderDetail, renderRoster, renderShortlist } from "./modules/ui/detail.js";

initializeState({
  sampleRows: sampleData.map(enrichRow),
});

function selectTicker(ticker) {
  setSelectedTicker(ticker);
  renderDashboard();
}

function selectDistrict(district) {
  setSelectedDistrict(district);
  renderDashboard();
}

async function handleApprovalStatus(ticker, status) {
  await updateApprovalStatus(ticker, status);
  await refreshBackendStatus();
  renderDashboard();
}

async function handleApprovalReset() {
  await resetApprovalQueue();
  await refreshBackendStatus();
  renderDashboard();
}

async function handleExecutionTicket(item) {
  await copyExecutionTicket(ui, item);
}

function ensureSelection(rows) {
  if (!rows.length) {
    if (state.selectedTicker !== null) {
      setSelectedTicker(null);
    }
    return;
  }

  if (!state.selectedTicker || !rows.some((row) => row.ticker === state.selectedTicker)) {
    setSelectedTicker(rows[0].ticker);
  }
}

function renderDashboard() {
  const rows = getFilteredRows();
  ensureSelection(rows);
  updateSyncLabel(ui, state.sourceLabel);
  renderOverview({ ui, rows });
  renderOpsWatch({ ui, backendState: state.backend });
  renderCampaignBoard({
    ui,
    rows,
    backendState: state.backend,
    onSelectTicker: selectTicker,
  });
  renderTownBoard({
    ui,
    rows,
    backendState: state.backend,
    selectedDistrict: state.selectedDistrict,
    onSelectTicker: selectTicker,
    onSelectDistrict: selectDistrict,
  });
  renderSignalRibbon({ ui, rows, onSelectTicker: selectTicker });
  renderConvictionEngine({ ui, rows });
  renderAccumulationDesk({ ui, rows, onSelectTicker: selectTicker });
  renderExecutionDesk({
    ui,
    backendState: state.backend,
    onUpdateApprovalStatus: handleApprovalStatus,
    onResetApprovalQueue: handleApprovalReset,
    onCopyExecutionTicket: handleExecutionTicket,
  });
  setLatestArtifacts(renderMorningBrief({ ui, rows, backendState: state.backend }));
  renderRoster({ ui, rows, selectedTicker: state.selectedTicker, onSelectTicker: selectTicker });
  renderDetail({ ui, rows, selectedTicker: state.selectedTicker });
  renderShortlist({ ui, rows, onSelectTicker: selectTicker });
}

hydratePersistedControls(ui);
populateFilters(ui);
setSelectedTicker(getFilteredRows()[0]?.ticker ?? null);
renderOAuthGuide(ui);
setSheetStatus(ui, "Using sample cache until Google authorization succeeds.", "muted");

bindControlEvents({
  ui,
  render: renderDashboard,
});

refreshBackendStatus().finally(() => {
  renderDashboard();
});

startBackendHeartbeat(async () => {
  renderDashboard();
});
