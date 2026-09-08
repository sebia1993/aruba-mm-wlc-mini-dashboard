"""README용 비식별 대시보드 화면을 실제 PySide6 MainWindow에서 생성합니다.

실제 네트워크에 접속하지 않으며 RFC 5737 문서용 IPv4와 가상 장비명만 사용합니다.
"""

from __future__ import annotations

import argparse
import os
import hashlib
import json
import platform
import socket
import subprocess
import tomllib
from unittest.mock import patch
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import __version__ as qt_version
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont, QFontDatabase, QImage
from PySide6.QtWidgets import QApplication

from aruba_mini_dashboard.config import AppSettings, ClusterMemberSettings
from aruba_mini_dashboard.ui.main_window import MainWindow
from aruba_mini_dashboard.ui.settings_dialog import SettingsDialog


class CoordinatorStub(QObject):
    """MainWindow 문서 렌더링에 필요한 신호/상태만 제공하는 비네트워크 stub."""

    cycle_started = Signal()
    cycle_finished = Signal(object)
    cycle_failed = Signal(str)
    busy_changed = Signal(bool)
    automatic_changed = Signal(bool)
    next_check_changed = Signal(object)
    scheduled_poll_skipped = Signal(str)
    manual_poll_queued = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.busy = False
        self.automatic = False

    def check_now(self) -> None:
        return None

    def start_automatic(self) -> None:
        self.automatic = True

    def pause_automatic(self) -> None:
        self.automatic = False


def _settings() -> AppSettings:
    settings = AppSettings.default()
    settings.ui.window_width = 1400
    settings.ui.window_height = 1100
    settings.ui.window_maximized = False
    settings.mobility_master.management_ip = "192.0.2.1"
    settings.mobility_master.display_name = "DEMO-MM"
    settings.cluster.members = [
        ClusterMemberSettings(ip=f"192.0.2.{10 + index}", alias=f"WLC-{index + 1:02d}")
        for index in range(4)
    ]
    settings.cluster.primary_controller_ip = "192.0.2.10"
    settings.cluster.fallback_controller_ips = ["192.0.2.11", "192.0.2.12", "192.0.2.13"]
    return settings


