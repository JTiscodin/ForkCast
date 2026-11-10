# Deploying Forkcast for free: Oracle Cloud (backend) + Vercel (website)

Why this split: Swiggy only allows calls from a fixed IP address, the backend must
stay running (catalogue warm-up, nightly job), and the database is a file on disk.
An Oracle "Always Free" VM gives all three; Vercel hosts the Next.js site for free.

You will end up with three values for `docs/PRODUCTION-APPLICATION.md`:
the VM's **public IP**, the **backend address** and the **website address**.

## 1. Oracle Cloud VM (about 20 minutes)

1. Sign up at cloud.oracle.com (a card is needed for verification; Always Free
   resources are not charged). Pick **India West (Mumbai)** or **India South
   (Hyderabad)** as the home region. It cannot be changed later.
2. Compute → Instances → Create instance.
   - Image: **Ubuntu 24.04**.
   - Shape: an **Always Free eligible** one (`VM.Standard.E2.1.Micro`, or Ampere
     `VM.Standard.A1.Flex` with 1 CPU / 6 GB if available).
   - Download the SSH private key it offers.
3. Networking → Reserved public IPs → reserve one and attach it to the instance,
   so the IP survives restarts. **This is the static IP Swiggy asks for.**
4. Open ports 80 and 443: Instance → Subnet → Security List → add two ingress
   rules, source `0.0.0.0/0`, TCP, ports `80` and `443`.

## 2. A free address for the backend

Create a subdomain at duckdns.org (for example `forkcast-api`) and point it at
the VM's public IP. The backend address becomes `https://forkcast-api.duckdns.org`.

## 3. Install the backend on the VM

```bash
ssh -i <key file> ubuntu@<public IP>

sudo apt update && sudo apt install -y python3-venv git caddy
# Ubuntu images on Oracle also block ports locally:
sudo iptables -I INPUT 6 -p tcp -m multiport --dports 80,443 -j ACCEPT
sudo netfilter-persistent save

git clone https://github.com/JTiscodin/Swiggy-Builder.git
cd Swiggy-Builder/backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

cp .env.example .env && nano .env      # fill every value (see the comments in the file)
```

Swiggy login: the "Connect Swiggy" button opens a browser on the machine the
backend runs on, so it cannot be used on a server. Connect once on your laptop,
then copy `SWIGGY_MCP_TOKEN`, `SWIGGY_REFRESH_TOKEN` and `SWIGGY_CLIENT_ID` from
the laptop's `backend/.env` into the server's. The nightly job keeps the token fresh.

```bash
sudo cp ../deploy/forkcast.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now forkcast

sudo cp ../deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile          # put your DuckDNS name on the first line
sudo systemctl restart caddy
```

Check: `curl https://forkcast-api.duckdns.org/mode` should print JSON with
`"live": true`. The first plan takes about three minutes after a restart.

## 4. Website on Vercel

1. vercel.com → Add New → Project → import the GitHub repo.
2. **Root Directory: `web`**. Framework: Next.js (detected).
3. Environment variable: `NEXT_PUBLIC_API_URL` = `https://forkcast-api.duckdns.org`.
4. Deploy. Copy the address it gives you (for example `https://forkcast.vercel.app`).
5. Back on the VM, set `FORKCAST_ORIGINS` in `backend/.env` to that exact address
   and run `sudo systemctl restart forkcast`. Without this the site cannot call the backend.

## 5. Updating later

```bash
cd ~/Swiggy-Builder && git pull && sudo systemctl restart forkcast
```
Vercel redeploys the website by itself on every push.

## Safety defaults on the server

- Orders stay in **dry run** until a user switches to Live with a second confirmation.
- The backend listens on `127.0.0.1` only; the internet reaches it through Caddy over HTTPS.
- "Local only" actions (the nightly trigger, account recovery) refuse anything
  that came through the proxy.
- `backend/.env`, the database and `.auth_secret` are never in git. Back up
  `backend/mealplanner.db` if the data matters.

## Known limit of this setup

The server holds **one** Swiggy login (yours). Everyone who opens the site sees
restaurants for that account's address and, in Live mode, would order on that
account. That is fine for Swiggy's review of the product, and it is why Live
mode should stay off for other people until per-user Swiggy sign-in is built
(see `docs/PRODUCTION-APPLICATION.md`).
