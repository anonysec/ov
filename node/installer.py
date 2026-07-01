import os
import sys
import tarfile
import subprocess
import shutil
from uuid import uuid4

import pexpect
from colorama import Fore, Style, init

init(autoreset=True)

APP_NAME = "ov-node"
INSTALL_DIR = f"/opt/{APP_NAME}"
REPO_URL = "https://github.com/anonysec/ov"
REPO_SUBDIR = "node"
MAIN_TARBALL_URL = f"{REPO_URL}/archive/refs/heads/main.tar.gz"


def get_uv_path() -> str:
    """Find uv in the common install locations used by the install script."""
    candidates = [
        shutil.which("uv"),
        os.path.expanduser("~/.local/bin/uv"),
        "/root/.local/bin/uv",
        "/usr/local/bin/uv",
        "/usr/bin/uv",
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return "uv"


def command_env() -> dict:
    env = os.environ.copy()
    extra = [os.path.expanduser("~/.local/bin"), "/root/.local/bin"]
    env["PATH"] = ":".join(extra + [env.get("PATH", "")])
    return env


def run_command(cmd, cwd=None, check=True):
    return subprocess.run(cmd, cwd=cwd, env=command_env(), check=check)


def extract_repo_subdir(tarball: str, subdir: str, destination: str) -> None:
    """Extract <github-wrapper>/<subdir>/... into destination, including dotfiles."""
    os.makedirs(destination, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tar:
        members = []
        for member in tar.getmembers():
            parts = member.name.split("/", 2)
            if len(parts) < 3 or parts[1] != subdir:
                continue
            member.name = parts[2]
            if member.name:
                members.append(member)
        if not members:
            raise RuntimeError(f"Could not find '{subdir}/' inside {tarball}")
        tar.extractall(destination, members)


def setup_multilogin() -> None:
    """Install the per-config simultaneous-login enforcement scripts."""
    server_conf = "/etc/openvpn/server/server.conf"
    scripts_dst_dir = "/etc/openvpn/scripts"
    limits_dir = "/etc/openvpn/limits"
    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "core", "scripts")

    os.makedirs(scripts_dst_dir, exist_ok=True)
    os.makedirs(limits_dir, exist_ok=True)

    connect_dst = os.path.join(scripts_dst_dir, "ovpanel-client-connect.sh")
    disconnect_dst = os.path.join(scripts_dst_dir, "ovpanel-client-disconnect.sh")

    for fname, dst in (
        ("ovpanel-client-connect.sh", connect_dst),
        ("ovpanel-client-disconnect.sh", disconnect_dst),
    ):
        src = os.path.join(src_dir, fname)
        if os.path.exists(src):
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o755)
        else:
            print(Fore.YELLOW + f"Warning: script not found: {src}" + Style.RESET_ALL)

    required = [
        "duplicate-cn",
        "script-security 2",
        f"client-connect {connect_dst}",
        f"client-disconnect {disconnect_dst}",
    ]

    if os.path.exists(server_conf):
        with open(server_conf, "r", encoding="utf-8") as f:
            content = f.read()
        existing = {line.strip() for line in content.splitlines()}
        to_add = [line for line in required if line not in existing]
        if to_add:
            with open(server_conf, "a", encoding="utf-8") as f:
                f.write("\n# ov-panel multi-login (per-config connection limit)\n")
                f.write("\n".join(to_add) + "\n")


def create_ccd() -> None:
    """Create OpenVPN CCD dir and make server.conf compatible with OV-Panel."""
    ccd_dir = "/etc/openvpn/ccd"
    server_conf = "/etc/openvpn/server/server.conf"

    os.makedirs(ccd_dir, exist_ok=True)
    os.chmod(ccd_dir, 0o755)

    if os.path.exists(server_conf):
        with open(server_conf, "r", encoding="utf-8") as f:
            lines = f.readlines()

        desired = [
            f"client-config-dir {ccd_dir}\n",
            "ccd-exclusive\n",
            "status /var/log/openvpn-status.log 10\n",
            "status-version 3\n",
        ]

        if not any(line.strip().startswith("client-config-dir ") for line in lines):
            lines.append("\n" + desired[0])
        if not any(line.strip() == "ccd-exclusive" for line in lines):
            lines.append(desired[1])
        if not any(line.strip().startswith("status ") for line in lines):
            lines.append(desired[2])
        if not any(line.strip().startswith("status-version") for line in lines):
            lines.append(desired[3])

        with open(server_conf, "w", encoding="utf-8") as f:
            f.writelines(lines)

    setup_multilogin()

    print("Restarting OpenVPN to activate CCD and multi-login enforcement...")
    try:
        run_command(["systemctl", "restart", "openvpn-server@server.service"])
        print(Fore.GREEN + "✓ OpenVPN restarted." + Style.RESET_ALL)
    except Exception as e:
        print(Fore.YELLOW + f"Warning: OpenVPN restart failed: {e}" + Style.RESET_ALL)
        print("Please run manually: systemctl restart openvpn-server@server")


