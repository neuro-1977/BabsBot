# BabsBot

A small Windows desktop app for **DelboiTV** Twitch chat. It joins the channel, listens for follow / raid / sub / channel point redemption events, and posts random dry-humour responses. Dark glassmorphic UI, resizable window, settings for Twitch tokens and Client ID.

**Created by [Neuro + A.I.](https://github.com/neuro-1977) for DelboiTV.**

---

## Download (installer)

**[Releases](https://github.com/neuro-1977/BabsBot/releases)** — download `BabsBot.exe` from the latest release. No install step: run the exe, add your Twitch token and Client ID in Settings (gear), restart. Put `logo.png` next to the exe if you want the logo in the window.

---

## Requirements

- **Windows**
- Twitch **Access Token** with scopes: `chat:read`, `chat:edit`, `moderator:read:followers`, `channel:read:subscriptions`, `channel:read:redemptions`
- Twitch **Client ID** (from [dev.twitch.tv](https://dev.twitch.tv/console/apps))
- Token must be for the **broadcaster** (DelboiTV) or a **moderator** of the channel

Use the in-app **Get Twitch Tokens** button to open a generator link with the right scopes. Authorize as the broadcaster or a mod, paste the token and Client ID, Save, then restart.

---

## Run from source

```bash
git clone https://github.com/neuro-1977/BabsBot.git
cd BabsBot
pip install -r requirements.txt
python main.py
```

Use `pythonw main.py` to avoid a console window. Optional: add `logo.png` in the same folder.

---

## Build BabsBot.exe

```bash
cd BabsBot
pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --distpath . BabsBot.spec
```

The executable is created in the same folder as `BabsBot.exe`. Optional: run `make_icon.py` first (edit the source image path) to generate `icon.ico` and `logo.png`, then rebuild so the exe and window use the icon.

---

## What it does

- Connects to **#delboitv** via Twitch IRC and EventSub (WebSocket).
- Sends one welcome message on connect; you can trigger it again with **Test chat**.
- On **new follower** → random line from the follower list (e.g. “Hey @user, welcome…”).
- On **raid** → random raid line.
- On **new sub** → random sub line.
- On **channel point redemption** → random redemption line.

Follows work when the channel is offline; raids, subs, and redemptions fire when the channel is live. All response lines are in `main.py` (e.g. `FOLLOWER_RESPONSES`); edit and rebuild to change them.

---

## Files

| File            | Purpose |
|-----------------|--------|
| `main.py`       | App entry, UI, bot, EventSub logic |
| `requirements.txt` | Python deps (twitchio 2.x, PyQt6, aiohttp, websockets) |
| `BabsBot.spec`  | PyInstaller spec (optional icon/logo) |
| `COMMENTS.txt`  | User-editable notes (does not affect run) |
| `make_icon.py`  | Builds `icon.ico` and `logo.png` from a source image |
| `config.json`   | Created at runtime; stores token and Client ID (do not commit) |

---

## License

Use and modify as you like. Credit: **Neuro + A.I.** for DelboiTV.
