import os
import pexpect, sys
import subprocess
import shutil
import requests
from uuid import uuid4
from colorama import Fore, Style


def setup_multilogin() -> None:
    """Install the multi-login (per-config connection limit) enforcement.

    Copies the client-connect/disconnect scripts into place and makes sure
    server.conf enables duplicate-cn + the script hooks. Idempotent and
    self-contained (no app imports) so it is safe to run during install.
    The running app also re-applies this on startup as a safety net.
    """
    server_conf = "/etc/openvpn/server/server.conf"
    scripts_dst_dir = "/etc/openvpn/scripts"
    limits_dir = "/etc/openvpn/limits"
    # Source scripts ship inside the repo (installer runs from /opt/ov-node).
    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "core", "scripts")

    connect_dst = os.path.join(scripts_dst_dir, "ovpanel-client-connect.sh")
    disconnect_dst = os.path.join(scripts_dst_dir, "ovpanel-client-disconnect.sh")

    os.makedirs(scripts_dst_dir, exist_ok=True)
    os.makedirs(limits_dir, exist_ok=True)

    for fname, dst in (
        ("ovpanel-client-connect.sh", connect_dst),
        ("ovpanel-client-disconnect.sh", disconnect_dst),
    ):
        src = os.path.join(src_dir, fname)
        if os.path.exists(src):
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o755)

    required = [
        "duplicate-cn",
        "script-security 2",
        f"client-connect {connect_dst}",
        f"client-disconnect {disconnect_dst}",
    ]

    if os.path.exists(server_conf):
        with open(server_conf, "r") as f:
            content = f.read()
        existing = {ln.strip() for ln in content.splitlines()}
        to_add = [d for d in required if d not in existing]
        if to_add:
            with open(server_conf, "a") as f:
                f.write(
                    "\n# ov-panel multi-login (per-config connection limit)\n"
                    + "\n".join(to_add)
                    + "\n"
                )


def create_ccd() -> None:
    ccd_dir = "/etc/openvpn/ccd"
    server_conf = "/etc/openvpn/server/server.conf"

    if not os.path.exists(ccd_dir):
        subprocess.run(["mkdir", "-p", ccd_dir], check=True)
        subprocess.run(["chmod", "755", ccd_dir], check=True)

        with open(server_conf, "r") as f:
            lines = f.readlines()

        ccd_line = f"client-config-dir {ccd_dir}\n"
        ccd_exclusive_line = "ccd-exclusive\n"
        statuses = "status /var/log/openvpn-status.log 10\n"
        # status-version 3 -> machine-readable CLIENT_LIST format that the
        # traffic parser and connection-limit script depend on.
        status_version = "status-version 3\n"

        if ccd_line not in lines:
            lines.append("\n" + ccd_line)

        if ccd_exclusive_line not in lines:
            lines.append(ccd_exclusive_line)

        if not any(l.startswith("status ") for l in lines):
            lines.append(statuses)

        if not any(l.startswith("status-version") for l in lines):
            lines.append(status_version)

        with open(server_conf, "w") as f:
            f.writelines(lines)

    # Set up multi-login enforcement (idempotent) on install.
    setup_multilogin()

    # Auto restart after installing multi-login scripts + server.conf hooks.
    # This is REQUIRED so the client-connect script becomes active immediately.
    print("Restarting OpenVPN to activate multi-login enforcement...")
    try:
        subprocess.run(
            ["systemctl", "restart", "openvpn-server@server.service"], check=True
        )
        print("✓ OpenVPN restarted with multi-login enabled.")
    except Exception as e:
        print(f"Warning: Failed to auto-restart OpenVPN: {e}")
        print("Please manually run: systemctl restart openvpn-server@server")


def install_ovnode():
    if os.path.exists("/etc/openvpn"):
        print("OV-Node is already installed.")
        input("Press Enter to continue...")
        menu()
    try:
        subprocess.run(
            ["wget", "-4", "https://git.io/vpn", "-O", "/root/openvpn-install.sh"],
            check=True,
        )  # thanks to Nyr for ovpn installation script <3 https://github.com/Nyr/openvpn-install

        bash = pexpect.spawn(
            "/usr/bin/bash", ["/root/openvpn-install.sh"], encoding="utf-8", timeout=180
        )
        print("Running OV-Node installer...")

        prompts = [
            (r"Which IPv4 address should be used.*:", "1"),
            (r"Protocol.*:", "2"),
            (r"Port.*:", "1194"),
            (r"Select a DNS server for the clients.*:", "1"),
            (r"Enter a name for the first client.*:", "first_client"),
            (r"Press any key to continue...", ""),
        ]

        for pattern, reply in prompts:
            try:
                bash.expect(pattern, timeout=10)
                bash.sendline(reply)
            except pexpect.TIMEOUT:
                pass

        bash.expect(pexpect.EOF, timeout=None)
        bash.close()
        create_ccd()

        # OV-Node configuration prompts
        shutil.copy(".env.example", ".env")
        example_uuid = str(uuid4())
        SERVICE_PORT = input("OV-Node service port (default 2083): ")
        if SERVICE_PORT.strip() == "":
            SERVICE_PORT = "2083"
        API_KEY = input(f"OV-Node API key (example: {example_uuid}): ")
        if API_KEY.strip() == "":
            API_KEY = example_uuid

        replacements = {
            "SERVICE_PORT": SERVICE_PORT,
            "API_KEY": API_KEY,
        }

        lines = []
        with open(".env", "r") as f:
            for line in f:
                replaced = False
                for key, value in replacements.items():
                    if line.startswith(f"{key}"):
                        lines.append(f"{key}={value}\n")
                        replaced = True
                        break
                if not replaced:
                    lines.append(line)

        with open(".env", "w") as f:
            f.writelines(lines)

        run_ovnode()
        input(
            f"Successfully installed,\nApi key= {API_KEY}\nPort= {SERVICE_PORT}\nPress Enter to return to the menu..."
        )
        menu()

    except Exception as e:
        print("Error occurred during installation:", e)
        input("Press Enter to return to the menu...")
        menu()


