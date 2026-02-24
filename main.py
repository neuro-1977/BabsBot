import asyncio
import json
import random
import sys
from pathlib import Path

def _app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
import aiohttp
import websockets
from twitchio.ext import commands

CONFIG_PATH = _app_dir() / "config.json"
CHANNEL = "delboitv"
TOKEN_GENERATOR_URL = (
    "https://twitchtokengenerator.com/quick/"
    "moderator-read-followers+channel-read-subscriptions+channel-read-redemptions+chat-read+chat-edit"
)

FOLLOWER_RESPONSES = [
    "Hey @{}, welcome. Don't expect fireworks—I'm still upright, barely.",
    "New blood! @{}. Hope you're on meds too—makes the chat bearable.",
    "Cheers for the follow. DelboiTV's spine says thanks, but it still hurts.",
    "Another one. @{}, try not to fall over—streamer already did.",
    "Follow received. @{}, we don't do enthusiasm here. You'll fit in.",
    "Ta for the follow. @{}—if you're here for good vibes only, wrong channel.",
    "Welcome @{}. DelboiTV's back is in charge; we're just along for the ride.",
    "New follower @{}. No confetti. We're saving energy for the next twinge.",
    "Cheers @{}. Expect dry humour and the occasional groan. That's it.",
    "Follow noted. @{}—welcome to the chaos. Bring painkillers.",
    "Oi @{}, in you come. Don't say we didn't warn you.",
    "Thanks for the follow. @{}—still no refunds on bad backs.",
]

RAID_RESPONSES = [
    "Raid squad! Thanks for the numbers—DelboiTV's still not impressed, but whatever.",
    "Cheers for the raid. You're alright.",
    "Here come the zombies—hope you're not here to judge.",
]

SUB_RESPONSES = [
    "Subbed? Mental. You're now part of the cult. No escape.",
    "Cheers for the sub—you're officially too invested now. No refunds.",
    "Bold move. Pain's free, chat's not.",
]

REDEMPTION_RESPONSES = [
    "Nice one, @{}. You just bought me a coffee—cheers.",
    "Spent points? Respect. You're wild.",
    "Thanks for the redemption—chat's now slightly less dead.",
    "Still upright, DelboiTV? Mad.",
    "Oi DelboiTV, say hi to your new fan.",
    "This stream sucks and so do you—kidding, sort of.",
]


def load_config():
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


