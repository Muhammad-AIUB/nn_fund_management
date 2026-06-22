# Deploying NN Fund Management to Microsoft Azure (free)

This guide puts the module on a public URL using a **free Azure account**. The app
runs from this repo's Docker stack **unchanged** — you create one small Linux VM and
run Compose on it.

> **Cost in one line:** a new Azure free account gives **$200 of credit for 30 days**.
> A **B2s** VM (2 vCPU / 4 GB RAM) costs ~$30/month, so the credit covers the whole
> evaluation window for **$0**. See [Keeping it free](#keeping-it-free) to avoid any
> charge afterwards.

---

## What you need first

- A Microsoft account (or GitHub account) to sign in.
- A non-prepaid credit/debit card for identity verification (Azure places a ~$1
  temporary hold and removes it — staying in free limits is not charged).
- An SSH key pair on your computer. If you don't have one:
  ```bash
  ssh-keygen -t ed25519 -C "azure-odoo"
  ```
  (Press Enter through the prompts; the public key is `~/.ssh/id_ed25519.pub`.)

---

## Part 1 — Create the Azure free account

1. Go to **https://azure.microsoft.com/free** → **Start free**.
2. Sign in / create a Microsoft account, enter the verification card. You get the
   **$200 / 30-day credit** automatically.

## Part 2 — Create the VM

1. In the [Azure Portal](https://portal.azure.com) search **Virtual machines** →
   **Create → Azure virtual machine**.
2. Fill in:
   - **Resource group:** create one, e.g. `nn-fund-rg` (deleting this later removes
     everything in one click).
   - **VM name:** `nn-fund-odoo`
   - **Region:** pick one close to you, e.g. *Central India* or *Southeast Asia*.
   - **Image:** **Ubuntu Server 24.04 LTS**
   - **Size:** **Standard_B2s** (2 vCPU, 4 GB RAM). *(Click "See all sizes" if it's
     not in the shortlist.)*
   - **Authentication type:** **SSH public key** → paste your `~/.ssh/id_ed25519.pub`.
   - **Username:** `azureuser`
   - **Inbound ports:** allow **SSH (22)** for now.
3. **Review + create → Create.** When it's done, open the VM page and copy its
   **Public IP address**.

## Part 3 — Open the Odoo port (8069)

Odoo serves on port **8069**, which isn't open by default.

1. On the VM page → **Networking** (or *Network settings*) → **Add inbound port rule**.
2. Set: **Destination port ranges = 8069**, **Protocol = TCP**, **Action = Allow**,
   **Priority = 310**, **Name = `Allow-Odoo-8069`** → **Add**.

## Part 4 — Connect and install Docker

From your computer:

```bash
ssh azureuser@<VM-PUBLIC-IP>
```

Then on the VM:

```bash
# Install Docker Engine + the compose plugin
curl -fsSL https://get.docker.com | sh

# Run docker without sudo (log out/in once after this, or run `newgrp docker`)
sudo usermod -aG docker $USER
newgrp docker
```

## Part 5 — Deploy the app

```bash
# 1. Get the code
git clone https://github.com/Muhammad-AIUB/nn_fund_management.git
cd nn_fund_management

# 2. Set a strong Odoo master password (replaces the placeholder in odoo.conf)
NEWPW=$(openssl rand -base64 24)
sed -i "s|REPLACE_WITH_A_STRONG_MASTER_PASSWORD|$NEWPW|" odoo.conf
echo "Your Odoo master password is: $NEWPW"   # save this somewhere safe

# 3. Start only the database first
docker compose -f docker-compose.prod.yml up -d db

# 4. Create the database AND install this module (with the §13 demo data)
docker compose -f docker-compose.prod.yml run --rm odoo \
  odoo -d odoo -i nn_fund_management --stop-after-init

# 5. Start the full stack (Odoo server + db)
docker compose -f docker-compose.prod.yml up -d
```

> Doing the install as a one-off `run` **before** starting the long-running server
> avoids two Odoo processes touching a fresh database at the same time.

## Part 6 — Verify it's live

1. In a browser open **`http://<VM-PUBLIC-IP>:8069`** — the Odoo login appears.
2. Log in with **`admin` / `admin`** (the default created with demo data).
   **Immediately change this password** (top-right → *My Profile → Account Security*) —
   it's a public server.
3. Open **Fund Management → Dashboard** — the demo scenario is already populated.
4. (Recommended) Walk the spec **§13** flow live to prove it end-to-end:
   receive 1,000,000 → allocate 600,000 to Project A → reject (money returns) →
   re-allocate & approve → transfer 200,000 A→B → requisition 150,000 on B →
   bill 100,000 (50,000 remains) → try to bill 60,000 (blocked) → try Project A
   against B's requisition (blocked).
5. Put the URL in [README.md](README.md) and your submission.

Check the containers any time:
```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f odoo   # Ctrl-C to stop tailing
```

---

## Keeping it free

The $200 credit covers ~30 days of the B2s VM. To make sure you never pay:

- **Stop (deallocate)** the VM whenever you don't need it live (Portal → VM → **Stop**).
  A deallocated VM stops billing compute. Start it again before a demo.
- **After the role decision: delete the resource group** (`nn-fund-rg`). That removes
  the VM, disk, IP and network in one action → guaranteed $0.
- **Want it free past 30 days?** Resize the VM down to the free-for-12-months **B1s**
  (1 vCPU / 1 GB RAM, 750 hrs/month). 1 GB is tight for Odoo, so first add these two
  lines to `odoo.conf` to keep it stable, then `docker compose -f docker-compose.prod.yml up -d`:
  ```ini
  workers = 0
  limit_memory_hard = 805306368
  ```

---

## Appendix A — Optional: HTTPS + clean hostname (Caddy)

For a `https://...` URL instead of `http://<ip>:8069`, add a Caddy reverse proxy.
You need a hostname pointing at the VM IP (a free subdomain from e.g. DuckDNS works).

1. In `odoo.conf` add: `proxy_mode = True`
2. Create `Caddyfile` next to the compose file:
   ```
   your-name.duckdns.org {
       reverse_proxy odoo:8069
   }
   ```
3. Add a Caddy service to the prod compose (ports `80:80` and `443:443`, image
   `caddy:2`, mounting the `Caddyfile`) and open ports **80** and **443** in the NSG
   (Part 3). Caddy fetches a free Let's Encrypt certificate automatically.

This is a bonus polish — plain `http://<ip>:8069` is perfectly fine for the assessment.

---

## Troubleshooting

- **Page won't load** → confirm the NSG rule for **8069** (Part 3) and that the
  stack is up (`docker compose -f docker-compose.prod.yml ps`).
- **`permission denied` on docker** → you skipped `newgrp docker` (Part 4), or log
  out and back in.
- **Odoo restarting / OOM on a 1 GB VM** → apply the `workers = 0` tuning above, or
  use the B2s size.
- **Module not visible** → re-run the install step:
  `docker compose -f docker-compose.prod.yml run --rm odoo odoo -d odoo -u nn_fund_management --stop-after-init`.