def update_ovnode():
    if not os.path.exists("/opt/ov-node"):
        print("OV-Node is not installed.")
        input("Press Enter to return to the menu...")
        menu()
    try:
        repo = "https://api.github.com/repos/anonysec/ov/releases/latest"
        repo_subdir = "node"
        install_dir = "/opt/ov-node"
        env_file = os.path.join(install_dir, ".env")
        backup_env = "/tmp/ovnode_env_backup"

        response = requests.get(repo)
        response.raise_for_status()
        release = response.json()

        download_url = release["tarball_url"]
        filename = "/tmp/ov-node-latest.tar.gz"

        print(Fore.YELLOW + f"Downloading {download_url}" + Style.RESET_ALL)
        subprocess.run(["wget", "-O", filename, download_url], check=True)

        if os.path.exists(env_file):
            shutil.copy2(env_file, backup_env)

        if os.path.exists(install_dir):
            shutil.rmtree(install_dir)

        os.makedirs(install_dir, exist_ok=True)

        # Release tarball contains the whole anonysec/ov repo; extract only the
        # ov-node subfolder, stripping the wrapper dir + subfolder name.
        subprocess.run(
            [
                "tar",
                "-xzf",
                filename,
                "-C",
                install_dir,
                "--strip-components=2",
                "--wildcards",
                f"*/{repo_subdir}/*",
            ],
            check=True,
        )

        if os.path.exists(backup_env):
            shutil.move(backup_env, env_file)

        print(Fore.YELLOW + "Installing requirements..." + Style.RESET_ALL)
        os.chdir(install_dir)
        subprocess.run(["uv", "sync"], check=True)

        run_ovnode()
        print(Fore.GREEN + "OV-Node updated successfully!" + Style.RESET_ALL)
        input("Press Enter to return to the menu...")
        menu()

    except Exception as e:
        print(Fore.RED + f"Update failed: {e}" + Style.RESET_ALL)


def restart_ovnode():
    if not os.path.exists("/opt/ov-node") and not os.path.exists("/etc/openvpn"):
        print("OV-Node is not installed.")
        input("Press Enter to return to the menu...")
        menu()
    try:
        subprocess.run(["systemctl", "restart", "ov-node"], check=True)
        subprocess.run(["systemctl", "restart", "openvpn-server@server"], check=True)
        print(
            Fore.GREEN + "OV-Node and OpenVPN restarted successfully!" + Style.RESET_ALL
        )
        input("Press Enter to return to the menu...")
        menu()

    except Exception as e:
        print(Fore.RED + f"Restart failed: {e}" + Style.RESET_ALL)
        input("Press Enter to return to the menu...")
        menu()


def uninstall_ovnode():
    if not os.path.exists("/opt/ov-node"):
        print("OV-Node is not installed.")
        input("Press Enter to return to the menu...")
        menu()
    try:
        uninstall = input("Do you want to uninstall OV-Node? (y/n): ")
        if uninstall.lower() != "y":
            print("Uninstallation canceled.")
            menu()

        bash = pexpect.spawn("bash /root/openvpn-install.sh", timeout=300)
        subprocess.run("clear")
        print("Please wait...")

        bash.expect("Option:")
        bash.sendline("3")

        bash.expect("Confirm OpenVPN removal")
        bash.sendline("y")

        bash.expect(pexpect.EOF, timeout=60)
        bash.close()

        pexpect.run("rm -rf /etc/openvpn")

        print(
            Fore.GREEN
            + "OV-Node uninstallation completed successfully!"
            + Style.RESET_ALL
        )
        deactivate_ovnode()
        input("Press Enter to return to the menu...")
        menu()

    except Exception as e:
        print(
            Fore.RED
            + "Error occurred during uninstallation: "
            + str(e)
            + Style.RESET_ALL
        )
        input("Press Enter to return to the menu...")
        menu()


