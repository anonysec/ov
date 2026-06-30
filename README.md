# OV

Monorepo for the OpenVPN management stack:

- **[`panel/`](./panel)** — OV-Panel: the web panel that manages OpenVPN users, nodes and configs.
- **[`node/`](./node)** — OV-Node: the per-server backend agent that runs on each OpenVPN box.

## Install

On the panel server:

```bash
bash <(curl -s https://raw.githubusercontent.com/anonysec/ov/main/panel/install.sh)
```

On each OpenVPN (node) server:

```bash
bash <(curl -s https://raw.githubusercontent.com/anonysec/ov/main/node/install.sh)
```

> Installs are driven by GitHub **Releases** — publish a release on this repo for the
> one-line installers to fetch the latest version.

## Multi-login (per-config connection limit)

Each user has a **Max Logins** setting controlling how many devices can connect with the
same config at once (`1` = single login, `0` = unlimited). Enforcement runs on the node.
See [`panel/docs/multi-login.md`](./panel/docs/multi-login.md) and
[`node/docs/multi-login.md`](./node/docs/multi-login.md).
