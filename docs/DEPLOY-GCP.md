# Deploying Forkcast for free: Google Cloud (backend) + Vercel (website)

The Google Cloud version of `docs/DEPLOY.md`. Same split and same reasons: Swiggy
only allows calls from a fixed IP address, the backend must stay running, and the
database is a file on disk. The backend runs on one Google Cloud **Always Free**
VM; Vercel hosts the Next.js site for free (Firebase Hosting does not run
Next.js server features, so it is not used).

You will end up with three values for `docs/PRODUCTION-APPLICATION.md`: the VM's
**public IP**, the **backend address** and the **website address**.

## Read first: what is free and what is not

Always Free covers, per billing account: **one e2-micro VM** in `us-central1`,
`us-west1` or `us-east1` only; **30 GB of standard persistent disk**; **1 GB a
month** of outbound traffic from North America. Everything else is billed.

- The disk must be type `pd-standard`. `gcloud` defaults to `pd-balanced`, which
  is **not** free. The command below sets it.
- **External IP: not certain it is free.** Since February 2024 Google bills
  every external IPv4 address in use by a VM (about $0.005/hour, around
  $3.65/month), static or ephemeral. I could not confirm whether Always Free
  waives this for the free e2-micro. Check Billing → Reports two days after
  setup. A reserved static IP that is **not** attached to a running VM is
  always billed, so delete it if you delete or stop the VM.
- Outbound traffic over 1 GB a month is billed (light use stays far below).
- Set a safety alarm: Billing → Budgets & alerts → Create budget → 1 USD, alerts
  at 50% and 100%. It emails you; it does not stop spending.
- There is no free region in India, so the server is in the US. Each Swiggy
  call takes about a quarter second longer than from Mumbai.

## 0. What you do yourself

1. Create a Google Cloud account at console.cloud.google.com and turn on
   billing (a card is needed for verification).
2. Install the gcloud CLI (cloud.google.com/sdk/docs/install), then run
   `gcloud auth login` yourself. It opens your browser to sign in. Or use
   **Cloud Shell** (the `>_` button in the console), which is already signed in.
   Never paste passwords, keys or tokens into chat, scripts or git.
3. Choose a **project ID**: 6 to 30 characters, lowercase letters, digits and
   hyphens, unique across all of Google Cloud (for example `forkcast-ab12`).

## 1. Project, IP, firewall and VM (about 15 minutes)

Run these on your computer. Replace `<project-id>` with your ID. To use another
free region, change `us-central1` / `us-central1-a` everywhere (for example
`us-east1` / `us-east1-b`).

```bash
gcloud projects create <project-id>
gcloud config set project <project-id>
gcloud billing accounts list                     # copy the ACCOUNT_ID
gcloud billing projects link <project-id> --billing-account=<ACCOUNT_ID>
gcloud services enable compute.googleapis.com
```

Reserve the static IP. **This is the IP Swiggy asks for.**

```bash
gcloud compute addresses create forkcast-ip --region=us-central1
gcloud compute addresses describe forkcast-ip --region=us-central1 --format="value(address)"
```

Open ports 80 and 443 (port 22 for SSH is already open on the default network):

```bash
gcloud compute firewall-rules create forkcast-web --network=default --direction=INGRESS --allow=tcp:80,tcp:443 --source-ranges=0.0.0.0/0 --target-tags=forkcast
```

Create the VM (e2-micro, Debian 12, 30 GB standard disk, the static IP):

```bash
gcloud compute instances create forkcast --zone=us-central1-a --machine-type=e2-micro --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=30GB --boot-disk-type=pd-standard --address=forkcast-ip --tags=forkcast
```

**Ephemeral IP instead (no reservation):** skip the two `addresses` commands
and drop `--address=forkcast-ip`. Read the IP with:

```bash
gcloud compute instances describe forkcast --zone=us-central1-a --format="get(networkInterfaces[0].accessConfigs[0].natIP)"
```

It survives reboots but **changes if you Stop and Start the VM**, which breaks
Swiggy's IP allow-list. You can make it static later without downtime:
`gcloud compute addresses create forkcast-ip --region=us-central1 --addresses=<that IP>`.

Connect over SSH:

```bash
gcloud compute ssh forkcast --zone=us-central1-a
```

The first time, gcloud makes an SSH key on your computer. If it asks for a
passphrase, pick one yourself. The key stays on your machine.

## 2. A free address for the backend

