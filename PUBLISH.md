# Publish BabsBot to GitHub

Do this once to create the public repo and first release.

## 1. Create the repo on GitHub

1. Open **https://github.com/new**
2. Log in as **neuro-1977** (or the account that owns [neuro-1977](https://github.com/neuro-1977)).
3. **Repository name:** `BabsBot`
4. **Public**
5. Leave **README, .gitignore, license** unchecked (we already have them locally).
6. Click **Create repository**.

## 2. Push code and tag

From the BabsBot folder:

```bash
cd D:\_Code_\BabsBot
git push -u origin main
git push origin v1.0.0
```

If Git asks for credentials, use a [Personal Access Token](https://github.com/settings/tokens) (repo scope) as the password.

## 3. Create the release and upload the installer

1. Build the exe if needed:
   ```bash
   python -m PyInstaller --noconfirm --distpath . BabsBot.spec
   ```
2. On GitHub go to **https://github.com/neuro-1977/BabsBot/releases**.
3. Click **Draft a new release**.
4. **Choose a tag:** `v1.0.0` (create from existing tag).
5. **Release title:** e.g. `v1.0.0`
6. **Description:** e.g. `First release. Windows desktop app for DelboiTV: follow/raid/sub/redemption chat bot. Download BabsBot.exe below.`
7. Under **Assets**, click **Attach binaries** and select `BabsBot.exe` from `D:\_Code_\BabsBot\BabsBot.exe`.
8. Click **Publish release**.

After that, the **Releases** page will have the installer for download.
