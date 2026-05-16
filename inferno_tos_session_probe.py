from __future__ import annotations

"""Live thinkorswim session probe for the Inferno export pipeline.

This module reads macOS accessibility state without clicking or typing. Its job
is to verify that the real thinkorswim trading window is present, identify the
active Java process name, and summarize the current visible workspace so export
automation can stay guarded and evidence-driven.
"""

import argparse
import json
import re
import subprocess
from typing import Any

from inferno_config import (
    TOS_MAIN_WINDOW_TOKEN,
    TOS_PROCESS_CANDIDATES,
    TOS_SAFE_AUTOMATION_PANELS,
    TOS_UNSAFE_AUTOMATION_PANELS,
    local_now,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


SESSION_PROBE_FILE = DATA_DIR / "inferno_tos_session_probe.json"
SESSION_PROBE_TEXT_FILE = REPORTS_DIR / "tos_session_probe_latest.txt"


def text(value: Any) -> str:
    """Normalize arbitrary values into trimmed text."""
    return str(value or "").strip()


def owner_matches_tos(owner_name: str) -> bool:
    """Return whether a CoreGraphics owner name belongs to the TOS surface.

    Some builds present the broker window as ``thinkorswim`` while others show
    the Java wrapper process name such as ``java-arm``. Treat both as valid so
    the probe can distinguish "login visible" from "no window visible".
    """
    owner = text(owner_name).strip().lower()
    if not owner:
        return False
    candidate_names = {text(candidate).strip().lower() for candidate in TOS_PROCESS_CANDIDATES if text(candidate)}
    if owner in candidate_names:
        return True
    return "thinkorswim" in owner or owner.startswith("java")


def infer_account_mode(report: dict[str, Any]) -> tuple[str, list[str]]:
    """Infer the visible account mode from accessible labels.

    The probe stays conservative: only an explicit paper-money signal earns a
    `paper` label. Anything that smells like a real account stays `live` or
    `unknown`, which keeps downstream automation from acting brave without
    evidence.
    """
    evidence: list[str] = []
    candidates: list[str] = []

    for name in report.get("windowNames") or []:
        label = text(name)
        if label:
            candidates.append(label)
    for item in report.get("labeledButtons") or []:
        label = text(item.get("label"))
        if label:
            candidates.append(label)
    for item in report.get("currentTabGroups") or []:
        label = text(item.get("label") or item.get("description") or item.get("title") or item.get("value"))
        if label:
            candidates.append(label)
    for item in report.get("keywordMatches") or []:
        label = text(item.get("label") or item.get("description") or item.get("title") or item.get("value"))
        if label:
            candidates.append(label)
    for item in report.get("staticTexts") or []:
        label = text(item.get("label") or item.get("description") or item.get("title") or item.get("value"))
        if label:
            candidates.append(label)

    lowered = [candidate.lower() for candidate in candidates]
    for candidate in candidates:
        if candidate:
            evidence.append(candidate)

    if any("logon to thinkorswim" in candidate for candidate in lowered):
        return "login-only", evidence[:12]
    if any(
        "papermoney" in candidate
        or "paper money" in candidate
        or "paper@thinkorswim" in candidate
        for candidate in lowered
    ):
        return "paper", evidence[:12]
    if any("live trading" in candidate or "real money" in candidate for candidate in lowered):
        return "live", evidence[:12]
    if any(
        re.search(r"\b(statement for account|account:?)\b.*\d{4,}", candidate)
        for candidate in lowered
    ):
        return "live", evidence[:12]
    return "unknown", evidence[:12]


def extract_account_suffix_candidates(report: dict[str, Any]) -> list[str]:
    """Extract plausible 4+ digit account suffixes from visible labels.

    We stay conservative and only consider digit groups that appear near
    account-oriented words. This avoids confusing app build numbers for actual
    account identifiers.
    """
    labels: list[str] = []
    for key in (
        "windowNames",
        "selectedMonitorSubtabs",
        "accountEvidence",
    ):
        for item in report.get(key) or []:
            label = text(item)
            if label:
                labels.append(label)
    for group in ("currentTabGroups", "keywordMatches", "labeledButtons", "labeledCheckboxes", "monitorSubtabs", "staticTexts"):
        for item in report.get(group) or []:
            label = text(item.get("label") or item.get("description") or item.get("title") or item.get("value"))
            if label:
                labels.append(label)

    suffixes: list[str] = []
    for label in labels:
        lowered = label.lower()
        if "account" not in lowered and "acct" not in lowered and "statement" not in lowered:
            continue
        for match in re.findall(r"(?<!\d)(\d{4,})(?!\d)", label):
            if match not in suffixes:
                suffixes.append(match)
    return suffixes[:10]


def run_jxa(script: str) -> subprocess.CompletedProcess[str]:
    """Run a JXA probe script and capture its output."""
    try:
        return subprocess.run(
            ["osascript", "-l", "JavaScript"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            exc.cmd,
            124,
            exc.stdout or "",
            (exc.stderr or "") + "JXA probe timed out",
        )


def run_osascript(script: str) -> subprocess.CompletedProcess[str]:
    """Run plain AppleScript and capture text output."""
    return subprocess.run(
        ["osascript", "-e", script],
        text=True,
        capture_output=True,
        check=False,
    )


def visible_tos_windows() -> list[dict[str, Any]]:
    """Return visible thinkorswim CoreGraphics windows with owning PIDs.

    AppleScript can struggle when macOS keeps multiple same-named thinkorswim
    wrappers alive. CoreGraphics gives us the concrete on-screen window list,
    which lets the probe target the right PID instead of whichever wrapper
    System Events happens to hand back first. Some installations surface the
    window owner as the Java wrapper (for example ``java-arm``), so we accept
    either the branded owner name or the Java wrapper alias.
    """
    swift_script = r"""
import Foundation
import CoreGraphics

let opts: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
let windows = CGWindowListCopyWindowInfo(opts, kCGNullWindowID) as? [[String: Any]] ?? []
for window in windows {
    let owner = window[kCGWindowOwnerName as String] as? String ?? ""
    let normalizedOwner = owner.lowercased()
    if normalizedOwner != "thinkorswim" && !normalizedOwner.hasPrefix("java") {
        continue
    }
    let pid = window[kCGWindowOwnerPID as String] as? Int ?? 0
    let title = window[kCGWindowName as String] as? String ?? ""
    let layer = window[kCGWindowLayer as String] as? Int ?? 0
    print("\(pid)\t\(owner)\t\(title)\t\(layer)")
}
"""
    try:
        result = subprocess.run(
            ["swift", "-e", swift_script],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return []

    if result.returncode != 0 or not result.stdout.strip():
        return []

    windows: list[dict[str, Any]] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        pid_text, owner_name, window_name, layer_text = parts[:4]
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        try:
            layer = int(layer_text)
        except ValueError:
            layer = 0
        windows.append(
            {
                "pid": pid,
                "ownerName": owner_name,
                "windowName": window_name,
                "layer": layer,
            }
        )
    return windows


def applescript_list(expression: str) -> list[str]:
    """Run an AppleScript list expression and normalize it to newline-delimited text."""
    script = f"""
set AppleScript's text item delimiters to linefeed
{expression}
try
  if class of _items is list then
    return _items as text
  end if
  return _items as text
on error
  return ""
end try
"""
    result = run_osascript(script)
    if result.returncode != 0:
        return []
    text_output = result.stdout.replace("\r", "")
    if not text_output:
        return []
    return [line.strip() for line in text_output.rstrip("\n").split("\n")]


def escape_applescript_text(value: str) -> str:
    """Escape a Python string for safe embedding inside AppleScript quotes."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def probe_tos_session_via_applescript() -> dict[str, Any]:
    """Fallback probe that reads the TOS window through fast AppleScript calls.

    This path deliberately avoids deep JXA traversal. We only inspect the live
    window, the first split-group container, and the active Monitor tab group,
    which is enough to recover the account statement header and current panel.
    """
    payload: dict[str, Any] = {
        "frontmostApp": None,
        "matchedProcessName": None,
        "visibleProcessNames": [],
        "windowNames": [],
        "mainWindowPresent": False,
        "splitGroupIndex": None,
        "monitorGroupIndex": None,
        "currentTabGroups": [],
        "currentPanel": None,
        "currentPanelSafety": "unknown",
        "monitorSubpanel": None,
        "selectedMonitorSubtabs": [],
        "monitorSubtabs": [],
        "labeledButtons": [],
        "labeledCheckboxes": [],
        "keywordMatches": [],
        "staticTexts": [],
    }

    payload["visibleProcessNames"] = applescript_list(
        'tell application "System Events" to set _items to name of every application process whose background only is false'
    )
    frontmost = run_osascript(
        'tell application "System Events" to get name of first application process whose frontmost is true'
    )
    payload["frontmostApp"] = text(frontmost.stdout)

    matched_process = None
    process_target = None
    visible_windows = visible_tos_windows()
    preferred_window = next(
        (item for item in visible_windows if TOS_MAIN_WINDOW_TOKEN in text(item.get("windowName"))),
        None,
    )
    if not preferred_window:
        preferred_window = next(
            (
                item for item in visible_windows
                if "logon to thinkorswim" in text(item.get("windowName")).lower()
            ),
            None,
        )
    if not preferred_window and visible_windows:
        preferred_window = visible_windows[0]
    if preferred_window:
        matched_process = text(preferred_window.get("ownerName")) or "thinkorswim"
        process_target = f'first application process whose unix id is {int(preferred_window["pid"])}'
        payload["matchedProcessName"] = matched_process
        payload["windowNames"] = [text(item.get("windowName")) for item in visible_windows if int(item.get("pid") or 0) == int(preferred_window["pid"])]

    frontmost_candidate = payload["frontmostApp"] if payload["frontmostApp"] in TOS_PROCESS_CANDIDATES else None
    if not matched_process and frontmost_candidate:
        frontmost_windows = applescript_list(
            'tell application "System Events" to tell first application process whose frontmost is true to set _items to name of windows'
        )
        if frontmost_windows:
            matched_process = str(frontmost_candidate)
            process_target = 'first application process whose frontmost is true'
            payload["matchedProcessName"] = matched_process
            payload["windowNames"] = frontmost_windows

    if not matched_process:
        for candidate in TOS_PROCESS_CANDIDATES:
            quoted = escape_applescript_text(candidate)
            window_names = applescript_list(
                f'tell application "System Events" to tell application process "{quoted}" to set _items to name of windows'
            )
            if window_names:
                matched_process = candidate
                process_target = f'application process "{quoted}"'
                payload["matchedProcessName"] = candidate
                payload["windowNames"] = window_names
                break

    if not matched_process:
        return payload

    payload["mainWindowPresent"] = any(TOS_MAIN_WINDOW_TOKEN in name for name in payload["windowNames"])

    top_roles = applescript_list(
        f'tell application "System Events" to tell {process_target} to set _items to role of every UI element of window 1'
    )
    if not top_roles:
        return payload

    try:
        split_index = top_roles.index("AXSplitGroup") + 1
    except ValueError:
        return payload
    payload["splitGroupIndex"] = split_index

    child_roles = applescript_list(
        f'tell application "System Events" to tell {process_target} to set _items to role of every UI element of UI element {split_index} of window 1'
    )
    child_descriptions = applescript_list(
        f'tell application "System Events" to tell {process_target} to set _items to description of every UI element of UI element {split_index} of window 1'
    )
    child_values = applescript_list(
        f'tell application "System Events" to tell {process_target} to set _items to value of every UI element of UI element {split_index} of window 1'
    )
    child_count = max(len(child_roles), len(child_descriptions), len(child_values))
    child_summaries: list[dict[str, Any]] = []
    for index in range(child_count):
        role = child_roles[index] if index < len(child_roles) else ""
        description = child_descriptions[index] if index < len(child_descriptions) else ""
        value = child_values[index] if index < len(child_values) else ""
        label = description or value
        child_summaries.append(
            {
                "index": index + 1,
                "role": role,
                "description": description,
                "title": "",
                "value": value,
                "label": label,
                "childCount": 0,
            }
        )

    payload["currentTabGroups"] = [item for item in child_summaries if item.get("role") == "AXTabGroup" and item.get("label")]
    panel_candidates = [item for item in payload["currentTabGroups"] if text(item.get("label")) in (set(TOS_SAFE_AUTOMATION_PANELS) | set(TOS_UNSAFE_AUTOMATION_PANELS))]
    if panel_candidates:
        payload["currentPanel"] = text(panel_candidates[-1].get("label"))
    elif payload["currentTabGroups"]:
        payload["currentPanel"] = text(payload["currentTabGroups"][-1].get("label"))

    if payload["currentPanel"] in TOS_UNSAFE_AUTOMATION_PANELS:
        payload["currentPanelSafety"] = "unsafe"
    elif payload["currentPanel"] in TOS_SAFE_AUTOMATION_PANELS:
        payload["currentPanelSafety"] = "safe"

    if payload["currentPanel"] == "Monitor":
        monitor_candidates = [item for item in child_summaries if item.get("role") == "AXTabGroup" and text(item.get("label")) == "Monitor"]
        if monitor_candidates:
            monitor_index = int(monitor_candidates[-1]["index"])
            payload["monitorGroupIndex"] = monitor_index
            monitor_roles = applescript_list(
                f'tell application "System Events" to tell {process_target} to set _items to role of every UI element of UI element {monitor_index} of UI element {split_index} of window 1'
            )
            monitor_descriptions = applescript_list(
                f'tell application "System Events" to tell {process_target} to set _items to description of every UI element of UI element {monitor_index} of UI element {split_index} of window 1'
            )
            monitor_values = applescript_list(
                f'tell application "System Events" to tell {process_target} to set _items to value of every UI element of UI element {monitor_index} of UI element {split_index} of window 1'
            )
            monitor_count = max(len(monitor_roles), len(monitor_descriptions), len(monitor_values))
            monitor_summaries: list[dict[str, Any]] = []
            for index in range(monitor_count):
                role = monitor_roles[index] if index < len(monitor_roles) else ""
                description = monitor_descriptions[index] if index < len(monitor_descriptions) else ""
                value = monitor_values[index] if index < len(monitor_values) else ""
                label = description or value
                monitor_summaries.append(
                    {
                        "index": index + 1,
                        "role": role,
                        "description": description,
                        "title": "",
                        "value": value,
                        "label": label,
                        "childCount": 0,
                    }
                )
            payload["monitorSubtabs"] = [
                {**item, "selected": bool(text(item.get("value")) and text(item.get("value")) != "0")}
                for item in monitor_summaries
                if item.get("role") == "AXCheckBox" and item.get("label")
            ]
            payload["selectedMonitorSubtabs"] = [
                text(item.get("label")) for item in payload["monitorSubtabs"] if item.get("selected")
            ]
            if payload["selectedMonitorSubtabs"]:
                payload["monitorSubpanel"] = payload["selectedMonitorSubtabs"][0]

            interesting = child_summaries + monitor_summaries
            payload["labeledButtons"] = [
                item for item in interesting if item.get("role") == "AXButton" and text(item.get("label"))
            ][:25]
            payload["labeledCheckboxes"] = [
                item for item in interesting if item.get("role") == "AXCheckBox" and text(item.get("label"))
            ][:25]
            payload["staticTexts"] = [
                item for item in interesting if item.get("role") == "AXStaticText" and text(item.get("label"))
            ][:60]
            payload["keywordMatches"] = [
                item
                for item in interesting
                if any(
                    keyword in f"{text(item.get('role'))} {text(item.get('description'))} {text(item.get('value'))}".lower()
                    for keyword in ("monitor", "statement", "export", "order", "market", "account")
                )
            ][:80]

    if not payload["staticTexts"]:
        payload["staticTexts"] = [item for item in child_summaries if item.get("role") == "AXStaticText" and text(item.get("label"))][:40]
    if not payload["keywordMatches"]:
        payload["keywordMatches"] = [
            item
            for item in child_summaries
            if any(
                keyword in f"{text(item.get('role'))} {text(item.get('description'))} {text(item.get('value'))}".lower()
                for keyword in ("monitor", "statement", "export", "order", "market", "account")
            )
        ][:40]

    return payload


def build_probe_script() -> str:
    """Build the non-destructive JXA script that inspects the TOS session."""
    process_candidates_json = json.dumps(list(TOS_PROCESS_CANDIDATES))
    main_window_token_json = json.dumps(TOS_MAIN_WINDOW_TOKEN)
    return f"""
const processCandidates = {process_candidates_json};
const mainWindowToken = {main_window_token_json};
const safePanels = {json.dumps(list(TOS_SAFE_AUTOMATION_PANELS))};
const unsafePanels = {json.dumps(list(TOS_UNSAFE_AUTOMATION_PANELS))};

function safe(fn, fallback = null) {{
  try {{
    return fn();
  }} catch (error) {{
    return fallback;
  }}
}}

function pickInteresting(items, limit, roles) {{
  return items
    .filter((item) => roles.includes(item.role) && item.label)
    .slice(0, limit);
}}

function elementLabel(element) {{
  const title = String(safe(() => element.title(), '') || '');
  const description = String(safe(() => element.description(), '') || '');
  const value = String(safe(() => element.value(), '') || '');
  return {{ title, description, value, label: title || description || value }};
}}

function summarizeElement(element, indexPath, depth) {{
  const role = String(safe(() => element.role(), '') || '');
  const labels = elementLabel(element);
  const childCount = safe(() => element.uiElements().length, 0) || 0;
  return {{
    index: indexPath,
    depth,
    role,
    title: labels.title,
    description: labels.description,
    value: labels.value,
    label: labels.label,
    childCount,
    ...frameSummary(element),
  }};
}}

function frameSummary(element) {{
  const position = safe(() => element.position(), null);
  const size = safe(() => element.size(), null);
  const x = position && position.length >= 2 ? Number(position[0]) : null;
  const y = position && position.length >= 2 ? Number(position[1]) : null;
  const width = size && size.length >= 2 ? Number(size[0]) : null;
  const height = size && size.length >= 2 ? Number(size[1]) : null;
  const center =
    x !== null && y !== null && width !== null && height !== null
      ? [Math.round(x + width / 2), Math.round(y + height / 2)]
      : null;
  return {{ x, y, width, height, center }};
}}

const se = Application('System Events');
const result = {{
  frontmostApp: null,
  processCandidates,
  matchedProcessName: null,
  visibleProcessNames: [],
  windowNames: [],
  mainWindowPresent: false,
  splitGroupIndex: null,
  monitorGroupIndex: null,
  currentTabGroups: [],
  currentPanel: null,
  currentPanelSafety: 'unknown',
  monitorSubpanel: null,
  selectedMonitorSubtabs: [],
  monitorSubtabs: [],
  labeledButtons: [],
  labeledCheckboxes: [],
  keywordMatches: [],
}};

const visibleProcesses = safe(() => se.applicationProcesses.whose({{ backgroundOnly: {{ '=': false }} }})(), []);
result.visibleProcessNames = visibleProcesses
  .map((process) => String(safe(() => process.name(), '') || ''))
  .filter(Boolean);

const frontmost = safe(() => se.applicationProcesses.whose({{ frontmost: {{ '=': true }} }})()[0], null);
if (frontmost) {{
  result.frontmostApp = String(safe(() => frontmost.name(), '') || '');
}}

let matchedProcess = null;
for (const candidate of processCandidates) {{
  try {{
    const process = se.applicationProcesses.byName(candidate);
    const windows = safe(() => process.windows(), []);
    if (windows && windows.length) {{
      matchedProcess = process;
      result.matchedProcessName = candidate;
      result.windowNames = windows.map((window) => String(safe(() => window.name(), '') || '')).filter(Boolean);
      break;
    }}
  }} catch (error) {{
    // Ignore missing process candidates and keep searching.
  }}
}}

result.mainWindowPresent = result.windowNames.some((windowName) => windowName.includes(mainWindowToken));

if (matchedProcess) {{
  const firstWindow = safe(() => matchedProcess.windows()[0], null);
  const topLevelElements = firstWindow ? safe(() => firstWindow.uiElements(), []) : [];
  const splitGroup = topLevelElements.find((element) => safe(() => element.role(), '') === 'AXSplitGroup');
  result.splitGroupIndex = splitGroup ? topLevelElements.indexOf(splitGroup) + 1 : null;
  const splitChildren = splitGroup ? safe(() => splitGroup.uiElements(), []) : [];

  const childSummaries = splitChildren.map((element, index) => {{
    const role = String(safe(() => element.role(), '') || '');
    const title = String(safe(() => element.title(), '') || '');
    const description = String(safe(() => element.description(), '') || '');
    const value = String(safe(() => element.value(), '') || '');
    const label = title || description || value;
    const childCount = safe(() => element.uiElements().length, 0) || 0;
    return {{ index: index + 1, role, title, description, value, label, childCount, ...frameSummary(element) }};
  }});

  result.currentTabGroups = childSummaries.filter((item) => item.role === 'AXTabGroup' && (item.label || item.childCount));
  if (result.currentTabGroups.length) {{
    const primaryPanel = result.currentTabGroups.reduce((best, item) => {{
      if (!best) return item;
      return (item.childCount || 0) > (best.childCount || 0) ? item : best;
    }}, null);
    result.currentPanel = primaryPanel ? primaryPanel.label : null;
    if (result.currentPanel && unsafePanels.includes(result.currentPanel)) {{
      result.currentPanelSafety = 'unsafe';
    }} else if (result.currentPanel && safePanels.includes(result.currentPanel)) {{
      result.currentPanelSafety = 'safe';
    }}

    if (primaryPanel && result.currentPanel === 'Monitor') {{
      result.monitorGroupIndex = primaryPanel.index || null;
      const primaryElement = splitChildren[(primaryPanel.index || 1) - 1];
      const primaryChildren = primaryElement ? safe(() => primaryElement.uiElements(), []) : [];
      const primaryChildSummaries = primaryChildren.map((element, index) =>
        summarizeElement(element, 'monitor.' + String(index + 1), 2)
      );
      const monitorSubtabs = primaryChildren
        .map((element, index) => {{
          const role = String(safe(() => element.role(), '') || '');
          const description = String(safe(() => element.description(), '') || '');
          const title = String(safe(() => element.title(), '') || '');
          const value = String(safe(() => element.value(), '') || '');
          const label = title || description || value;
          const selected = Boolean(value && value !== '0');
          return {{ index: index + 1, role, description, title, value, label, selected, ...frameSummary(element) }};
        }})
        .filter((item) => item.role === 'AXCheckBox' && item.label);
      result.monitorSubtabs = monitorSubtabs;
      result.selectedMonitorSubtabs = monitorSubtabs.filter((item) => item.selected).map((item) => item.label);
      const selectedSubtab = monitorSubtabs.find((item) => item.selected);
      result.monitorSubpanel = selectedSubtab ? selectedSubtab.label : null;
      const interestingSummaries = childSummaries.concat(primaryChildSummaries);
      result.labeledButtons = pickInteresting(interestingSummaries, 25, ['AXButton']);
      result.labeledCheckboxes = pickInteresting(interestingSummaries, 25, ['AXCheckBox']);
      result.staticTexts = pickInteresting(interestingSummaries, 60, ['AXStaticText']);
      result.keywordMatches = interestingSummaries.filter((item) => {{
        const blob = `${{item.role}} ${{item.title}} ${{item.description}} ${{item.value}}`.toLowerCase();
        return (
          blob.includes('monitor') ||
          blob.includes('statement') ||
          blob.includes('export') ||
          blob.includes('order') ||
          blob.includes('market') ||
          blob.includes('account')
        );
      }}).slice(0, 80);
    }}
  }}
  if (!result.labeledButtons.length && !result.labeledCheckboxes.length && !result.staticTexts.length) {{
    result.labeledButtons = pickInteresting(childSummaries, 25, ['AXButton']);
    result.labeledCheckboxes = pickInteresting(childSummaries, 25, ['AXCheckBox']);
    result.staticTexts = pickInteresting(childSummaries, 40, ['AXStaticText']);
    result.keywordMatches = childSummaries.filter((item) => {{
      const blob = `${{item.role}} ${{item.title}} ${{item.description}} ${{item.value}}`.toLowerCase();
      return blob.includes('monitor') || blob.includes('statement') || blob.includes('export') || blob.includes('order') || blob.includes('market');
    }});
  }}
}}

console.log(JSON.stringify(result));
"""


def summarize_session(report: dict[str, Any]) -> str:
    """Generate a short operator-facing session summary."""
    if not report.get("ok"):
        return "probe failed"
    if not report.get("matchedProcessName"):
        return "no visible thinkorswim window detected"
    account_mode = text(report.get("accountMode") or "unknown")
    account_suffix = f" | account {account_mode}" if account_mode and account_mode != "unknown" else ""
    if report.get("mainWindowPresent"):
        panel_label = text(report.get("currentPanel"))
        if panel_label:
            subpanel_label = text(report.get("monitorSubpanel"))
            if panel_label == "Monitor" and subpanel_label:
                return (
                    f"main window live via {report['matchedProcessName']} | "
                    f"current panel {panel_label}/{subpanel_label} | "
                    f"safety {report.get('currentPanelSafety')}{account_suffix}"
                )
            return (
                f"main window live via {report['matchedProcessName']} | "
                f"current panel {panel_label} | safety {report.get('currentPanelSafety')}{account_suffix}"
            )
        current_tabs = report.get("currentTabGroups") or []
        if current_tabs:
            # Prefer the largest tab group because it tends to represent the
            # main workspace pane, not the smaller order-entry strip.
            first_tab = max(current_tabs, key=lambda item: int(item.get("childCount") or 0))
            tab_label = text(first_tab.get("description") or first_tab.get("title") or first_tab.get("value"))
            if tab_label:
                return f"main window live via {report['matchedProcessName']} | current panel {tab_label}{account_suffix}"
        return f"main window live via {report['matchedProcessName']}{account_suffix}"
    window_names = [text(name) for name in report.get("windowNames") or [] if text(name)]
    if any("logon to thinkorswim" in name.lower() for name in window_names):
        return "thinkorswim login window is visible; the main trading workspace is not open yet"
    return f"{report['matchedProcessName']} is running but the main window token is missing"


def probe_tos_session() -> dict[str, Any]:
    """Probe the live thinkorswim session and persist a structured report."""
    ensure_dirs()
    report: dict[str, Any] = {
        "generatedAt": local_now().isoformat(),
        "ok": False,
        "processCandidates": list(TOS_PROCESS_CANDIDATES),
        "mainWindowToken": TOS_MAIN_WINDOW_TOKEN,
        "frontmostApp": None,
        "matchedProcessName": None,
        "visibleProcessNames": [],
        "windowNames": [],
        "mainWindowPresent": False,
        "splitGroupIndex": None,
        "monitorGroupIndex": None,
        "currentTabGroups": [],
        "currentPanel": None,
        "currentPanelSafety": "unknown",
        "monitorSubpanel": None,
        "selectedMonitorSubtabs": [],
        "monitorSubtabs": [],
        "labeledButtons": [],
        "labeledCheckboxes": [],
        "keywordMatches": [],
        "staticTexts": [],
        "accountMode": "unknown",
        "accountEvidence": [],
        "accountSuffixCandidates": [],
        "summary": None,
        "message": None,
    }

    result = run_jxa(build_probe_script())
    report["stdout"] = text(result.stdout)
    report["stderr"] = text(result.stderr)
    report["returncode"] = result.returncode
    payload: dict[str, Any] | None = None
    if result.returncode == 0:
        payload_text = result.stdout.strip() or result.stderr.strip() or "{}"
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            report["message"] = f"probe returned invalid JSON: {exc}"
    else:
        report["message"] = report["stderr"] or "JXA probe failed"

    if payload is None:
        fallback_payload = probe_tos_session_via_applescript()
        if fallback_payload.get("matchedProcessName") or fallback_payload.get("visibleProcessNames"):
            payload = fallback_payload
            report["fallbackProbe"] = "applescript"
            report["message"] = None
        else:
            save_session_probe(report)
            return report

    report.update(payload)
    window_names_lower = [text(name).lower() for name in report.get("windowNames") or [] if text(name)]
    if not report.get("mainWindowPresent"):
        # Some paperMoney builds expose `Paper@thinkorswim [build ...]` instead
        # of the historic `Main@thinkorswim` token. Treat that as a visible
        # workspace, but keep account-mode checks separate so live sessions
        # still fail closed downstream.
        if any("paper@thinkorswim" in name for name in window_names_lower):
            report["mainWindowPresent"] = True
        elif report.get("matchedProcessName") and report.get("currentPanel") and not any(
            "logon to thinkorswim" in name for name in window_names_lower
        ):
            report["mainWindowPresent"] = True
    report["ok"] = True
    report["accountMode"], report["accountEvidence"] = infer_account_mode(report)
    report["accountSuffixCandidates"] = extract_account_suffix_candidates(report)
    report["summary"] = summarize_session(report)
    if not report.get("message"):
        report["message"] = report["summary"]
    save_session_probe(report)
    return report


def session_probe_text(report: dict[str, Any]) -> str:
    """Render the latest session probe report into plain text."""
    lines = [
        "Inferno thinkorswim Session Probe",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Probe ok: {report.get('ok')}",
        f"Message: {report.get('message')}",
        f"Summary: {report.get('summary')}",
        f"Frontmost app: {report.get('frontmostApp')}",
        f"Matched process: {report.get('matchedProcessName')}",
        f"Main window present: {report.get('mainWindowPresent')}",
        f"Window token: {report.get('mainWindowToken')}",
        f"Current panel: {report.get('currentPanel')}",
        f"Panel safety: {report.get('currentPanelSafety')}",
        f"Account mode: {report.get('accountMode')}",
    ]
    if report.get("accountEvidence"):
        lines.append(f"Account evidence: {' | '.join(report.get('accountEvidence') or [])}")
    if report.get("accountSuffixCandidates"):
        lines.append(f"Account suffix candidates: {', '.join(report.get('accountSuffixCandidates') or [])}")
    if report.get("monitorSubpanel"):
        lines.append(f"Monitor subpanel: {report.get('monitorSubpanel')}")
    if report.get("selectedMonitorSubtabs"):
        lines.append(f"Selected Monitor subtabs: {', '.join(report.get('selectedMonitorSubtabs') or [])}")
    if report.get("windowNames"):
        lines.append(f"Windows: {' | '.join(report.get('windowNames') or [])}")
    if report.get("currentTabGroups"):
        lines.append("Tab groups:")
        for item in report.get("currentTabGroups") or []:
            label = text(item.get("description") or item.get("title") or item.get("value"))
            lines.append(f"- #{item.get('index')} {label or '(unnamed)'} | children={item.get('childCount')}")
    if report.get("keywordMatches"):
        lines.append("Keyword matches:")
        for item in (report.get("keywordMatches") or [])[:12]:
            label = text(item.get("title") or item.get("description") or item.get("value"))
            lines.append(f"- #{item.get('index')} {item.get('role')} | {label or '(unnamed)'}")
    if report.get("labeledButtons"):
        lines.append("Buttons:")
        for item in (report.get("labeledButtons") or [])[:12]:
            lines.append(f"- #{item.get('index')} {text(item.get('label'))}")
    return "\n".join(lines).rstrip() + "\n"


def save_session_probe(report: dict[str, Any]) -> None:
    """Persist the latest session probe JSON and text reports."""
    ensure_dirs()
    SESSION_PROBE_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    SESSION_PROBE_TEXT_FILE.write_text(session_probe_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the session probe."""
    parser = argparse.ArgumentParser(description="Inspect the live thinkorswim session without clicking.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    """Run or print the latest thinkorswim session probe."""
    args = parse_args()
    if args.command == "status" and SESSION_PROBE_TEXT_FILE.exists():
        print(SESSION_PROBE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = probe_tos_session()
    print(session_probe_text(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
