# Run it on Oracle Cloud (Always Free)

A small always-on server in Mumbai with a fixed IP, so the bot runs every market day without your laptop, and so the IP you register with Groww never changes. Written from a real setup in November 2026; Oracle's console changes often, so labels may differ slightly.

Why a fixed IP: under SEBI's retail algo framework, Groww requires orders sent through your API keys to come from a static IP you've registered. Reading data (everything this project does today) doesn't need it, but a server with a reserved IP is ready for it and also keeps the bot running unattended.

## 1. Account and region

Sign up at cloud.oracle.com and choose **India West (Mumbai)** or **India South (Hyderabad)** as the home region. You can't change it later.

## 2. Network first (avoids a greyed-out "public IP" switch)

Creating the network inside the VM wizard can leave the public-IP switch disabled. Create it first:

1. **Networking → Virtual cloud networks → Create VCN**: name `trader-vcn`, IPv4 CIDR `10.0.0.0/16` (type it and press Enter).
2. In the VCN: **Gateways → Create Internet Gateway** (`trader-igw`).
3. **Routing**: add a route rule to the default route table (or a new one): target type *Internet Gateway*, destination `0.0.0.0/0`, target `trader-igw`.
4. **Subnets → Create Subnet**: `public-subnet`, CIDR `10.0.0.0/24`, that route table, **Subnet access: Public**, the default security list (it allows SSH on port 22 only).

Or use **Actions → Start VCN Wizard → Create VCN with Internet Connectivity**, which does all four.

## 3. The VM

**Compute → Instances → Create instance**

- Image: **Canonical Ubuntu 24.04**
- Shape: **Ampere VM.Standard.A1.Flex** (1 OCPU, 6 GB) if available; Mumbai often reports *Out of capacity*. Then use **Specialty and previous generation → VM.Standard.E2.1.Micro** (AMD, 1 GB) and the non-aarch64 Ubuntu image. Both are Always Free; the Micro is enough.
- Security: leave shielded instance and confidential computing off.
- Networking: existing VCN and `public-subnet`; **Automatically assign public IPv4 address** on.
- SSH keys: **Generate a key pair for me** and download the private key. You can't download it again.
- Storage: defaults.

## 4. Make the IP permanent

The IP assigned at creation is *ephemeral*. Replace it with a reserved one:

1. **Networking → IP management → Reserved public IPs → Reserve public IP address**.
2. Instance → **Networking → Attached VNICs → (VNIC) → IP administration** → on the primary private IP: **⋯ → Edit → No public IP → Update**.
3. **⋯ → Edit** again → **Reserved public IP → select it → Update**. (The reserved option only appears once the ephemeral IP is gone.)

Register this IP at **groww.in/trade-api/api-keys → Add static IP**. You can only change it about once a week, so check the digits.

## 5. Log in and prepare the server

```
mv ~/Downloads/"ssh-key-YYYY-MM-DD.key" ~/.ssh/trader.key && chmod 400 ~/.ssh/trader.key
ssh -i ~/.ssh/trader.key ubuntu@YOUR_RESERVED_IP
```

```
sudo apt update && sudo apt upgrade -y          # if it mentions a pending kernel: sudo reboot, reconnect
sudo timedatectl set-timezone Asia/Kolkata
sudo apt install -y python3-venv git
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

The swap file matters on the 1 GB Micro.

## 6. Install

```
git clone https://github.com/MaheshPulivarthi18/groww-trader-skills.git
python3 -m venv ~/venv
~/venv/bin/pip install growwapi pyotp            # + pymongo if you use the MongoDB mirror
mkdir -p ~/trading/trader
cp ~/groww-trader-skills/config.example.json ~/trading/trader/config.json
nano ~/trading/trader/config.json                # YOUR capital and limits; keep "paper": true
```

## 7. Credentials

```
nano ~/.groww_env
```

```
export GROWW_TOTP_TOKEN='the long TOTP token'
export GROWW_TOTP_SECRET='the TOTP secret: only A-Z and 2-7'
export GTRADE_HOME="$HOME/trading/trader"
```

```
chmod 600 ~/.groww_env
echo "source ~/.groww_env" >> ~/.bashrc
echo "alias gt='~/venv/bin/python ~/groww-trader-skills/gtrade.py'" >> ~/.bashrc
source ~/.bashrc
```

Rules: no spaces around `=`, single quotes around values. Create the key as **TOTP** (dropdown next to *Generate API Key*). If the secret Groww shows contains lowercase letters or symbols, it isn't the TOTP secret: scan the QR code with your phone camera and take the part after `secret=`. Never paste keys into chats or screenshots; if you do, revoke them.

## 8. Test

```
gt check                 # prints a price: login works
gt fetch --days 60       # caches 5-minute candles
gt backtest SBIN --setup orb --source csv
gt paper once
```

## 9. Run every market morning

```
crontab -e
```

```
55 8 * * 1-5 cd $HOME/trading && . $HOME/.groww_env && $HOME/venv/bin/python $HOME/groww-trader-skills/gtrade.py paper run >> $HOME/trading/paper.log 2>&1
```

Then `sudo systemctl restart cron` (cron reads the timezone at start), and test the exact command in cron's bare environment:

```
env -i HOME=$HOME sh -c 'cd $HOME/trading && . $HOME/.groww_env && $HOME/venv/bin/python $HOME/groww-trader-skills/gtrade.py paper once'
```

Watch it: `tail -f ~/trading/paper.log`.

## 10. Keep the VM

- Oracle reclaims Always Free VMs that look idle for a week (very low CPU, network and memory), and this bot looks idle. Upgrading the account to **Pay As You Go** avoids that; Always Free resources stay free. Set a small **budget alert** right after.
- Keep SSH key-only and the security list at SSH only. Don't open ports for dashboards; use the MongoDB mirror or Telegram instead.
- Update with `cd ~/groww-trader-skills && git pull`.
