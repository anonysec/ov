import pexpect
import re
import os

from core.logger import logger
from core.schema.all_schemas import UsersUsage


script_path = "/root/openvpn-install.sh"

# Where per-client simultaneous-login limits are stored.
# Kept separate from the CCD dir because CCD files are wiped on
# deactivate/reactivate, while the limit should survive that.
LIMITS_DIR = "/etc/openvpn/limits"


def set_user_limit(name: str, max_logins: int) -> bool:
    """Persist the max simultaneous logins for a client.

    max_logins: 1 = single login (default), 0 = unlimited.
    The connect-time enforcement script reads this file.
    """
    try:
        if max_logins is None:
            return True
        max_logins = int(max_logins)
        if max_logins < 0:
            max_logins = 0
        os.makedirs(LIMITS_DIR, exist_ok=True)
        with open(os.path.join(LIMITS_DIR, name), "w") as f:
            f.write(str(max_logins))
        logger.info("Set login limit for '%s' to %s", name, max_logins)
        return True
    except Exception as e:
        logger.error("Error setting login limit for '%s': %s", name, e)
        return False


def remove_user_limit(name: str) -> None:
    """Remove the stored limit file for a client (used on delete)."""
    try:
        path = os.path.join(LIMITS_DIR, name)
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        logger.error("Error removing login limit for '%s': %s", name, e)


def create_user_on_server(name, max_logins: int = 1) -> bool:
    try:
        if not os.path.exists(script_path):
            logger.error("script not found on ")
            return False

        env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
        bash = pexpect.spawn(
            "/usr/bin/bash",
            [script_path],
            env=env,
            encoding="utf-8",
            timeout=120,
        )

        bash.expect(r"Option:", timeout=90)
        bash.sendline("1")

        bash.expect(r"Name:", timeout=90)
        bash.sendline(name)
        bash.expect(pexpect.EOF, timeout=180)

        bash.close()
        ccd_file = f"/etc/openvpn/ccd/{name}"
        with open(ccd_file, "w") as f:
            f.write("")

        # Persist the simultaneous-login limit for this new client.
        set_user_limit(name, max_logins if max_logins is not None else 1)

        return True

    except pexpect.TIMEOUT:
        logger.error("Timeout occurred while executing script!")
        return False
    except pexpect.EOF:
        logger.error("Script closed earlier than expected!")
        return False
    except Exception as e:
        logger.error(f"Error occurred: {e}")
        return False


def delete_user_on_server(name) -> bool | str:
    try:
        if not os.path.exists(script_path):
            logger.error("script not found at %s", script_path)
            return False

        env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
        bash = pexpect.spawn(
            "/usr/bin/bash", [script_path], env=env, encoding="utf-8", timeout=120
        )

        try:
            bash.expect(r"Option:|Select an option:", timeout=20)
        except pexpect.TIMEOUT:
            logger.warning("Did not see main menu prompt, attempting to continue")

        bash.sendline("2")

        try:
            bash.expect(
                r"Select the client to revoke:|Select the client to revoke", timeout=20
            )
        except pexpect.TIMEOUT:
            logger.info("Didn't match full header")

        bash.expect(r"Client:", timeout=20)
        list_output = bash.before

        pattern = re.compile(r"\s*(\d+)\)\s*(.+)")
        matches = pattern.findall(list_output)

        user_number = None
        for num, user in matches:
            if user.strip() == name:
                user_number = num
                break

        if not user_number:
            logger.error("User '%s' not found for delete!", name)
            bash.close(force=True)
            return "not_found"

        logger.info("Revoking user '%s' -> number %s", name, user_number)
        bash.sendline(user_number)

        try:
            bash.expect(
                r"Confirm .*revocation\?.*\[y/N\]:|Confirm .*revocation\?.*:|Confirm .*revocation\?",
                timeout=20,
            )
            bash.sendline("y")
        except pexpect.TIMEOUT:
            logger.warning("Confirmation prompt not seen; trying to continue")

        bash.expect(pexpect.EOF, timeout=120)
        bash.close()

        # remove local .ovpn file if exists
        file_to_delete = f"/root/{name}.ovpn"
        if os.path.exists(file_to_delete):
            try:
                os.remove(file_to_delete)
                logger.info("Removed %s", file_to_delete)
            except Exception as e:
                logger.error("Error deleting file %s: %s", file_to_delete, e)
                return True

        ccd_file = f"/etc/openvpn/ccd/{name}"
        if os.path.exists(ccd_file):
            try:
                os.remove(ccd_file)
                logger.info("Removed %s", ccd_file)
            except Exception as e:
                logger.error("Error deleting file %s: %s", ccd_file, e)
                return True

        # Drop the stored login limit for this client.
        remove_user_limit(name)

        return True

    except Exception as e:
        logger.exception("Error in delete_user_on_server: %s", e)
        return False


def change_user_status(name: str, status: str) -> bool:
    ccd_file = f"/etc/openvpn/ccd/{name}"
    if status == "deactivate":
        if os.path.exists(ccd_file):
            try:
                os.remove(ccd_file)
                restart_openvpn_service()
                logger.info("Removed %s", ccd_file)
            except Exception as e:
                logger.error("Error deleting file %s: %s", ccd_file, e)
                return False
        return True
    elif status == "activate":
        try:
            os.makedirs("/etc/openvpn/ccd", exist_ok=True)
            with open(ccd_file, "w") as f:
                f.write("")
            logger.info("Created %s", ccd_file)
            restart_openvpn_service()
            return True
        except Exception as e:
            logger.error("Error creating file %s: %s", ccd_file, e)
            return False


def restart_openvpn_service() -> bool:
    try:
        os.system("systemctl restart openvpn-server@server")
        logger.info("OpenVPN service restarted successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to restart OpenVPN service: {e}")
        return False


async def download_ovpn_file(name: str) -> str | None:
    """This function returns the path of the ovpn file for downloading"""
    file_path = f"/root/{name}.ovpn"
    if os.path.exists(file_path):
        return file_path
    else:
        create_user_on_server(name)
        return await download_ovpn_file(name)


def get_users_usage() -> UsersUsage | None:
    users = {}
    sessions: dict = {}
    file_path = "/var/log/openvpn-status.log"
    with open(file_path) as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if line.startswith("CLIENT_LIST") and not line.startswith(
            "CLIENT_LIST,Common Name"
        ):
            parts = line.split(",")
            username = parts[1]
            real_address = parts[2]  # IP:port, unique per active session
            bytes_received = int(parts[5])
            bytes_sent = int(parts[6])
            total_bytes = bytes_received + bytes_sent

            # Per-CN total (a multi-login user has several rows; sum them).
            users[username] = users.get(username, 0) + total_bytes

            # Per-session breakdown so the panel can diff each session
            # independently and avoid double-counting when one of several
            # simultaneous sessions disconnects.
            sessions.setdefault(username, {})[real_address] = total_bytes

    if users:
        return UsersUsage(users=users, sessions=sessions)
    else:
        return None
