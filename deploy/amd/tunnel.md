# Reaching the clinic server

Health data. Rules: vLLM never gets a public port. Only Caddy (443, plus 80 for certificate issuance) and SSH (22) are open.

## Option A: SSH tunnel (no public exposure, best for the demo laptop)
```bash
ssh -N -L 8800:127.0.0.1:8800 -L 8001:127.0.0.1:8001 root@<DROPLET_IP>
# Clinic console: http://localhost:8800     vLLM (bench from laptop): http://localhost:8001/v1
```
`serve_vllm.sh` already binds vLLM to `127.0.0.1`, and `docker-compose.clinic.yml` publishes no vLLM port, so the tunnel is the only way in from outside. Keep it alive with `autossh -M 0 -N -L ...` if installed.

Caveat: a patient device posting a share package (`POST /api/inbox`) must reach the clinic over HTTPS, so for the full flow use Option B for port 8800 only and keep vLLM tunnelled.

## Option B: Caddy with HTTPS (what a real clinic does)
1. DNS A record `clinic.<your-domain>` to the droplet IP (or use `clinic.<IP>.sslip.io`).
2. Cloud firewall in the AMD Developer Cloud dashboard (verify the control exists on your droplet): inbound TCP 22 (restrict to your IP), 80, 443. Nothing else.
3. Docker `-p` publishes bypass UFW. So publish only to loopback (`127.0.0.1:...`) and let the cloud firewall be the real boundary.
4. Run Caddy with `deploy/amd/Caddyfile` (the compose file does this).
5. Test from outside: `curl -i https://clinic.<domain>/api/health` returns 200; `curl -m 5 http://<IP>:8001/v1/models` must fail to connect.

## After the event
Rotate `VLLM_API_KEY`, delete the HF token from the box, destroy the droplet (powering off still bills). Shared packages live in the clinic container volume: remove it with `docker compose -f deploy/docker-compose.clinic.yml down -v`.
