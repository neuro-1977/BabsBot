import asyncio
import json
import random
import secrets
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

def _app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QPixmap, QFont
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
OAUTH_PORT = 8765
OAUTH_REDIRECT_URI = f"http://localhost:{OAUTH_PORT}/callback"
OAUTH_SCOPES = "chat:read chat:edit moderator:read:followers channel:read:subscriptions channel:read:redemptions"
TOKEN_GENERATOR_URL = (
    "https://twitchtokengenerator.com/"
    "?auth=auth_stay&scope=chat%3Aread+chat%3Aedit+moderator%3Aread%3Afollowers"
    "+channel%3Aread%3Asubscriptions+channel%3Aread%3Aredemptions"
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


_oauth_token_queue = []
_oauth_server_ref = [None]


def _make_oauth_handler():
    class OAuthHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            try:
                if self.path.startswith("/callback"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="font-family:sans-serif;background:#1a1a1a;color:#00ff00;padding:2em;text-align:center;">
<script>
var h = location.hash.substring(1);
var p = new URLSearchParams(h);
var t = p.get('access_token');
if (t) location.replace('http://localhost:%s/capture?access_token=' + encodeURIComponent(t));
else document.body.innerHTML = '<p>No token received. Close this window.</p>';
</script>
<p>Please wait...</p>
</body></html>""" % OAUTH_PORT)
                    return
                if self.path.startswith("/capture?"):
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    tokens = qs.get("access_token", [])
                    if tokens:
                        _oauth_token_queue.append(tokens[0])
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="font-family:sans-serif;background:#1a1a1a;color:#00ff00;padding:2em;text-align:center;">
<h2>Success!</h2><p>Close this window and return to BabsBot. Click Save.</p>
</body></html>""")
                    srv = _oauth_server_ref[0]
                    if srv:
                        threading.Thread(target=srv.shutdown, daemon=True).start()
            except Exception:
                pass
    return OAuthHandler


def _run_oauth_server():
    handler = _make_oauth_handler()
    server = HTTPServer(("127.0.0.1", OAUTH_PORT), handler)
    server.allow_reuse_address = True
    _oauth_server_ref[0] = server
    try:
        server.serve_forever()
    except Exception:
        pass
    _oauth_server_ref[0] = None


class BotRunner(QThread):
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    eventsub_warning = pyqtSignal(str)
    eventsub_ready = pyqtSignal()
    channel_ready = pyqtSignal(str)

    def __init__(self, access_token, refresh_token, client_id, channel_override=None, parent=None):
        super().__init__(parent)
        self.access_token = (access_token or "").strip().replace("oauth:", "")
        if self.access_token and not self.access_token.startswith("oauth:"):
            self.access_token = "oauth:" + self.access_token
        self.refresh_token = (refresh_token or "").strip() or None
        self.client_id = (client_id or "").strip() or None
        self._channel_override = (channel_override or "").strip().lower().replace("#", "") or None
        self._channel = None
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
                await self._bot._connection.send(f"PRIVMSG #{self._channel} :{text}")
            except Exception:
                pass
            ch = self._bot.get_channel(self._channel) or next((c for c in self._bot.connected_channels if c is not None), None)
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

    async def _get_token_user_login(self):
        """Get the Twitch login of the account that owns the token (their channel)."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.twitch.tv/helix/users",
                    headers=self._helix_headers(),
                ) as r:
                    if r.status != 200:
                        return None
                    j = await r.json()
                    users = j.get("data", [])
                    if users:
                        return (users[0].get("login") or "").strip().lower()
        except Exception:
            pass
        return None

    async def _run_bot_and_eventsub(self):
        self._loop = asyncio.get_event_loop()
        if not self.access_token:
            self.error.emit("No access token in config.")
            return
        if self._channel_override:
            self._channel = self._channel_override
        else:
            token_login = await self._get_token_user_login()
            if not token_login:
                self.error.emit("Could not get channel from token. Set 'Channel to join' in Settings or check token.")
                return
            self._channel = token_login
        self.channel_ready.emit(self._channel)
        try:
            self._bot = commands.Bot(
                token=self.access_token,
                prefix="!",
                initial_channels=[self._channel],
            )
            self._bot.runner = self

            @self._bot.event()
            async def event_ready():
                self.status.emit("connected")
                await self._bot._connection.wait_until_ready()
                msg = "BabsBot here. I'll call out follows, raids, subs and redemptions."
                try:
                    await self._bot._connection.send(f"PRIVMSG #{self._channel} :{msg}")
                except Exception:
                    pass
                ch = self._bot.get_channel(self._channel) or next((c for c in self._bot.connected_channels if c is not None), None)
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
                    "https://api.twitch.tv/helix/users?login=" + self._channel,
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
        ch = self._bot.get_channel(self._channel)
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
        self.setStyleSheet("""
            QDialog { background: #1a1a1a; }
            QLabel { color: #00ff00; }
            QLineEdit { color: #00ff00; background: #2a2a2a; border: 1px solid rgba(0,255,0,0.4); }
            QPushButton { color: #00ff00; background: rgba(0,255,0,0.12); border: 1px solid rgba(0,255,0,0.4); }
            QPushButton:hover { background: rgba(0,255,0,0.22); }
        """)
        layout = QVBoxLayout(self)
        easy_note = QLabel(
            "Easiest: Add your Client ID below (click Show optional fields), then click \"Log in with Twitch\". "
            "Your browser opens → click Authorize → token is filled for you. Then Save.\n"
            "One-time: In dev.twitch.tv → your app → Redirect URIs, add: " + OAUTH_REDIRECT_URI
        )
        easy_note.setWordWrap(True)
        easy_note.setStyleSheet("color: #00ff00; font-size: 11px;")
        layout.addWidget(easy_note)
        who_posts = QLabel("The bot joins your channel and posts from the account you log in with. One account — no second \"bot\" account needed.")
        who_posts.setWordWrap(True)
        who_posts.setStyleSheet("color: #00ff00; font-size: 11px;")
        layout.addWidget(who_posts)
        layout.addWidget(QLabel("Channel to join (your stream — where the bot should post)"))
        self.channel_edit = QLineEdit()
        self.channel_edit.setPlaceholderText("e.g. delboitv — leave blank to use token account's channel")
        layout.addWidget(self.channel_edit)
        self.btn_login = QPushButton("Log in with Twitch")
        self.btn_login.setMinimumHeight(44)
        self.btn_login.clicked.connect(self._login_with_twitch)
        layout.addWidget(self.btn_login)
        layout.addWidget(QLabel("Access Token (filled by Log in above, or paste manually)"))
        self.access_edit = QLineEdit()
        self.access_edit.setPlaceholderText("oauth:...")
        self.access_edit.setEchoMode(QLineEdit.EchoMode.Password)
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
        btn_manual = QPushButton("Or open token generator (manual copy‑paste)")
        btn_manual.setMaximumWidth(280)
        btn_manual.clicked.connect(self._open_token_generator)
        layout.addWidget(btn_manual, alignment=Qt.AlignmentFlag.AlignCenter)
        note = QLabel("After token is set, click Save. The bot will connect automatically.")
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
        self.channel_edit.setText(cfg.get("channel", ""))
        has_optional = bool((cfg.get("refresh_token") or "").strip() or (cfg.get("client_id") or "").strip())
        no_token = not (cfg.get("access_token") or "").strip()
        if no_token:
            self.optional_container.setVisible(True)
            self._optional_visible = True
        else:
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
        QDesktopServices.openUrl(QUrl(TOKEN_GENERATOR_URL))

    def _login_with_twitch(self):
        client_id = self.client_edit.text().strip()
        if not client_id:
            QMessageBox.warning(
                self,
                "Client ID needed",
                "Enter your Client ID first (click Show optional fields and paste it from dev.twitch.tv).\n\n"
                "One-time: In your Twitch app settings, add this under Redirect URIs:\n" + OAUTH_REDIRECT_URI,
            )
            return
        _oauth_token_queue.clear()
        scope_param = urllib.parse.quote(OAUTH_SCOPES, safe="").replace("%20", "+")
        state = secrets.token_urlsafe(16)
        url = (
            "https://id.twitch.tv/oauth2/authorize"
            "?client_id=" + urllib.parse.quote(client_id, safe="")
            + "&redirect_uri=" + urllib.parse.quote(OAUTH_REDIRECT_URI, safe="")
            + "&response_type=token"
            + "&scope=" + scope_param
            + "&state=" + state
            + "&force_verify=true"
        )
        thread = threading.Thread(target=_run_oauth_server, daemon=True)
        thread.start()
        QDesktopServices.openUrl(QUrl(url))
        self.btn_login.setText("Waiting for you to click Authorize…")
        self._oauth_check_timer = QTimer(self)
        self._oauth_check_timer.timeout.connect(self._oauth_check_token)
        self._oauth_check_timer.start(300)

    def _oauth_check_token(self):
        if _oauth_token_queue:
            self._oauth_check_timer.stop()
            token = _oauth_token_queue.pop(0)
            if not token.startswith("oauth:"):
                token = "oauth:" + token
            self.access_edit.setText(token)
            self.btn_login.setText("Log in with Twitch")
            QMessageBox.information(self, "Token received", "Token is filled above. Click Save.")
            return
        if _oauth_server_ref[0] is None:
            self._oauth_check_timer.stop()
            self.btn_login.setText("Log in with Twitch")

    def _save(self):
        ch = (self.channel_edit.text() or "").strip().lower().replace("#", "").strip() or None
        ok = save_config({
            "access_token": self.access_edit.text().strip(),
            "refresh_token": self.refresh_edit.text().strip(),
            "client_id": self.client_edit.text().strip(),
            "channel": ch or "",
        })
        if not ok:
            QMessageBox.critical(self, "Error", "Could not save config. Check folder permissions.")
            return
        QMessageBox.information(self, "Saved", "Saved. Connecting now…")
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
                border: 1px solid rgba(0,255,0,0.3);
                border-radius: 12px;
            }
            QLabel { color: #00ff00; background: transparent; }
            QPushButton {
                background: rgba(0,255,0,0.12);
                color: #00ff00;
                border: 1px solid rgba(0,255,0,0.4);
                border-radius: 4px;
                padding: 4px;
            }
            QPushButton:hover {
                background: rgba(0,255,0,0.22);
                border-color: rgba(0,255,0,0.6);
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
            logo_label.setStyleSheet("color: #00ff00;")
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setFixedSize(188, 188)
        layout.addWidget(logo_label, alignment=Qt.AlignmentFlag.AlignCenter)
        test_btn = QPushButton("Test chat")
        test_btn.setFixedHeight(24)
        test_btn.clicked.connect(self._send_test_message)
        layout.addWidget(test_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        credit = QLabel("Neuro + A.I. for DelboiTV")
        credit.setFont(QFont("Segoe UI", 7))
        credit.setStyleSheet("color: #00ff00; background: transparent;")
        credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(credit)
        layout.addStretch()
        self.bot_runner = None
        self._start_bot_from_config()
        cfg = load_config()
        if not (cfg.get("access_token") or "").strip():
            QTimer.singleShot(100, self._open_settings)

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
            cfg.get("channel"),
        )
        self.bot_runner.status.connect(self._on_bot_status)
        self.bot_runner.error.connect(self._on_bot_error)
        self.bot_runner.eventsub_warning.connect(self._on_eventsub_warning)
        self.bot_runner.eventsub_ready.connect(self._on_eventsub_ready)
        self.bot_runner.channel_ready.connect(self._on_channel_ready)
        self.bot_runner.start()
        self.status_label.setText("Connecting…")

    def _on_bot_status(self, text):
        self.status_label.setText("Running")

    def _on_channel_ready(self, channel):
        self.status_label.setToolTip("Posting to #" + channel)

    def _on_bot_error(self, text):
        self.status_label.setText("Error")
        QMessageBox.warning(self, "BabsBot", f"Bot could not connect:\n\n{text}\n\nCheck your token in Settings (gear icon).")

    def _on_eventsub_warning(self, text):
        is_scope = "scope" in text.lower() or "moderator:read:followers" in text
        if is_scope:
            msg = QMessageBox(self)
            msg.setWindowTitle("BabsBot EventSub")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setText(
                "Your token is missing a required permission.\n\n"
                "Easiest: Open Settings (gear) and use \"Log in with Twitch\" — it gets a token with the right permissions. Then Save.\n\n"
                "Or click \"Open token page\" to use the website and paste a token manually."
            )
            open_btn = msg.addButton("Open token page", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Ok)
            msg.exec()
            if msg.clickedButton() == open_btn:
                QDesktopServices.openUrl(QUrl(TOKEN_GENERATOR_URL))
                QTimer.singleShot(500, self._open_settings)
        else:
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