def run_ovnode() -> None:
    """Create and run a systemd service for OV-Node"""
    path = "/etc/systemd/system/ov-node.service"
    if os.path.exists(path):
        os.remove(path)
    service_content = """
[Unit]
Description=OV-Node App
After=network.target

[Service]
WorkingDirectory=/opt/ov-node
ExecStart=/root/.local/bin/uv run main.py
Restart=always
RestartSec=5
User=root
Environment="PATH=/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target

"""

    with open("/etc/systemd/system/ov-node.service", "w") as f:
        f.write(service_content)

    subprocess.run(["sudo", "systemctl", "daemon-reload"])
    subprocess.run(["sudo", "systemctl", "enable", "ov-node"])
    subprocess.run(["sudo", "systemctl", "start", "ov-node"])


def deactivate_ovnode() -> None:
    """Stop and disable the OV-Node systemd service"""
    subprocess.run(["sudo", "systemctl", "stop", "ov-node"])
    subprocess.run(["sudo", "systemctl", "disable", "ov-node"])
    subprocess.run(["rm", "-f", "/etc/systemd/system/ov-node.service"])


def change_node_config():
    """Change OV-Node port and/or API key without reinstalling."""
    env_file = "/opt/ov-node/.env"
    try:
        if not os.path.exists(env_file):
            print("OV-Node is not installed.")
            input("Press Enter to return to the menu...")
            menu()
            return

        current_port = ""
        current_key = ""
        with open(env_file, "r") as f:
            for line in f:
                line_stripped = line.strip().replace(" ", "")
                if line_stripped.startswith("SERVICE_PORT="):
                    current_port = line_stripped.split("=", 1)[1].strip()
                elif line_stripped.startswith("API_KEY="):
                    current_key = line_stripped.split("=", 1)[1].strip()

        print(Fore.CYAN + f"\nCurrent Node Config:" + Style.RESET_ALL)
        print(f"  Port   : {current_port or '2083'}")
        print(f"  API Key: {current_key[:12] + '...' if current_key else 'not set'}")

        print(Fore.YELLOW + "\nLeave blank to keep current value." + Style.RESET_ALL)

        new_port = input("New node service port (default 2083): ").strip()
        if new_port == "":
            new_port = current_port or "2083"
        if not new_port.isdigit() or not (1 <= int(new_port) <= 65535):
            print(Fore.RED + "Invalid port." + Style.RESET_ALL)
            input("Press Enter to return to the menu...")
            menu()
            return

        new_key = input("New API key (leave blank to keep): ").strip()
        if new_key == "":
            new_key = current_key

        lines = []
        found_port = False
        found_key = False
        with open(env_file, "r") as f:
            for line in f:
                lstripped = line.strip().replace(" ", "")
                if lstripped.startswith("SERVICE_PORT="):
                    lines.append(f"SERVICE_PORT = {new_port}\n")
                    found_port = True
                elif lstripped.startswith("API_KEY="):
                    lines.append(f"API_KEY = {new_key}\n")
                    found_key = True
                else:
                    lines.append(line)

        if not found_port:
            lines.append(f"SERVICE_PORT = {new_port}\n")
        if not found_key:
            lines.append(f"API_KEY = {new_key}\n")

        with open(env_file, "w") as f:
            f.writelines(lines)

        subprocess.run(["systemctl", "restart", "ov-node"], check=True)
        print(Fore.GREEN + f"\nNode config updated!" + Style.RESET_ALL)
        print(f"  Port: {new_port}")
        if new_key != current_key:
            print(f"  New API Key: {new_key}")
        print(Fore.YELLOW + "Remember to update the node in the panel if you changed the port or key." + Style.RESET_ALL)
        input("Press Enter to return to the menu...")
        menu()

    except Exception as e:
        print(Fore.RED + f"Failed to change node config: {e}" + Style.RESET_ALL)
        input("Press Enter to return to the menu...")
        menu()


def menu():
    subprocess.run("clear")
    print(Fore.BLUE + "=" * 34)
    print("Welcome to the OV-Node Installer")
    print("=" * 34 + Style.RESET_ALL)
    print()
    print("Please choose an option:\n")
    print("  1. Install")
    print("  2. Update")
    print("  3. Restart")
    print("  4. Change Config (port / api key)")
    print("  5. Uninstall")
    print("  6. Exit")
    print()
    choice = input(Fore.YELLOW + "Enter your choice: " + Style.RESET_ALL)

    if choice == "1":
        install_ovnode()
    elif choice == "2":
        update_ovnode()
    elif choice == "3":
        restart_ovnode()
    elif choice == "4":
        change_node_config()
    elif choice == "5":
        uninstall_ovnode()
    elif choice == "6":
        print(Fore.GREEN + "\nExiting..." + Style.RESET_ALL)
        sys.exit()
    else:
        print(Fore.RED + "\nInvalid choice. Please try again." + Style.RESET_ALL)
        input(Fore.YELLOW + "Press Enter to continue..." + Style.RESET_ALL)
        menu()


if __name__ == "__main__":
    menu()