class BotRunner(QThread):
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    eventsub_warning = pyqtSignal(str)
    eventsub_ready = pyqtSignal()

    def __init__(self, access_token, refresh_token, client_id, parent=None):
        super().__init__(parent)
        self.access_token = (access_token or "").strip().replace("oauth:", "")
        if self.access_token and not self.access_token.startswith("oauth:"):
            self.access_token = "oauth:" + self.access_token
        self.refresh_token = (refresh_token or "").strip() or None
        self.client_id = (client_id or "").strip() or None
        self._bot = None
        self._loop = None
        self._eventsub_ws = None
        self._eventsub_session_id = None
        self._broadcaster_id = None

    def _helix_headers(self, content_type=None):
        h = {
            "Authorization": "Bearer " + self.access_token.replace("oauth:", ""),
            "Client-Id": self.client_id,
        }
        if content_type:
            h["Content-Type"] = content_type
        return h

    def send_to_chat(self, text: str):
        if self._loop is None or self._bot is None:
            return
        async def _send():
            try:
                await self._bot._connection.send(f"PRIVMSG #{CHANNEL} :{text}")
            except Exception:
                pass
            ch = self._bot.get_channel(CHANNEL) or next((c for c in self._bot.connected_channels if c is not None), None)
            if ch:
                try:
                    await ch.send(text)
                except Exception:
                    pass
        try:
            asyncio.run_coroutine_threadsafe(_send(), self._loop)
        except Exception:
            pass

    def run(self):
        asyncio.run(self._run_bot_and_eventsub())

    async def _run_bot_and_eventsub(self):
        self._loop = asyncio.get_event_loop()
        if not self.access_token:
            self.error.emit("No access token in config.")
            return
        try:
            self._bot = commands.Bot(
                token=self.access_token,
                prefix="!",
                initial_channels=[CHANNEL],
            )
            self._bot.runner = self

            @self._bot.event()
            async def event_ready():
                self.status.emit("connected")
                await self._bot._connection.wait_until_ready()
                msg = "BabsBot here. I'll call out follows, raids, subs and redemptions."
                try:
                    await self._bot._connection.send(f"PRIVMSG #{CHANNEL} :{msg}")
                except Exception:
                    pass
                ch = self._bot.get_channel(CHANNEL) or next((c for c in self._bot.connected_channels if c is not None), None)
                if ch:
                    try:
                        await ch.send(msg)
                    except Exception:
                        pass

            asyncio.create_task(self._subscribe_eventsub())
            await self._bot.start()
        except Exception as e:
            self.error.emit(str(e))

    async def _subscribe_eventsub(self):
        if not self.access_token:
            return
        if not self.client_id:
            self.eventsub_warning.emit("Client ID is required for follow/raid/sub/redemption. Add it in Settings (Show optional fields).")
            return
        try:
            async with websockets.connect(
                "wss://eventsub.wss.twitch.tv/ws",
                close_timeout=2,
                open_timeout=10,
            ) as ws:
                self._eventsub_ws = ws
                msg = await asyncio.wait_for(ws.recv(), timeout=15)
                data = json.loads(msg)
                if data.get("metadata", {}).get("message_type") != "session_welcome":
                    self.eventsub_warning.emit("EventSub: did not receive session_welcome.")
                    return
                self._eventsub_session_id = data.get("payload", {}).get("session", {}).get("id")
                if not self._eventsub_session_id:
                    self.eventsub_warning.emit("EventSub: no session ID in welcome.")
                    return
                self._broadcaster_id = await self._get_broadcaster_id()
                if not self._broadcaster_id:
                    return
                await self._cleanup_eventsub_subscriptions()
                subs = [
                    ("channel.follow", "2", {"broadcaster_user_id": self._broadcaster_id, "moderator_user_id": self._broadcaster_id}),
                    ("channel.raid", "1", {"to_broadcaster_user_id": self._broadcaster_id}),
                    ("channel.subscribe", "1", {"broadcaster_user_id": self._broadcaster_id}),
                    ("channel.channel_points_custom_reward_redemption.add", "1", {"broadcaster_user_id": self._broadcaster_id}),
                ]
                ok = True
                for sub_type, version, condition in subs:
                    ok = ok and await self._create_eventsub_sub(sub_type, version, condition)
                if ok:
                    self.eventsub_ready.emit()
                while True:
                    raw = await ws.recv()
                    ev = json.loads(raw)
                    mtype = ev.get("metadata", {}).get("message_type")
                    if mtype == "notification":
                        await self._handle_eventsub_notification(ev)
                    elif mtype in ("session_reconnect", "revocation"):
                        break
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _get_broadcaster_id(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.twitch.tv/helix/users?login=" + CHANNEL,
                    headers=self._helix_headers(),
                ) as r:
                    if r.status != 200:
                        text = await r.text()
                        try:
                            j = json.loads(text)
                            msg = j.get("message", text)
                        except Exception:
                            msg = text or str(r.status)
                        self.eventsub_warning.emit(f"Could not get broadcaster ID: {r.status} - {msg}")
                        return None
                    j = await r.json()
                    users = j.get("data", [])
                    if users:
                        return users[0].get("id")
        except Exception as e:
            self.eventsub_warning.emit(f"Could not get broadcaster ID: {e!s}")
        return None

    async def _cleanup_eventsub_subscriptions(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.twitch.tv/helix/eventsub/subscriptions",
                    headers=self._helix_headers(),
                ) as r:
                    if r.status != 200:
                        return
                    j = await r.json()
                    for sub in j.get("data", []):
                        transport = sub.get("transport", {})
                        if transport.get("method") == "websocket":
                            sub_id = sub.get("id")
                            if sub_id:
                                async with session.delete(
                                    "https://api.twitch.tv/helix/eventsub/subscriptions",
                                    headers=self._helix_headers(),
                                    params={"id": sub_id},
                                ):
                                    pass
        except Exception:
            pass

    async def _create_eventsub_sub(self, sub_type, version, condition):
        try:
            async with aiohttp.ClientSession() as session:
                body = {
                    "type": sub_type,
                    "version": version,
                    "condition": condition,
                    "transport": {"method": "websocket", "session_id": self._eventsub_session_id},
                }
                async with session.post(
                    "https://api.twitch.tv/helix/eventsub/subscriptions",
                    headers=self._helix_headers("application/json"),
                    json=body,
                ) as r:
                    if r.status not in (200, 202):
                        try:
                            j = await r.json()
                            msg = j.get("message", str(r.status))
                            if r.status == 403 and "channel.follow" in sub_type:
                                msg = "Follow events need moderator:read:followers scope. Regenerate token with that scope (see Settings)."
                            elif r.status == 403 and "channel.subscribe" in sub_type:
                                msg = "Sub events need channel:read:subscriptions scope. Regenerate token (see Settings)."
                            elif r.status == 403 and "redemption" in sub_type:
                                msg = "Redemption events need channel:read:redemptions (or channel:manage:redemptions). Regenerate token (see Settings)."
                            self.eventsub_warning.emit(f"{sub_type}: {msg}")
                        except Exception:
                            self.eventsub_warning.emit(f"{sub_type}: HTTP {r.status}")
                        return False
                    return True
        except Exception as e:
            self.eventsub_warning.emit(f"{sub_type}: {e!s}")
            return False

    async def _handle_eventsub_notification(self, ev):
        payload = ev.get("payload", {})
        sub_type = payload.get("subscription", {}).get("type")
        event = payload.get("event", {})
        ch = self._bot.get_channel(CHANNEL)
        if not ch:
            return
        user_name = (event.get("user_name") or event.get("from_broadcaster_user_name") or event.get("user_login") or "").strip()
        try:
            if sub_type == "channel.follow":
                msg = random.choice(FOLLOWER_RESPONSES)
                if "{}" in msg:
                    msg = msg.format(user_name or "someone")
                await ch.send(msg)
            elif sub_type == "channel.raid":
                await ch.send(random.choice(RAID_RESPONSES))
            elif sub_type == "channel.subscribe":
                await ch.send(random.choice(SUB_RESPONSES))
            elif sub_type == "channel.channel_points_custom_reward_redemption.add":
                msg = random.choice(REDEMPTION_RESPONSES)
                if "{}" in msg:
                    msg = msg.format(user_name or "someone")
                await ch.send(msg)
        except Exception:
            pass


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BabsBot Settings")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        btn_tokens = QPushButton("Get Twitch Tokens")
        btn_tokens.setMinimumHeight(44)
        btn_tokens.clicked.connect(self._open_token_generator)
        layout.addWidget(btn_tokens)
        must_have_note = QLabel(
            "Authorize as broadcaster (delboitv) or a mod. Paste the access token below. "
            "Add Client ID (from dev.twitch.tv/console/apps) in optional fields—required for follow/sub/redemption."
        )
        must_have_note.setWordWrap(True)
        must_have_note.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(must_have_note)
        self.access_edit = QLineEdit()
        self.access_edit.setPlaceholderText("Access Token (oauth:...)")
        self.access_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(QLabel("Access Token (oauth:...)"))
        layout.addWidget(self.access_edit)
        self.optional_container = QWidget()
        opt_layout = QVBoxLayout(self.optional_container)
        opt_layout.setContentsMargins(0, 0, 0, 0)
        self.refresh_edit = QLineEdit()
        self.refresh_edit.setPlaceholderText("Refresh Token (optional)")
        self.refresh_edit.setEchoMode(QLineEdit.EchoMode.Password)
        opt_layout.addWidget(QLabel("Refresh Token (optional)"))
        opt_layout.addWidget(self.refresh_edit)
        self.client_edit = QLineEdit()
        self.client_edit.setPlaceholderText("Client ID — required for events")
        self.client_edit.setEchoMode(QLineEdit.EchoMode.Password)
        opt_layout.addWidget(QLabel("Client ID (required for follow/sub/redemption)"))
        opt_layout.addWidget(self.client_edit)
        layout.addWidget(self.optional_container)
        self.show_optional_btn = QPushButton("Show optional fields (Refresh Token, Client ID)")
        self.show_optional_btn.clicked.connect(self._toggle_optional)
        layout.addWidget(self.show_optional_btn)
        note = QLabel("Paste token and Client ID, then Save. Restart the app to connect.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        cfg = load_config()
        self.access_edit.setText(cfg.get("access_token", ""))
        self.refresh_edit.setText(cfg.get("refresh_token", ""))
        self.client_edit.setText(cfg.get("client_id", ""))
        has_optional = bool((cfg.get("refresh_token") or "").strip() or (cfg.get("client_id") or "").strip())
        self.optional_container.setVisible(has_optional)
        self._optional_visible = has_optional
        self.show_optional_btn.setText(self._optional_btn_text())

    def _optional_btn_text(self):
        return "Hide optional fields" if self._optional_visible else "Show optional fields (Refresh Token, Client ID)"

    def _toggle_optional(self):
        self._optional_visible = not self._optional_visible
        self.optional_container.setVisible(self._optional_visible)
        self.show_optional_btn.setText(self._optional_btn_text())

    def _open_token_generator(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(TOKEN_GENERATOR_URL))

    def _save(self):
        ok = save_config({
            "access_token": self.access_edit.text().strip(),
            "refresh_token": self.refresh_edit.text().strip(),
            "client_id": self.client_edit.text().strip(),
        })
        if not ok:
            QMessageBox.critical(self, "Error", "Could not save config. Check folder permissions.")
            return
        QMessageBox.information(self, "Saved", "Config saved. Restart BabsBot to connect with the new token.")
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Babs — Neuro + A.I. for DelboiTV")
        self.setToolTip("This app was created by Neuro + A.I. For DelboiTV")
        self.setMinimumSize(200, 200)
        self.resize(200, 200)
        self.setStyleSheet("""
            QMainWindow { background: rgba(0,0,0,0.92); }
            QWidget#central {
                background: rgba(20,20,20,0.9);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 12px;
            }
            QLabel { color: #fff; background: transparent; }
            QPushButton {
                background: rgba(255,255,255,0.08);
                color: #fff;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 4px;
                padding: 4px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.18);
                border-color: rgba(255,255,255,0.25);
            }
        """)
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.status_label = QLabel("Running")
        self.status_label.setFont(QFont("Segoe UI", 8))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setMaximumWidth(176)
        self.status_label.setWordWrap(True)
        top_row = QHBoxLayout()
        top_row.addWidget(self.status_label, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        settings_btn = QPushButton("\u2699")
        settings_btn.setFixedSize(28, 28)
        settings_btn.clicked.connect(self._open_settings)
        top_row.addWidget(settings_btn)
        layout.addLayout(top_row)
        logo_label = QLabel()
        logo_path = _app_dir() / "logo.png"
        if not logo_path.exists() and getattr(sys, "frozen", False):
            logo_path = Path(sys._MEIPASS) / "logo.png"
        if logo_path.exists():
            logo_label.setPixmap(QPixmap(str(logo_path)).scaled(176, 176, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            logo_label.setText("(logo)")
            logo_label.setStyleSheet("color: #666;")
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setFixedSize(188, 188)
        layout.addWidget(logo_label, alignment=Qt.AlignmentFlag.AlignCenter)
        test_btn = QPushButton("Test chat")
        test_btn.setFixedHeight(24)
        test_btn.clicked.connect(self._send_test_message)
        layout.addWidget(test_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        credit = QLabel("Neuro + A.I. for DelboiTV")
        credit.setFont(QFont("Segoe UI", 7))
        credit.setStyleSheet("color: #666; background: transparent;")
        credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(credit)
        layout.addStretch()
        self.bot_runner = None
        self._start_bot_from_config()

    def _open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()
        self._start_bot_from_config()

    def _send_test_message(self):
        if self.bot_runner and self.bot_runner.isRunning():
            self.bot_runner.send_to_chat("BabsBot here. I'll call out follows, raids, subs and redemptions.")
            self.status_label.setText("Sent!")
            QTimer.singleShot(2500, lambda: self.status_label.setText("Running"))
        else:
            QMessageBox.information(self, "Babs", "Bot not connected. Add a token in Settings (gear) and restart.")

    def _start_bot_from_config(self):
        if self.bot_runner and self.bot_runner.isRunning():
            return
        cfg = load_config()
        token = (cfg.get("access_token") or "").strip()
        if not token:
            self.status_label.setText("No token")
            return
        self.bot_runner = BotRunner(
            cfg.get("access_token"),
            cfg.get("refresh_token"),
            cfg.get("client_id"),
        )
        self.bot_runner.status.connect(self._on_bot_status)
        self.bot_runner.error.connect(self._on_bot_error)
        self.bot_runner.eventsub_warning.connect(self._on_eventsub_warning)
        self.bot_runner.eventsub_ready.connect(self._on_eventsub_ready)
        self.bot_runner.start()
        self.status_label.setText("Connecting…")

    def _on_bot_status(self, text):
        self.status_label.setText("Running")

    def _on_bot_error(self, text):
        self.status_label.setText("Error")
        QMessageBox.warning(self, "BabsBot", f"Bot could not connect:\n\n{text}\n\nCheck your token in Settings (gear icon).")

    def _on_eventsub_warning(self, text):
        QMessageBox.warning(self, "BabsBot EventSub", text)

    def _on_eventsub_ready(self):
        self.status_label.setToolTip("EventSub: follow, raid, sub, redemption")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    icon_path = Path(getattr(sys, "_MEIPASS", _app_dir())) / "icon.ico"
    if not icon_path.exists():
        icon_path = _app_dir() / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    if icon_path.exists():
        win.setWindowIcon(QIcon(str(icon_path)))
    win.show()
    win.raise_()
    win.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