Create a subdomain at duckdns.org (for example `forkcast-api`) and point it at
the VM's IP. The backend address becomes `https://forkcast-api.duckdns.org`.

## 3. Install the backend on the VM

On the VM (inside the SSH session). The setup script clones nothing: you put
the repo at `/opt/forkcast` yourself, as the first two lines do.

```bash
sudo apt-get update && sudo apt-get install -y git
sudo git clone https://github.com/JTiscodin/Swiggy-Builder.git /opt/forkcast
sudo bash /opt/forkcast/deploy/gcp-setup.sh forkcast-api.duckdns.org
```

`deploy/gcp-setup.sh` installs python3-venv, git and Caddy; adds a 2 GB swap file
(the e2-micro has 1 GB RAM); creates a `forkcast` user with no sudo; builds
`backend/.venv` and installs `backend/requirements.txt`; installs
`deploy/forkcast.service` (with the user and path changed to `/opt/forkcast`)
and `deploy/Caddyfile` (with your DuckDNS name). Running it again is safe.
Unlike Oracle's Ubuntu image, Debian on Google Cloud has no local firewall, so
the `iptables` step from `docs/DEPLOY.md` is not needed. SQLite stays on the VM
disk at `/opt/forkcast/backend/mealplanner.db`.

Then fill in the secrets and restart:

```bash
sudo nano /opt/forkcast/backend/.env
sudo systemctl restart forkcast
```

The backend reads these variables (names from `backend/.env.example`; the file's
comments say what goes in each):

| Variable | What it is |
|---|---|
| `GEMINI_API_KEY` | Your Gemini API key |
| `SWIGGY_MODE` | `mcp` |
| `SWIGGY_MCP_TOKEN` | Copied from your laptop's `backend/.env` |
| `SWIGGY_REFRESH_TOKEN` | Copied from your laptop's `backend/.env` |
| `SWIGGY_CLIENT_ID` | Copied from your laptop's `backend/.env` |
| `FORKCAST_SECRET` | Long random string: `python3 -c "import secrets;print(secrets.token_hex(32))"` |
| `FORKCAST_ORIGINS` | The website address from step 4 |

Swiggy login: "Connect Swiggy" opens a browser on the machine the backend runs
on, so it cannot be used on a server. Connect once on your laptop, then paste
the three Swiggy values straight into `nano` over SSH. The nightly job keeps the
token fresh.

Check: `curl https://forkcast-api.duckdns.org/mode` should print JSON with
`"live": true`. The first plan takes about three minutes after a restart. Logs:
`sudo journalctl -u forkcast -f`.

## 4. Website on Vercel

1. vercel.com → Add New → Project → import the GitHub repo.
2. **Root Directory: `web`**. Framework: Next.js (detected).
3. Environment variable: `NEXT_PUBLIC_API_URL` = `https://forkcast-api.duckdns.org`.
4. Deploy. Copy the address it gives you (for example `https://forkcast.vercel.app`).
5. On the VM, set `FORKCAST_ORIGINS` to that exact address: no trailing slash,
   comma-separated if there are several (for example
   `FORKCAST_ORIGINS=https://forkcast.vercel.app`). Then
   `sudo systemctl restart forkcast`. Without this the site cannot call the backend.

## 5. Values for the Swiggy production application

- Public IP: the address from step 1.
- Backend address: `https://forkcast-api.duckdns.org` (your DuckDNS name).
- Website address: your Vercel address.
- Production redirect URL: `https://forkcast-api.duckdns.org/auth/swiggy/callback`.
  The backend does **not** serve this route yet: today's login catches the
  redirect on `http://localhost:8765/callback` on your laptop. Until per-user
  Swiggy sign-in is built, keep connecting on the laptop and copying the tokens.

## 6. Updating later

```bash
sudo -u forkcast git -C /opt/forkcast pull
sudo bash /opt/forkcast/deploy/gcp-setup.sh forkcast-api.duckdns.org
```

Vercel redeploys the website by itself on every push. Back up
`/opt/forkcast/backend/mealplanner.db` if the data matters.

## Removing everything (stops all charges)

```bash
gcloud compute instances delete forkcast --zone=us-central1-a
gcloud compute addresses delete forkcast-ip --region=us-central1
gcloud compute firewall-rules delete forkcast-web
```

The "Safety defaults on the server" and "Known limit of this setup" sections of
`docs/DEPLOY.md` apply here unchanged.
