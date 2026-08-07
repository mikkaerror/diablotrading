from __future__ import annotations

import json
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_central_command as central_command


class InfernoCentralCommandTests(unittest.TestCase):
    """Verify the supervisor entrypoint centralizes maintenance and collaboration."""

    def test_build_central_command_combines_maintenance_command_center_and_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            report_file = temp_root / "central_command.json"
            report_text_file = temp_root / "central_command.txt"

            with (
                patch.object(central_command, "CENTRAL_COMMAND_FILE", report_file),
                patch.object(central_command, "CENTRAL_COMMAND_TEXT_FILE", report_text_file),
                patch.object(
                    central_command,
                    "run_maintenance",
                    return_value={"ok": True, "generatedAt": "2026-05-10T15:00:00-06:00"},
                ),
                patch.object(
                    central_command,
                    "build_command_center",
                    return_value={
                        "generatedAt": "2026-05-10T15:00:01-06:00",
                        "headlineMetrics": {
                            "accountTotalCash": 0.0,
                            "depositAmountDollars": 250.0,
                            "depositIntervalDays": 14,
                            "depositNextDate": "2026-05-15",
                            "depositForecast30Days": 500.0,
                            "cashAttributionVerdict": "attribution-incomplete",
                            "cashAttributionLatestDelta": -250.0,
                            "cashAttributionClassification": "cash-decrease-unattributed-without-transaction-ledger",
                            "ticketCapVerdict": "active",
                            "ticketCapMinTarget": 250.0,
                            "ticketCapConstructionMinTarget": 250.0,
                            "ticketCapConstructionHardCap": 500.0,
                            "ticketCapHardCap": 500.0,
                            "ticketCapLiveHardCap": 0.0,
                            "ticketCapCallPosture": "aggressive-defined-risk",
                            "liveSupported": 2,
                            "liveFragile": 1,
                            "paperAutoSelected": 0,
                            "paperApprovalOnly": 1,
                            "paperConstructionWatch": 2,
                            "fastPaperBacklog": 8,
                            "paperRemainingForPromotion": 30,
                        },
                        "nextActions": ["Manual risk review: GDS."],
                        "activeMissions": [{"id": "mission-1"}],
                        "recentNotes": [{"id": "note-1"}],
                    },
                ),
                patch.object(
                    central_command,
                    "doctor_summary",
                    return_value={"ok": True, "verdict": "healthy", "detail": "Desk status: healthy"},
                ),
                patch.object(
                    central_command,
                    "build_schedule_status",
                    return_value={
                        "generatedAt": "2026-05-10T15:00:02-06:00",
                        "entrypoint": "./inferno",
                        "launchAgents": [],
                        "codexAutomations": [],
                    },
                ),
            ):
                payload = central_command.build_central_command(
                    backtest_root=temp_root,
                    sheet_name="Earnings Tracker",
                    cloud_region="us-central1",
                )

            saved = json.loads(report_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["verdict"], "healthy")
            self.assertEqual(saved["controlPlane"]["entrypoint"], "./inferno")
            self.assertIn("sync", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("paper-capture", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("usage", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("preflight", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("oauth", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("action-pulse", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("deposit-plan", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("tracker-taxonomy", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("tracker-role-review", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("tracker-role-policy-packet", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("tracker-role-policy", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("schwab-transactions", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("cash-ledger", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("ticket-cap", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("daily-ops", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("chain-history", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("capital-check", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("strike-cycle", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertIn("approvals", {item["command"] for item in saved["controlPlane"]["commands"]})
            self.assertEqual(saved["modelCommandCenter"]["missionCount"], 1)
            self.assertEqual(saved["modelCommandCenter"]["noteCount"], 1)
            self.assertEqual(saved["recommendedNextMove"], "Manual risk review: GDS.")
            self.assertIn("./inferno status", saved["shortcutCommands"])
            self.assertIn("./inferno paper-capture", saved["shortcutCommands"])
            self.assertIn("./inferno preflight", saved["shortcutCommands"])
            self.assertIn("./inferno usage", saved["shortcutCommands"])
            self.assertIn("./inferno action-pulse", saved["shortcutCommands"])
            self.assertIn("./inferno deposit-plan", saved["shortcutCommands"])
            self.assertIn("./inferno tracker-taxonomy", saved["shortcutCommands"])
            self.assertIn("./inferno tracker-role-review", saved["shortcutCommands"])
            self.assertIn("./inferno tracker-role-policy-packet", saved["shortcutCommands"])
            self.assertIn("./inferno tracker-role-policy", saved["shortcutCommands"])
            self.assertIn("./inferno schwab-transactions", saved["shortcutCommands"])
            self.assertIn("./inferno cash-ledger", saved["shortcutCommands"])
            self.assertIn("./inferno ticket-cap", saved["shortcutCommands"])
            self.assertIn("./inferno approvals", saved["shortcutCommands"])
            report_text = report_text_file.read_text(encoding="utf-8")
            self.assertIn("Supervisor verdict: healthy", report_text)
            self.assertIn("Unified entrypoint: ./inferno", report_text)
            self.assertIn(
                "Deposit plan: $250.00 every 14 day(s) | next 2026-05-15 | 30d $500.00 planned | broker cash $0.00",
                report_text,
            )
            self.assertIn(
                "Cash attribution: attribution-incomplete | latest delta -$250.00 | cash-decrease-unattributed-without-transaction-ledger",
                report_text,
            )
            self.assertIn(
                "Ticket cap policy: active | construction $250.00-$500.00 | paper cap $500.00 | live cap $0.00 | call posture aggressive-defined-risk",
                report_text,
            )
            self.assertIn("Paper construction-watch: 2", report_text)
            self.assertIn("Fast-paper backlog: 8", report_text)

    def test_build_schedule_status_reads_launchagents_and_codex_automations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_agents = root / "LaunchAgents"
            automations = root / "automations"
            launch_agents.mkdir()
            automation_dir = automations / "schwab-oauth-early-warning"
            automation_dir.mkdir(parents=True)
            strategy_dir = automations / "inferno-strategy-shadow-engine-daily"
            strategy_dir.mkdir(parents=True)
            plist_path = launch_agents / "io.diablotrading.inferno-daily-model-refresh.plist"
            with plist_path.open("wb") as handle:
                plistlib.dump(
                    {
                        "ProgramArguments": ["/tmp/inferno_daily_model_refresh_service.sh"],
                        "StartCalendarInterval": [
                            {"Weekday": 1, "Hour": 6, "Minute": 45},
                            {"Weekday": 2, "Hour": 16, "Minute": 20},
                        ],
                    },
                    handle,
                )
            (automation_dir / "automation.toml").write_text(
                '\n'.join(
                    [
                        'id = "schwab-oauth-early-warning"',
                        'kind = "heartbeat"',
                        'name = "Schwab OAuth daily early warning"',
                        'status = "ACTIVE"',
                        'rrule = "FREQ=DAILY;BYHOUR=5;BYMINUTE=45"',
                    ]
                ),
                encoding="utf-8",
            )
            (strategy_dir / "automation.toml").write_text(
                '\n'.join(
                    [
                        'id = "inferno-strategy-shadow-engine-daily"',
                        'kind = "cron"',
                        'name = "Inferno Strategy Shadow Engine Daily"',
                        'status = "ACTIVE"',
                        'rrule = "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=16;BYMINUTE=55"',
                    ]
                ),
                encoding="utf-8",
            )

            with (
                patch.object(central_command, "LAUNCH_AGENTS_DIR", launch_agents),
                patch.object(central_command, "CODEX_AUTOMATIONS_DIR", automations),
                patch.object(
                    central_command,
                    "LAUNCH_AGENT_SCHEDULES",
                    (("io.diablotrading.inferno-daily-model-refresh", "full sync"),),
                ),
                patch.object(central_command, "CODEX_AUTOMATIONS", ("schwab-oauth-early-warning",)),
            ):
                payload = central_command.build_schedule_status()

        self.assertEqual(payload["launchAgents"][0]["status"], "configured")
        self.assertIn("06:45", payload["launchAgents"][0]["schedule"])
        self.assertIn("16:20", payload["launchAgents"][0]["schedule"])
        by_id = {item["id"]: item for item in payload["codexAutomations"]}
        self.assertEqual(by_id["schwab-oauth-early-warning"]["status"], "ACTIVE")
        self.assertEqual(by_id["schwab-oauth-early-warning"]["schedule"], "daily at 05:45")
        self.assertEqual(by_id["inferno-strategy-shadow-engine-daily"]["status"], "ACTIVE")
        self.assertIn("MO,TU,WE,TH,FR", by_id["inferno-strategy-shadow-engine-daily"]["schedule"])
        strategy_audit = by_id["inferno-strategy-shadow-engine-daily"]["promptAudit"]
        self.assertFalse(strategy_audit["ok"])
        self.assertIn("./run_inferno_paper_test_director.sh build", strategy_audit["missing"])

    def test_strategy_shadow_automation_prompt_audit_accepts_paper_sync_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            automations = root / "automations"
            strategy_dir = automations / "inferno-strategy-shadow-engine-daily"
            strategy_dir.mkdir(parents=True)
            prompt = " ".join(
                [
                    "./run_inferno_strategy_alternative_pricing.sh --limit 6 --variants-per-ticker 3",
                    "./run_inferno_strategy_shadow_comparison.sh",
                    "./run_inferno_paper_test_director.sh build",
                    "./run_inferno_paper_blocker_swarm.sh run",
                    "./run_inferno_paper_bottleneck_reducer.sh",
                ]
            )
            (strategy_dir / "automation.toml").write_text(
                '\n'.join(
                    [
                        'id = "inferno-strategy-shadow-engine-daily"',
                        'kind = "cron"',
                        'name = "Inferno Strategy Shadow Engine Daily"',
                        f'prompt = "{prompt}"',
                        'status = "ACTIVE"',
                        'rrule = "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=18;BYMINUTE=55"',
                    ]
                ),
                encoding="utf-8",
            )

            with (
                patch.object(central_command, "LAUNCH_AGENTS_DIR", root / "LaunchAgents"),
                patch.object(central_command, "CODEX_AUTOMATIONS_DIR", automations),
                patch.object(central_command, "LAUNCH_AGENT_SCHEDULES", ()),
                patch.object(central_command, "CODEX_AUTOMATIONS", ()),
            ):
                payload = central_command.build_schedule_status()
                rendered = central_command.render_schedule_status(payload)

        strategy = {item["id"]: item for item in payload["codexAutomations"]}[
            "inferno-strategy-shadow-engine-daily"
        ]
        self.assertTrue(strategy["promptAudit"]["ok"])
        self.assertEqual(strategy["promptAudit"]["status"], "prompt-sync-ok")
        self.assertIn("prompt-sync-ok", rendered)

    def test_schedule_renderer_surfaces_nightly_deployment_drift(self) -> None:
        rendered = central_command.render_schedule_status(
            {
                "generatedAt": "2026-05-10T12:00:00-06:00",
                "entrypoint": "./inferno",
                "launchAgents": [
                    {
                        "id": "io.diablotrading.inferno-nightly-optimize",
                        "purpose": "nightly research",
                        "status": "configured",
                        "schedule": "Mon at 18:30",
                        "scriptSync": {"status": "drift"},
                    }
                ],
                "codexAutomations": [],
            }
        )

        self.assertIn("script-sync drift", rendered)

    def test_build_schedule_status_audits_daily_refresh_deployment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_agents = root / "LaunchAgents"
            launch_agents.mkdir()
            plist_path = launch_agents / "io.diablotrading.inferno-daily-model-refresh.plist"
            with plist_path.open("wb") as handle:
                plistlib.dump(
                    {"StartCalendarInterval": [{"Weekday": 1, "Hour": 6, "Minute": 45}]},
                    handle,
                )
            with (
                patch.object(central_command, "LAUNCH_AGENTS_DIR", launch_agents),
                patch.object(central_command, "CODEX_AUTOMATIONS_DIR", root / "automations"),
                patch.object(
                    central_command,
                    "LAUNCH_AGENT_SCHEDULES",
                    (("io.diablotrading.inferno-daily-model-refresh", "full sync"),),
                ),
                patch.object(central_command, "CODEX_AUTOMATIONS", ()),
                patch.object(
                    central_command,
                    "daily_model_refresh_script_sync_status",
                    return_value={"status": "drift"},
                ),
            ):
                payload = central_command.build_schedule_status()

        self.assertEqual(payload["launchAgents"][0]["scriptSync"]["status"], "drift")

    def test_build_schedule_status_audits_daily_loop_deployment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_agents = root / "LaunchAgents"
            launch_agents.mkdir()
            plist_path = launch_agents / "io.diablotrading.inferno-daily-loop.plist"
            with plist_path.open("wb") as handle:
                plistlib.dump(
                    {"StartCalendarInterval": [{"Weekday": 1, "Hour": 6, "Minute": 30}]},
                    handle,
                )
            with (
                patch.object(central_command, "LAUNCH_AGENTS_DIR", launch_agents),
                patch.object(central_command, "CODEX_AUTOMATIONS_DIR", root / "automations"),
                patch.object(
                    central_command,
                    "LAUNCH_AGENT_SCHEDULES",
                    (("io.diablotrading.inferno-daily-loop", "digest"),),
                ),
                patch.object(central_command, "CODEX_AUTOMATIONS", ()),
                patch.object(
                    central_command,
                    "daily_loop_script_sync_status",
                    return_value={"status": "drift"},
                ),
            ):
                payload = central_command.build_schedule_status()

        self.assertEqual(payload["launchAgents"][0]["scriptSync"]["status"], "drift")

    def test_build_schedule_status_audits_evidence_goal_loop_deployment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_agents = root / "LaunchAgents"
            launch_agents.mkdir()
            plist_path = launch_agents / "io.diablotrading.inferno-evidence-goal-loop.plist"
            with plist_path.open("wb") as handle:
                plistlib.dump(
                    {"StartCalendarInterval": [{"Weekday": 1, "Hour": 13, "Minute": 40}]},
                    handle,
                )
            with (
                patch.object(central_command, "LAUNCH_AGENTS_DIR", launch_agents),
                patch.object(central_command, "CODEX_AUTOMATIONS_DIR", root / "automations"),
                patch.object(
                    central_command,
                    "LAUNCH_AGENT_SCHEDULES",
                    (("io.diablotrading.inferno-evidence-goal-loop", "paper evidence"),),
                ),
                patch.object(central_command, "CODEX_AUTOMATIONS", ()),
                patch.object(
                    central_command,
                    "evidence_goal_loop_script_sync_status",
                    return_value={"status": "drift"},
                ),
            ):
                payload = central_command.build_schedule_status()

        self.assertEqual(payload["launchAgents"][0]["scriptSync"]["status"], "drift")

    def test_schedule_includes_all_installed_inferno_launch_agents(self) -> None:
        labels = {label for label, _purpose in central_command.LAUNCH_AGENT_SCHEDULES}

        self.assertEqual(
            labels,
            {
                "io.diablotrading.inferno-dawn-brief",
                "io.diablotrading.inferno-watchdog",
                "io.diablotrading.inferno-daily-model-refresh",
                "io.diablotrading.inferno-action-pulse",
                "io.diablotrading.inferno-daily-loop",
                "io.diablotrading.inferno-evidence-goal-loop",
                "io.diablotrading.inferno-nightly-optimize",
                "io.diablotrading.inferno-ops-maintenance",
                "io.diablotrading.inferno-desktop-automation",
            },
        )

    def test_launch_agent_schedule_renders_interval_only_and_mixed_cadence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launch_agents = Path(temp_dir)
            interval_only = launch_agents / "io.diablotrading.inferno-ops-maintenance.plist"
            mixed = launch_agents / "io.diablotrading.inferno-dawn-brief.plist"
            with interval_only.open("wb") as handle:
                plistlib.dump({"StartInterval": 1800}, handle)
            with mixed.open("wb") as handle:
                plistlib.dump(
                    {
                        "StartCalendarInterval": [{"Weekday": 1, "Hour": 6, "Minute": 0}],
                        "StartInterval": 600,
                    },
                    handle,
                )

            with patch.object(central_command, "LAUNCH_AGENTS_DIR", launch_agents):
                interval_payload = central_command._read_launch_agent(
                    "io.diablotrading.inferno-ops-maintenance", "ops maintenance"
                )
                mixed_payload = central_command._read_launch_agent(
                    "io.diablotrading.inferno-dawn-brief", "dawn brief"
                )

        self.assertEqual(interval_payload["schedule"], "every 30 minutes")
        self.assertEqual(mixed_payload["schedule"], "Mon at 06:00; every 10 minutes")

    def test_parser_accepts_central_tactical_options(self) -> None:
        parser = central_command.build_parser()

        action_pulse = parser.parse_args(
            ["action-pulse", "--phase", "manual", "--deployable-cash", "0", "--fast"]
        )
        self.assertEqual(action_pulse.command, "action-pulse")
        self.assertEqual(action_pulse.phase, "manual")
        self.assertEqual(action_pulse.deployable_cash, "0")
        self.assertTrue(action_pulse.fast)

        capital_check = parser.parse_args(["capital-check", "--deployable-cash", "1000", "--refresh-live-sync"])
        self.assertEqual(capital_check.command, "capital-check")
        self.assertEqual(capital_check.deployable_cash, "1000")
        self.assertTrue(capital_check.refresh_live_sync)

        strike_cycle = parser.parse_args(["strike-cycle", "--deployable-cash", "500", "--limit", "3"])
        self.assertEqual(strike_cycle.command, "strike-cycle")
        self.assertEqual(strike_cycle.deployable_cash, "500")
        self.assertEqual(strike_cycle.limit, "3")

        oauth = parser.parse_args(["oauth", "refresh"])
        self.assertEqual(oauth.command, "oauth")
        self.assertEqual(oauth.oauth_action, "refresh")

        preflight = parser.parse_args(["preflight", "--max-age-hours", "12"])
        self.assertEqual(preflight.command, "preflight")
        self.assertEqual(preflight.max_age_hours, 12)

        usage = parser.parse_args(["usage", "status"])
        self.assertEqual(usage.command, "usage")
        self.assertEqual(usage.usage_action, "status")

        deposit_plan = parser.parse_args(
            ["deposit-plan", "configure", "--amount", "250", "--interval-days", "14", "--first-date", "2026-07-03"]
        )
        self.assertEqual(deposit_plan.command, "deposit-plan")
        self.assertEqual(deposit_plan.deposit_action, "configure")
        self.assertEqual(deposit_plan.amount, 250)
        self.assertEqual(deposit_plan.interval_days, 14)
        self.assertEqual(deposit_plan.first_date, "2026-07-03")

        tracker_taxonomy = parser.parse_args(["tracker-taxonomy", "status"])
        self.assertEqual(tracker_taxonomy.command, "tracker-taxonomy")
        self.assertEqual(tracker_taxonomy.tracker_taxonomy_action, "status")

        tracker_role_review = parser.parse_args(["tracker-role-review", "status"])
        self.assertEqual(tracker_role_review.command, "tracker-role-review")
        self.assertEqual(tracker_role_review.tracker_role_review_action, "status")

        tracker_role_policy_packet = parser.parse_args(["tracker-role-policy-packet", "status"])
        self.assertEqual(tracker_role_policy_packet.command, "tracker-role-policy-packet")
        self.assertEqual(tracker_role_policy_packet.tracker_role_policy_packet_action, "status")

        tracker_role_policy = parser.parse_args(["tracker-role-policy", "status"])
        self.assertEqual(tracker_role_policy.command, "tracker-role-policy")
        self.assertEqual(tracker_role_policy.tracker_role_policy_action, "status")

        cash_ledger = parser.parse_args(["cash-ledger", "status"])
        self.assertEqual(cash_ledger.command, "cash-ledger")
        self.assertEqual(cash_ledger.cash_ledger_action, "status")

        ticket_cap = parser.parse_args(
            [
                "ticket-cap",
                "configure",
                "--min-ticket",
                "250",
                "--max-ticket",
                "500",
                "--target-ticket",
                "300",
                "--call-posture",
                "call-debit-biased",
            ]
        )
        self.assertEqual(ticket_cap.command, "ticket-cap")
        self.assertEqual(ticket_cap.ticket_cap_action, "configure")
        self.assertEqual(ticket_cap.min_ticket, 250)
        self.assertEqual(ticket_cap.max_ticket, 500)
        self.assertEqual(ticket_cap.target_ticket, 300)
        self.assertEqual(ticket_cap.call_posture, "call-debit-biased")

        partial_ticket_cap = parser.parse_args(["ticket-cap", "configure", "--min-ticket", "300"])
        self.assertEqual(partial_ticket_cap.command, "ticket-cap")
        self.assertEqual(partial_ticket_cap.ticket_cap_action, "configure")
        self.assertEqual(partial_ticket_cap.min_ticket, 300)
        self.assertIsNone(partial_ticket_cap.max_ticket)
        self.assertIsNone(partial_ticket_cap.target_ticket)
        self.assertIsNone(partial_ticket_cap.call_posture)


if __name__ == "__main__":
    unittest.main()
