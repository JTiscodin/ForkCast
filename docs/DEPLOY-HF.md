# Deploy Forkcast free: Hugging Face Space + Vercel + UptimeRobot

Backend runs on a free Hugging Face Docker Space, the website on Vercel, and UptimeRobot pings the
backend so the Space does not fall asleep.

## 1. Create a private dataset for DB backups

Free Spaces lose their disk on every restart. The backend copies its SQLite DB to a private
dataset and restores it on boot (`backend/hf_backup.py`).

1. huggingface.co -> New -> Dataset. Name it e.g. `forkcast-db`, set **Private**.
2. Settings -> Access Tokens -> New token, type **Write**. Keep it for step 3.

## 2. Create the Space

1. huggingface.co -> New -> Space. SDK: **Docker** (blank template). Hardware: **CPU basic (free)**.
2. Visibility: **Public** is simplest (the URL must be reachable by Vercel and UptimeRobot either
   way; private Spaces need an HF token on every request, which the web app does not send). The API
   still checks Forkcast tokens on every non-public route.

## 3. Set Space secrets

Space -> Settings -> Variables and secrets -> **New secret** for each (values from your own
`backend/.env`, never commit them):

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | your key |
| `SWIGGY_MODE` | same as local |
| `SWIGGY_MCP_TOKEN`, `SWIGGY_REFRESH_TOKEN`, `SWIGGY_CLIENT_ID` | copy from your local `.env` after logging in to Swiggy locally |
| `FORKCAST_SECRET` | a long random string |
| `FORKCAST_ORIGINS` | your Vercel URL, e.g. `https://forkcast.vercel.app` |
| `HF_TOKEN` | the write token from step 1 |
| `HF_BACKUP_REPO` | `<your-hf-user>/forkcast-db` |
| `HF_BACKUP_MINUTES` | optional, default `15` |

## 4. Push the code

The Space repo needs, at its root: `Dockerfile` and `README.md` (from `deploy/hf-space/`) and the
`backend/` folder.

Git route:

```bash
git clone https://huggingface.co/spaces/<user>/<space> hf-space
cp deploy/hf-space/Dockerfile deploy/hf-space/README.md hf-space/
cp -r backend hf-space/backend
rm -f hf-space/backend/.env hf-space/backend/mealplanner.db   # never push secrets or the local DB
cd hf-space && git add . && git commit -m "deploy" && git push
```

(Password prompt: your HF username + the write token.)

Upload route: Space -> Files -> Add file -> Upload files; drag in the two files and the `backend`
folder (without `.env` and `mealplanner.db`).

The Space builds and starts. Check `https://<user>-<space>.hf.space/ping` returns `{"ok":true}`.

## 5. Vercel

Project -> Settings -> Environment Variables:
`NEXT_PUBLIC_API_URL=https://<user>-<space>.hf.space`, then redeploy (the value is baked in at build).

## 6. UptimeRobot

uptimerobot.com -> Add New Monitor -> **HTTP(s)**, URL `https://<user>-<space>.hf.space/ping`,
interval **5 minutes**. This keeps the free Space from sleeping after inactivity.

## Caveats (read these)

- **Swiggy login lives on the server.** The browser login flow can't run inside the Space, so log in
  locally and copy the tokens into Space secrets. When they expire, repeat and restart the Space.
- **Backups are periodic.** A crash loses up to `HF_BACKUP_MINUTES` of writes; a clean restart
  uploads one last copy first.
- **Free CPU limits:** 2 vCPU / 16 GB RAM, slow cold builds, and HF may still pause or restart the
  Space; HF's terms don't promise "always on" for free hardware.
- **Location:** Spaces run in the US/EU, so expect ~200-300 ms extra per call from India.
- **Public Space = public code.** Anyone can read the files in a public Space (not the secrets).
  Pick private only if you accept the access-token problem above.