def _device(
    ip: str,
    alias: str,
    *,
    severity: str = "normal",
    controller_state: str = "up",
    active: int | None = 120,
    standby: int | None = 80,
    connection_type: str = "L2-Connected",
    distribution_state: str = "normal",
    streak: int = 0,
    reasons: tuple[str, ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        ip=ip,
        alias=alias,
        hostname=f"demo-{alias.lower()}",
        mm_status="Down" if controller_state == "down" else "Up",
        controller_state=controller_state,
        active_clients=active,
        standby_clients=standby,
        connection_type=connection_type,
        distribution_state=distribution_state,
        load_anomaly_streak=streak,
        severity=severity,
        last_seen=datetime(2026, 9, 8, 10, 30, tzinfo=timezone.utc),
        is_registered=True,
        issue_reasons=list(reasons),
    )


def _snapshot(*, incident: bool) -> SimpleNamespace:
    if not incident:
        devices = [
            _device("192.0.2.10", "WLC-01", active=138, standby=92),
            _device("192.0.2.11", "WLC-02", active=126, standby=101),
            _device("192.0.2.12", "WLC-03", active=117, standby=88),
            _device("192.0.2.13", "WLC-04", active=131, standby=96),
        ]
        return SimpleNamespace(
            severity="normal",
            summary="등록 컨트롤러의 MM 상태와 Cluster 분배가 정상입니다.",
            devices=devices,
            problem_ips=[],
            checked_at=datetime(2026, 9, 8, 10, 30, tzinfo=timezone.utc),
            monitoring_scope_ips=[device.ip for device in devices],
            raw_outputs={},
            parse_results={},
            previous_devices={},
            active_incidents=[],
        )

    devices = [
        _device("192.0.2.10", "WLC-01", active=142, standby=90),
        _device(
            "192.0.2.11",
            "WLC-02",
            severity="attention",
            active=4,
            standby=124,
            distribution_state="anomalous",
            streak=3,
            reasons=("Active Client 분배 이상이 3회 연속 확인됨",),
        ),
        _device(
            "192.0.2.12",
            "WLC-03",
            severity="failure",
            controller_state="down",
            active=None,
            standby=None,
            distribution_state="unknown",
            reasons=("MM이 Controller 상태를 Down으로 보고함",),
        ),
        _device("192.0.2.13", "WLC-04", active=128, standby=95),
    ]
    return SimpleNamespace(
        severity="failure",
        summary="MM Down과 Client 분배 이상이 서로 다른 장비에서 감지되었습니다.",
        devices=devices,
        problem_ips=["192.0.2.12", "192.0.2.11"],
        checked_at=datetime(2026, 9, 8, 10, 35, tzinfo=timezone.utc),
        monitoring_scope_ips=[device.ip for device in devices],
        raw_outputs={},
        parse_results={},
        previous_devices={},
        active_incidents=[
            SimpleNamespace(ip="192.0.2.11", active=True, acknowledged=False,
                            incident_type="load_anomaly"),
            SimpleNamespace(ip="192.0.2.12", active=True, acknowledged=False,
                            incident_type="controller_down"),
        ],
    )


def _load_docs_font(app: QApplication) -> None:
    font_path = os.environ.get("DOCS_FONT_PATH", "").strip()
    if not font_path:
        app.setFont(QFont("Malgun Gothic" if sys.platform == "win32" else "Apple SD Gothic Neo", 10))
        return
    font_id = QFontDatabase.addApplicationFont(font_path)
    if font_id < 0:
        raise RuntimeError("문서용 한글 글꼴을 로드하지 못했습니다.")
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise RuntimeError("문서용 한글 글꼴 family를 확인하지 못했습니다.")
    app.setFont(QFont(families[0], 9))


def _save(window: MainWindow, path: Path, snapshot: SimpleNamespace) -> None:
    window.update_snapshot(snapshot)
    window.resize(1400, 1100)
    window._apply_responsive_mode(force=True)
    QApplication.processEvents()
    if not window.grab().save(str(path), "PNG"):
        raise RuntimeError(f"문서 화면 PNG 저장에 실패했습니다: {path}")


def _validate(path: Path) -> None:
    image = QImage(str(path))
    if image.isNull():
        raise RuntimeError(f"문서 화면 PNG를 다시 열 수 없습니다: {path}")
    if image.width() < 1000 or image.height() < 600:
        raise RuntimeError(
            f"문서 화면 해상도가 예상보다 작습니다: {path} ({image.width()}x{image.height()})"
        )
    if path.stat().st_size < 5_000:
        raise RuntimeError(f"문서 화면 파일이 비정상적으로 작습니다: {path}")
    print(f"created: {path} ({image.width()}x{image.height()}, {path.stat().st_size} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("ArubaMiniDashboardDocs")
    app.setQuitOnLastWindowClosed(False)
    _load_docs_font(app)

    def deny_connection(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Network connections are forbidden in documentation captures")

    names = ["dashboard-normal.png", "dashboard-incident.png", "dashboard-filtered.png", "dashboard-settings.png"]
    with patch.object(socket.socket, "connect", deny_connection), patch.object(
        socket.socket, "connect_ex", deny_connection
    ), patch.object(socket, "create_connection", deny_connection):
        coordinator = CoordinatorStub()
        settings = _settings()
        window = MainWindow(coordinator, settings, demo_mode=True)
        window.show()
        app.processEvents()
        normal = _snapshot(incident=False)
        incident = _snapshot(incident=True)
        # Two fixture observations create a real two-point session sparkline.
        # This is display data, not a measurement or correlation-engine result.
        _save(window, output / names[0], normal)
        _save(window, output / names[1], incident)
        window.status_filter_combo.setCurrentIndex(window.status_filter_combo.findData("failure"))
        app.processEvents()
        if window.device_page_model.rowCount() != 1:
            raise RuntimeError("Failure filter must show only the synthetic Down member")
        if not window.grab().save(str(output / names[2]), "PNG"):
            raise RuntimeError("Could not save filtered dashboard")
        dialog = SettingsDialog(settings, parent=window)
        dialog.resize(1100, 900)
        dialog.show()
        app.processEvents()
        if not dialog.grab().save(str(output / names[3]), "PNG"):
            raise RuntimeError("Could not save settings dialog")
        dialog.close()
        window.tray_icon.hide()
        window.request_quit()
        app.processEvents()

    files = []
    for name in names:
        path = output / name
        _validate(path)
        picture = QImage(str(path))
        files.append({"name": name, "width": picture.width(), "height": picture.height(),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    metadata = {
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "app_version": tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())["project"]["version"], "python": platform.python_version(),
        "qt": qt_version, "os": platform.platform(),
        "scale_factor": os.environ.get("QT_SCALE_FACTOR", "1"),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"), "synthetic": True,
        "method": "actual MainWindow / SettingsDialog with CoordinatorStub and synthetic snapshots",
        "limitations": "No SSH, parser/correlation pipeline or physical Windows desktop verification",
        "files": files,
    }
    (output / "capture-metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
