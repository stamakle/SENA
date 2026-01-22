
# utils_cmd.py (Final Version)
"""
Enhanced SSH and firmware update utilities:
- Secure SSH with TOFU
- Atomic SFTP uploads
- Configurable SSL for HTTPS downloads
- SHA-256 checksum logging
- Structured parsing for Windows and Linux NVMe
- Full firmware update helpers for Windows & Linux
"""

from __future__ import annotations
import hashlib, json, logging, os, shlex, tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import paramiko, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Regex-based token matching helper for utils_cmd
def _token_match(candidate: str, tokens: list[str]) -> bool:
    c = candidate.lower()
    for tok in tokens:
        if not tok:
            continue
        if tok.startswith('/') and tok.endswith('/'):
            try:
                if re.search(tok[1:-1], candidate, flags=re.IGNORECASE):
                    logger.debug("Regex match: %s on %s", tok, candidate)
                    print(f"[DEBUG] Regex match: {tok} on {candidate}")
                    return True
            except re.error:
                logger.warning("Invalid regex token: %s", tok)
                print(f"[WARN] Invalid regex token: {tok}")
        else:
            if tok.lower() in c:
                logger.debug("Substring match: %s in %s", tok, candidate)
                print(f"[DEBUG] Substring match: {tok} in {candidate}")
                return True
    return False


# Constants
_DEFAULT_CONNECT_TIMEOUT = 10
_DEFAULT_COMMAND_TIMEOUT = 300
_HTTP_TIMEOUT = (5, 60)
_CHUNK_SIZE = 1024 * 1024
VERIFY_SSL = os.getenv("VERIFY_SSL", "").lower() == "true"

# HTTP session with retry
retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
adapter = HTTPAdapter(max_retries=retry_strategy)
http_session = requests.Session()
http_session.mount("https://", adapter)
http_session.mount("http://", adapter)

def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"

@dataclass
class SSHConfig:
    host: str
    username: str
    password: Optional[str] = None
    pkey: Optional[paramiko.PKey] = None
    port: int = 22
    look_for_keys: bool = True
    allow_agent: bool = True
    known_hosts: Optional[str] = None
    trust_first_use: bool = False

class SSHClientManager:
    def __init__(self, cfg: SSHConfig):
        self.cfg = cfg
        self.client: Optional[paramiko.SSHClient] = None

    def _load_known_hosts(self, client: paramiko.SSHClient):
        path = Path(self.cfg.known_hosts).expanduser() if self.cfg.known_hosts else Path.home() / ".ssh" / "known_hosts"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(mode=0o600, exist_ok=True)
        try: client.load_host_keys(str(path))
        except: pass
        try: client.load_system_host_keys()
        except: pass

    def __enter__(self):
        client = paramiko.SSHClient()
        self._load_known_hosts(client)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(hostname=self.cfg.host, port=self.cfg.port, username=self.cfg.username,
                           password=self.cfg.password, pkey=self.cfg.pkey, look_for_keys=self.cfg.look_for_keys,
                           allow_agent=self.cfg.allow_agent, timeout=_DEFAULT_CONNECT_TIMEOUT)
            self.client = client
            return client
        except paramiko.SSHException as e:
            if "not found in known_hosts" in str(e) and self.cfg.trust_first_use:
                consent = input(f"Host {self.cfg.host} not in known_hosts. Trust and add? (yes/no): ").strip().lower()
                if consent != "yes": raise RuntimeError("TOFU declined")
                learner = paramiko.SSHClient()
                learner.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                learner.connect(hostname=self.cfg.host, port=self.cfg.port, username=self.cfg.username,
                                password=self.cfg.password, timeout=_DEFAULT_CONNECT_TIMEOUT)
                hostkey = learner.get_transport().get_remote_server_key()
                kh_path = Path(self.cfg.known_hosts or (Path.home() / ".ssh" / "known_hosts")).expanduser()
                kh_path.parent.mkdir(parents=True, exist_ok=True)
                with kh_path.open("a", encoding="ascii") as f:
                    f.write(f"{self.cfg.host} {hostkey.get_name()} {hostkey.get_base64()}\n")
                learner.close()
                return self.__enter__()
            raise

    def __exit__(self, exc_type, exc, tb):
        if self.client: self.client.close()

