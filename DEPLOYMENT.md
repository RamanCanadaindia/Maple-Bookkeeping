# Deploy Maple Ledger AI

## 1. Secure the project

Revoke the Gemini key that was previously stored in `services/ai_service.py` and create a new key. Never commit `.streamlit/secrets.toml`, `google_credentials.json`, `.env`, or `accounting.db`.

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` for local use and replace every placeholder. On Streamlit Community Cloud, paste the same TOML into **App settings > Secrets** instead of uploading the file.

The Google service account must have the Google Sheets and Google Drive APIs enabled. Share the existing master spreadsheet with the service account's `client_email` as an Editor.

## 2. Test locally

From the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

## 3. Push to GitHub

Create a new empty private repository on GitHub. Do not initialize it with a README or other files. Then run:

```powershell
git status
git add .gitignore requirements.txt app.py core services ui .streamlit/config.toml .streamlit/secrets.toml.example DEPLOYMENT.md
git commit -m "Prepare Streamlit Cloud deployment"
git branch -M main
git remote add origin https://github.com/YOUR-USER/YOUR-REPOSITORY.git
git push -u origin main
```

Before pushing, confirm `git status` does not list `google_credentials.json`, `accounting.db`, `.streamlit/secrets.toml`, or `.env`.

## 4. Deploy on Streamlit Community Cloud

1. Sign in at https://share.streamlit.io using GitHub.
2. Select **Create app**, then choose the repository and `main` branch.
3. Set the main file path to `app.py`.
4. Open **Advanced settings** and paste the contents of your real `.streamlit/secrets.toml` into **Secrets**.
5. Deploy, then inspect the app logs if package installation or startup fails.

## Important data limitation

The app currently uses a local SQLite file. Streamlit Community Cloud storage is ephemeral, so bookkeeping data can disappear when the app restarts, redeploys, or moves to another instance. Use the deployment for testing only until the database is moved to a persistent hosted database such as PostgreSQL. Do not upload the existing `accounting.db` because it may contain confidential financial and user data.