def write_env(service_port: str, api_key: str) -> None:
    with open(".env", "w", encoding="utf-8") as f:
        f.write(
            "# This is the service port for the OV-Node\n"
            f"SERVICE_PORT={service_port}\n\n"
            "# This is an API key for connecting the master to the node\n"
            f"API_KEY={api_key}\n\n"
            "# Development\n"
            "# DOC=True\n"
            "# DEBUG=INFO\n"
        )


def install_ovnode():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    if os.path.exists("/etc/openvpn"):
        print("OpenVPN already exists. If this node is already installed, use Update/Restart.")
        input("Press Enter to return to the menu...")
        menu()
        return

    try:
        run_command(["wget", "-4", "https://git.io/vpn", "-O", "/root/openvpn-install.sh"])

        bash = pexpect.spawn(
            "/usr/bin/bash", ["/root/openvpn-install.sh"], encoding="utf-8", timeout=180
        )
        print("Running OpenVPN installer...")

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

        example_uuid = str(uuid4())
        service_port = input("OV-Node service port (default 2083): ").strip() or "2083"
        if not service_port.isdigit() or not (1 <= int(service_port) <= 65535):
            raise ValueError("Service port must be a number between 1 and 65535")

        api_key = input(f"OV-Node API key (example: {example_uuid}): ").strip() or example_uuid
        write_env(service_port, api_key)

        run_ovnode()
        input(
            f"Successfully installed,\nApi key= {api_key}\nPort= {service_port}\nPress Enter to return to the menu..."
        )
        menu()

    except Exception as e:
        print(Fore.RED + f"Error occurred during installation: {e}" + Style.RESET_ALL)
        input("Press Enter to return to the menu...")
        menu()


def update_ovnode():
    if not os.path.exists(INSTALL_DIR):
        print("OV-Node is not installed.")
        input("Press Enter to return to the menu...")
        menu()
        return

    filename = "/tmp/ov-node-main.tar.gz"
    backup_env = "/tmp/ov-node.env.bak"
    env_file = os.path.join(INSTALL_DIR, ".env")

    try:
        print(Fore.YELLOW + "Downloading latest code from main branch..." + Style.RESET_ALL)
        run_command(["wget", "--no-check-certificate", "-O", filename, MAIN_TARBALL_URL])

        if os.path.exists(env_file):
            shutil.copy2(env_file, backup_env)

        shutil.rmtree(INSTALL_DIR, ignore_errors=True)
        os.makedirs(INSTALL_DIR, exist_ok=True)
        extract_repo_subdir(filename, REPO_SUBDIR, INSTALL_DIR)

        if os.path.exists(backup_env):
            shutil.move(backup_env, env_file)

        print(Fore.YELLOW + "Installing requirements..." + Style.RESET_ALL)
        run_command([get_uv_path(), "sync", "--refresh"], cwd=INSTALL_DIR)

        os.chdir(INSTALL_DIR)
        create_ccd()
        run_ovnode()
        print(Fore.GREEN + "OV-Node updated successfully!" + Style.RESET_ALL)
        input("Press Enter to return to the menu...")
        menu()

    except Exception as e:
        print(Fore.RED + f"Update failed: {e}" + Style.RESET_ALL)
        input("Press Enter to return to the menu...")
        menu()