class Executors:
    def __init__(self, ip: str, username: str, password: Optional[str] = None, *, is_windows=False,
                 pkey=None, known_hosts=None, trust_first_use=False):
        self.cfg = SSHConfig(host=ip, username=username, password=password, pkey=pkey,
                             known_hosts=known_hosts, trust_first_use=trust_first_use)
        self.is_windows = is_windows

    def execute_ssh_command(self, command: str, *, timeout=_DEFAULT_COMMAND_TIMEOUT) -> Tuple[str, str, int]:
        with SSHClientManager(self.cfg) as client:
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            return stdout.read().decode(errors="replace").strip(), stderr.read().decode(errors="replace").strip(), stdout.channel.recv_exit_status()

    def _ensure_remote_dir(self, remote_path: str):
        remote_dir = os.path.dirname(remote_path) or "."
        cmd = f"mkdir -p {shlex.quote(remote_dir)}" if not self.is_windows else \
              f'powershell -NoProfile -NonInteractive -Command "New-Item -ItemType Directory -Path \\"{remote_dir}\\" -Force"'
        self.execute_ssh_command(cmd)

    def _sftp_put_atomic(self, local_path: str, remote_path: str):
        self._ensure_remote_dir(remote_path)
        with SSHClientManager(self.cfg) as client:
            sftp = client.open_sftp()
            tmp = remote_path + ".tmp"
            sftp.put(local_path, tmp)
            try: sftp.posix_rename(tmp, remote_path)
            except IOError: sftp.rename(tmp, remote_path)
            sftp.close()

    def download_firmware(self, url: str, remote_path: str, headers: dict) -> bool:
        try:
            with http_session.get(url, headers=headers, verify=VERIFY_SSL, stream=True, timeout=_HTTP_TIMEOUT) as resp:
                resp.raise_for_status()
                hasher = hashlib.sha256()
                with tempfile.NamedTemporaryFile(prefix="fw_", delete=False) as tmp:
                    for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                        if chunk: tmp.write(chunk); hasher.update(chunk)
                    local_file = tmp.name
            self._sftp_put_atomic(local_file, remote_path)
            logger.info("Uploaded firmware to %s (sha256=%s)", remote_path, hasher.hexdigest())
            os.remove(local_file)
            return True
        except Exception as e:
            logger.error("Firmware transfer failed: %s", e)
            return False

    
    def list_windows_disks(self) -> list:
        # PowerShell command to get physical disks and their boot status
        cmd = (
            'powershell -NoProfile -NonInteractive -Command '
            '"$bootDisk = (Get-Partition | Where-Object { $_.IsBoot }).DiskNumber; '
            'Get-PhysicalDisk | ForEach-Object { '
            '    $disk = $_; '
            '    $diskNumber = (Get-Disk -UniqueId $disk.UniqueId).Number; '
            '    if ($diskNumber -ne $bootDisk) { '
            '        [PSCustomObject]@{ '
            '            FriendlyName = $disk.FriendlyName; '
            '            Model = $disk.Model; '
            '            SerialNumber = $disk.SerialNumber; '
            '            FirmwareVersion = $disk.FirmwareVersion; '
            '            UniqueId = $disk.UniqueId '
            '        } '
            '    } '
            '} | ConvertTo-Json"'
        )

        out, _, rc = self.execute_ssh_command(cmd)
        if rc != 0 or not out.strip():
            return []

        try:
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            return [
                {
                    "friendly": d.get("FriendlyName", ""),
                    "model": d.get("Model", ""),
                    "serial": d.get("SerialNumber", ""),
                    "fwver": d.get("FirmwareVersion", ""),
                    "uniqueid": d.get("UniqueId", "")
                }
                for d in data
            ]
        except:
            return []

    def _detect_boot_nvme(self) -> Optional[str]:
        """
        Detect the NVMe base device that holds / or /boot using lsblk JSON.
        Returns the base token (e.g., 'nvme0n1') or None if not found.
        """
        out, err, rc = self.execute_ssh_command('bash -lc "lsblk -J -o NAME,MOUNTPOINT"')
        if rc != 0 or not out.strip():
            return None
        try:
            data = json.loads(out)
        except Exception:
            return None

        def walk(nodes) -> Optional[str]:
            for n in nodes or []:
                name = n.get('name', '')
                mount = n.get('mountpoint')
                # Look for mounts at / or /boot on nvme devices
                if mount in ('/', '/boot') and name.startswith('nvme'):
                    base = name.split('p')[0]
                    return base
                child = walk(n.get('children'))
                if child:
                    return child
            return None

        return walk(data.get('blockdevices'))
    
    # ---- Discovery Helpers ----
    
    def list_linux_nvme(self) -> list:
        """
        Return a list of dicts parsed from `nvme list -o json`:
        {dev (device path), model (ModelNumber/mn), serial (SerialNumber/sn), fwver (Firmware/fr)}.
        Falls back to `nvme list` + `nvme id-ctrl` if JSON is unavailable.
        Printing format per device:
        Device: <dev or None> \n Model: <model> \n Serial: <serial> \n FW: <fwver>
        """
        boot_dev = self._detect_boot_nvme()
        if boot_dev:
            logger.info("Boot device detected and will be excluded: %s", boot_dev)

        out, err, rc = self.execute_ssh_command("sudo nvme list -o json")
        if rc == 0 and out.strip():
            try:
                data = json.loads(out)
            except Exception as e:
                logger.warning('Failed to parse nvme JSON: %s', e)
            else:
                devices_json = data.get('Devices') or data.get('devices') or []
                if boot_dev:
                    def _is_boot_entry(d: dict) -> bool:
                        dp = d.get('DevicePath') or d.get('name') or ''
                        tok = dp.split('/')[-1]
                        return tok == boot_dev
                    devices_json = [d for d in devices_json if not _is_boot_entry(d)]
                devices: list = []

                def _print_and_append(name, model, serial, fw):
                    dev_path = f"/dev/{name}" if name else None
                    print(f"Device: {dev_path if dev_path else 'None'} \nModel: {model} \nSerial: {serial} \nFW: {fw}")
                    devices.append({'dev': dev_path if dev_path else None,
                                    'model': model or '',
                                    'serial': serial or '',
                                    'fwver': fw or ''})
                for devinfo in devices_json:
                    top_name = devinfo.get('DevicePath') or devinfo.get('name') or None
                    top_serial = devinfo.get('SerialNumber') or devinfo.get('sn') or ''
                    top_model = devinfo.get('ModelNumber') or devinfo.get('mn') or ''
                    top_fw = devinfo.get('Firmware') or devinfo.get('fr') or ''
                    if top_name:
                        name_token = top_name.split('/')[-1]
                        if boot_dev and name_token == boot_dev:
                            continue
                        _print_and_append(name_token, top_model, top_serial, top_fw)
                    subsystems = devinfo.get('Subsystems') or []
                    for subs in subsystems:
                        controllers = subs.get('Controllers') or []
                        for ctrl in controllers:
                            ctrl_serial = ctrl.get('SerialNumber') or ctrl.get('sn') or top_serial
                            ctrl_model = ctrl.get('ModelNumber') or ctrl.get('mn') or top_model
                            ctrl_fw = ctrl.get('Firmware') or ctrl.get('fr') or top_fw
                            namespaces = ctrl.get('Namespaces') or []
                            if namespaces:
                                for ns in namespaces:
                                    ns_name = ns.get('NameSpace') or ns.get('name') or None
                                    if boot_dev and ns_name == boot_dev:
                                        continue
                                    _print_and_append(ns_name, ctrl_model, ctrl_serial, ctrl_fw)
                            else:
                                _print_and_append(None, ctrl_model, ctrl_serial, ctrl_fw)
                if devices:
                    return [d for d in devices if d['dev'] is not None]
        # Fallback
        out2, err2, rc2 = self.execute_ssh_command('sudo nvme list')
        if rc2 != 0:
            return []
        devices = []
        for line in out2.splitlines():
            if line.strip().startswith('/dev/nvme'):
                dev = line.split()[0]
                token = dev.split('/')[-1]
                if boot_dev and token == boot_dev:
                    continue
                devices.append({'dev': dev})
        enriched = []
        for d in devices:
            dev = d['dev']
            out3, err3, rc3 = self.execute_ssh_command(f"sudo nvme id-ctrl {shlex.quote(dev)}")
            model = serial = fw = ''
            if rc3 == 0:
                for ln in out3.splitlines():
                    s = ln.strip()
                    if s.startswith('mn'):
                        model = s.split(':', 1)[1].strip()
                    elif s.startswith('sn'):
                        serial = s.split(':', 1)[1].strip()
                    elif s.startswith('fr'):
                        fw = s.split(':', 1)[1].strip()
            d.update({'model': model, 'serial': serial, 'fwver': fw})
            enriched.append(d)
        return enriched

    def select_targets(self, is_windows: bool, candidate_tokens: list) -> list:
        if is_windows:
            items = self.list_windows_disks()
            return [{"name": it["friendly"], "uniqueid": it["uniqueid"]}
                    for it in items if _token_match(f"{it['friendly']} {it['model']} {it['serial']} {it['fwver']}", candidate_tokens)]
        else:
            items = self.list_linux_nvme()
            return [it["dev"] for it in items if _token_match(" ".join(it.values()), candidate_tokens)]
	
    def update_firmware_windows(self, remote_path: str, firmware_file: str, candidate_tokens: List[str]) -> List[str]:
        targets = [d for d in self.list_windows_disks() if any(tok.lower() in f"{d['friendly']} {d['model']} {d['serial']} {d['fwver']}".lower() for tok in candidate_tokens)]
        updated = []
        if not targets: return updated

        def get_fwver(name): 
            ps = f"(Get-PhysicalDisk -FriendlyName {_ps_quote(name)}).FirmwareVersion"
            out, _, rc = self.execute_ssh_command(f"powershell -NoProfile -NonInteractive -Command {_ps_quote(ps)}")
            return out.strip() if rc==0 else ""
          
        

        def do_update(t):
            try:
                before = get_fwver(t["friendly"])
                # Detect supported slots
                slot_cmd = f"Get-StorageFirmwareInfo -UniqueId {_ps_quote(t['uniqueid'])} | ConvertTo-Json"
                slot_out, _, rc_slot = self.execute_ssh_command(f"powershell -NoProfile -NonInteractive -Command {_ps_quote(slot_cmd)}")
                slots = [2]  # default
                if rc_slot == 0 and slot_out.strip():
                    try:
                        info = json.loads(slot_out)
                        slots = info.get("SupportedSlotNumbers", [2])
                    except:
                        pass
                ok = False
                msg = ""
                after = before
                for slot in slots:
                    ps = (f"Update-StorageFirmware -UniqueId {_ps_quote(t['uniqueid'])} "
                        f"-ImagePath {_ps_quote(remote_path)} -SlotNumber {slot} -Verbose -ErrorAction Stop")
                    out, err, rc = self.execute_ssh_command(f'powershell -NoProfile -NonInteractive -Command "{ps}"')
                    if rc == 0:
                        after = get_fwver(t["friendly"])
                        ok = True
                        msg = out or err
                        break
                    else:
                        msg = err or out
                return t["friendly"], ok, before, after, msg
            except Exception as e:
                return t.get("friendly", "UNKNOWN"), False, "", "", f"Exception: {e}"



        with ThreadPoolExecutor(max_workers=min(4,len(targets))) as pool:
            for fut in as_completed({pool.submit(do_update,t):t for t in targets}):
                name, ok, before, after, msg = fut.result()
                if ok and after!=before: updated.append(name); print(f"SUCCESS: {name} FW {before}->{after}")
                elif ok: print(f"PASS: {name} FW unchanged ({before})")
                else: print(f"FAILED: {name} -> {msg}")
        return updated

    def update_firmware_linux(self, remote_path: str, firmware_file: str, candidate_tokens: List[str]) -> List[str]:
        updated = []
        devices = self.select_targets(is_windows=False, candidate_tokens=candidate_tokens)
        if not devices:
            return updated

        def get_fwver(dev: str) -> str:
            out, _, rc = self.execute_ssh_command(f"sudo nvme id-ctrl {shlex.quote(dev)}")
            if rc != 0:
                return ""
            for ln in out.splitlines():
                if ln.strip().startswith("fr"):
                    return ln.split(":", 1)[1].strip()
            return ""

        def do_update(dev: str):
            before = get_fwver(dev)
            cmds = [f"sudo nvme fw-download --fw {shlex.quote(remote_path)} {shlex.quote(dev)}",
                    f"sudo nvme fw-commit -s 2 -a 3 {shlex.quote(dev)}"]
            ok = True
            last_output = ""
            for c in cmds:
                out, err, rc = self.execute_ssh_command(c)
                last_output = out or err
                if rc != 0:
                    ok = False
                    break
            after = get_fwver(dev)
            return dev, ok, before, after, last_output

        with ThreadPoolExecutor(max_workers=min(6, len(devices))) as pool:
            futures = {pool.submit(do_update, d): d for d in devices}
            for fut in as_completed(futures):
                dev, ok, before, after, msg = fut.result()
                if ok and after and after != before:
                    updated.append(dev)
                    print(f"SUCCESS: {dev} FW {before} -> {after}")
                elif ok:
                    print(f"PASS: {dev} FW unchanged ({before})")
                else:
                    print(f"FAILED: {dev} -> {msg}")
        return updated

    @staticmethod
    def slice_number(string: str) -> str:
        return "".join(string.split("-")[-3:])