def restart_ovnode():
    if not os.path.exists(INSTALL_DIR) and not os.path.exists("/etc/openvpn"):
        print("OV-Node is not installed.")
        input("Press Enter to return to the menu...")
        menu()
        return
    try:
        run_command(["systemctl", "restart", "ov-node"])
        run_command(["systemctl", "restart", "openvpn-server@server"], check=False)
        print(Fore.GREEN + "OV-Node and OpenVPN restarted successfully!" + Style.RESET_ALL)
        input("Press Enter to return to the menu...")
        menu()
    except Exception as e:
        print(Fore.RED + f"Restart failed: {e}" + Style.RESET_ALL)
        input("Press Enter to return to the menu...")
        menu()


def uninstall_ovnode():
    try:
        if not os.path.exists(INSTALL_DIR) and not os.path.exists("/etc/openvpn"):
            print("OV-Node is not installed.")
            input("Press Enter to return to the menu...")
            menu()
            return

        uninstall = input("Do you want to uninstall OV-Node? This removes OpenVPN too. (y/n): ")
        if uninstall.lower() not in ("y", "yes"):
            print("Uninstallation canceled.")
            input("Press Enter to return to the menu...")
            menu()
            return

        print("Removing OV-Node service...")
        deactivate_ovnode()

        print("Removing OpenVPN...")
        if os.path.exists("/root/openvpn-install.sh"):
            try:
                bash = pexpect.spawn("bash /root/openvpn-install.sh", timeout=300)
                bash.expect("Option:")
                bash.sendline("3")
                bash.expect("Confirm OpenVPN removal")
                bash.sendline("y")
                bash.expect(pexpect.EOF, timeout=60)
                bash.close()
            except Exception:
                pass

        shutil.rmtree("/etc/openvpn", ignore_errors=True)
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)

        service_file = "/etc/systemd/system/ov-node.service"
        if os.path.exists(service_file):
            os.remove(service_file)
        run_command(["systemctl", "daemon-reload"], check=False)
        run_command(["systemctl", "reset-failed"], check=False)

        print(Fore.GREEN + "OV-Node uninstallation completed successfully!" + Style.RESET_ALL)
        input("Press Enter to return to the menu...")
        menu()

    except Exception as e:
        print(Fore.RED + f"Error occurred during uninstallation: {e}" + Style.RESET_ALL)
        input("Press Enter to return to the menu...")
        menu()


def run_ovnode() -> None:
    """Create/replace and run the systemd service for OV-Node."""
    service_file = "/etc/systemd/system/ov-node.service"
    uv_bin = get_uv_path()

    service_content = f"""
[Unit]
Description=OV-Node App
After=network.target

[Service]
WorkingDirectory={INSTALL_DIR}
ExecStart={uv_bin} run main.py
Restart=always
RestartSec=5
User=root
Environment="PATH=/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
"""

    with open(service_file, "w", encoding="utf-8") as f:
        f.write(service_content)

    run_command(["systemctl", "daemon-reload"], check=False)
    run_command(["systemctl", "enable", "ov-node"], check=False)
    run_command(["systemctl", "restart", "ov-node"], check=False)


def deactivate_ovnode() -> None:
    run_command(["systemctl", "stop", "ov-node"], check=False)
    run_command(["systemctl", "disable", "ov-node"], check=False)
    try:
        os.remove("/etc/systemd/system/ov-node.service")
    except FileNotFoundError:
        pass


def menu():
    subprocess.run("clear")
    print(Fore.BLUE + "=" * 34)
    print("Welcome to the OV-Node Installer  v1.3.0")
    print("=" * 34 + Style.RESET_ALL)
    print()
    print("Please choose an option:\n")
    print("  1. Install")
    print("  2. Update")
    print("  3. Restart")
    print("  4. Uninstall")
    print("  5. Exit")
    print()
    choice = input(Fore.YELLOW + "Enter your choice: " + Style.RESET_ALL)

    if choice == "1":
        install_ovnode()
    elif choice == "2":
        update_ovnode()
    elif choice == "3":
        restart_ovnode()
    elif choice == "4":
        uninstall_ovnode()
    elif choice == "5":
        print(Fore.GREEN + "\nExiting..." + Style.RESET_ALL)
        sys.exit(0)
    else:
        print(Fore.RED + "\nInvalid choice. Please try again." + Style.RESET_ALL)
        input(Fore.YELLOW + "Press Enter to continue..." + Style.RESET_ALL)
        menu()


if __name__ == "__main__":
    menu()
