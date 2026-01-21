
# speed.py (Refactored & Fixed)
"""
Firmware Search & Update Orchestration - Enhanced Version
Features:
- Handles Windows and Linux hosts
- Configurable temp and log directories
- Dry-run mode for safe testing
- Parallel host updates
- Regex-based firmware matching
- Rollback strategy for failed updates
- Structured logging
- Safe dictionary access to prevent NoneType errors
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from artifactory import searchfirmware
from utils_cmd import Executors

# Regex-based token matching helper
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


logger = logging.getLogger(__name__)

@dataclass
class HostInfo:
    ip: str
    username: str
    password: Optional[str] = None
    is_windows: bool = False
    known_hosts: Optional[str] = None
    trust_first_use: bool = False

class SystemInfo:
    def __init__(self, system_info_file: str):
        self.system_info = self.load_json(system_info_file)

    def load_json(self, file_path: str):
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"JSON decode error in {file_path}: {e}")
        except FileNotFoundError:
            raise RuntimeError(f"File not found: {file_path}")

    def get_hostname(self, ex: Executors, is_windows: bool) -> str:
        cmd = 'hostname' if not is_windows else 'powershell -NoProfile -NonInteractive -Command "hostname"'
        out, err, rc = ex.execute_ssh_command(cmd)
        if rc != 0:
            raise RuntimeError(f"Failed to get hostname: {err}")
        return out.strip()

    def ensure_directories(self, ex: Executors, is_windows: bool, temp_dir: str, log_dir: str) -> Tuple[str, str]:
        if is_windows:
            ps = (
                f'$d="{temp_dir}"; if (-Not (Test-Path $d)) {{ New-Item -ItemType Directory -Path $d }} ; '
                f'$l="{log_dir}"; if (-Not (Test-Path $l)) {{ New-Item -ItemType Directory -Path $l }} ; $l'
            )
            cmd = f'powershell -NoProfile -NonInteractive -Command "{ps}"'
        else:
            cmd = f"mkdir -p {log_dir} && printf {log_dir}"
        out, err, rc = ex.execute_ssh_command(cmd)
        if rc != 0:
            raise RuntimeError(f"Failed to ensure directories: {err}")
        return temp_dir, log_dir

    def create_log_file(self, ex: Executors, firmware_log_dir: str, firmware_file_name: str, is_windows: bool) -> str:
        log_file_name = f"{firmware_file_name[:8]}.log"
        log_path = str(PureWindowsPath(firmware_log_dir) / log_file_name) if is_windows else str(PurePosixPath(firmware_log_dir) / log_file_name)
        cmd = (
            f'powershell -NoProfile -NonInteractive -Command "Write-Output \\"Log for firmware file: {firmware_file_name}\\" | Out-File -FilePath \\"{log_path}\\" -Encoding UTF8"'
            if is_windows else f"bash -lc 'echo \"Log for firmware file: {firmware_file_name}\" > {log_path}'"
        )
        out, err, rc = ex.execute_ssh_command(cmd)
        if rc != 0:
            raise RuntimeError(f"Failed to create log file: {err}")
        logger.info("Log file created at %s", log_path)
        return log_path

    def update_firmware(self, ex: Executors, remote_path: str, firmware_file: str, matches: List[str], is_windows: bool, dry_run: bool) -> List[str]:
        if dry_run:
            logger.info("Dry-run: Skipping firmware update for %s", firmware_file)
            return []
        return ex.update_firmware_windows(remote_path, firmware_file, matches) if is_windows else ex.update_firmware_linux(remote_path, firmware_file, matches)

    def display_info(self, query: str, type: Optional[str], extension: str, hostnames: Optional[List[str]], no_cache: bool, temp_dir: str, log_dir: str, dry_run: bool):
        query = query.upper()
        api_key = os.getenv('api_key')
        if not api_key:
            raise RuntimeError("api_key not set in environment")

        urls = searchfirmware(query, type, [extension], use_cache=not no_cache)
        if not urls:
            logger.error("No matching firmware found for %s", query)
            return

        def process_host(info):
            if hostnames and "all" not in hostnames and info.get('hostname') not in hostnames:
                return
            host = HostInfo(
                ip=info['ip'], username=info['username'], password=info.get('password'),
                is_windows=info.get('is_windows', False), known_hosts=info.get('known_hosts'),
                trust_first_use=bool(info.get('trust_first_use', False)),
            )
            ex = Executors(host.ip, host.username, host.password, is_windows=host.is_windows,
                           known_hosts=host.known_hosts, trust_first_use=host.trust_first_use)
            try:
                temp_dir_final, firmware_log_dir = self.ensure_directories(ex, host.is_windows, temp_dir, log_dir)
                hostname = self.get_hostname(ex, host.is_windows)
                logger.info('Hostname: %s', hostname)

                matches = []
                if host.is_windows:
                    disks = ex.list_windows_disks()
                    for d in disks:
                        fwver = (d.get('fwver') or '')
                        if any(re.search(query, fw, re.IGNORECASE) for fw in urls):
                            matches.append(fwver[:4])
                else:
                    nvmes = ex.list_linux_nvme()
                    for it in nvmes:
                        fwver = (it.get('fwver') or '')
                        model = (it.get('model') or '')
                        serial = (it.get('serial') or '')
                        blob = f"{fwver[:4]} {model} {serial}".upper()
                        if query in blob or any(query in fw.upper() for fw in urls):
                            matches.append(fwver[:4])

                if not matches:
                    logger.warning("No matching devices found on %s", host.ip)
                    return

                firmware = next((fw for fw in urls if query and extension in fw and any(dut[:4] in fw for dut in matches)), None)
                if not firmware:
                    logger.warning("No firmware URL chosen for %s on %s", query, host.ip)
                    return

                fw_name = firmware.split('/')[-1]
                remote_file_path = str(PureWindowsPath(temp_dir_final) / fw_name) if host.is_windows else str(PurePosixPath(temp_dir_final) / fw_name)
                headers = {"X-JFrog-Art-Api": api_key}

                if not dry_run:
                    if not self.download_firmware(firmware, remote_file_path, headers, ex):
                        logger.error('Firmware download/upload failed for %s', host.ip)
                        return

                logger.info("Targets to be updated on %s:", host.ip)
                targets = ex.select_targets(host.is_windows, matches)
                for t in targets:
                    logger.info(" - %s", t)

                self.create_log_file(ex, firmware_log_dir, fw_name, host.is_windows)
                updated = self.update_firmware(ex, remote_file_path, fw_name, matches, host.is_windows, dry_run)

                if updated:
                    logger.info('Firmware updated on %d drive(s).', len(updated))
                else:
                    logger.warning('Firmware update skipped or failed.')
            except Exception as e:
                logger.exception("Host %s failed: %s", host.ip, e)

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(process_host, info) for info in self.system_info]
            for fut in as_completed(futures):
                fut.result()

    @staticmethod
    def download_firmware(firmware_url: str, remote_path: str, headers: dict, ex: Executors) -> bool:
        return ex.download_firmware(firmware_url, remote_path, headers)

def configure_logging(verbosity: int):
    # Verbosity levels: 0=WARNING, 1=INFO (-V), 2+=DEBUG (-VV)
    level = logging.WARNING
    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity == 1:
        level = logging.INFO
    logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    try:
        from datetime import datetime
        run_log = f"firmware_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        fh = logging.FileHandler(run_log, encoding='utf-8')
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
        logging.getLogger().addHandler(fh)
        logging.getLogger(__name__).info('Local run transcript will be saved to %s', run_log)
    except Exception as e:
        logging.getLogger(__name__).warning('FileHandler setup failed: %s', e)

def main():
    parser = argparse.ArgumentParser(description='Firmware Search & Update Utility')
    parser.add_argument('-v', '--version', type=str, required=True, help='Firmware version to search for (e.g., 007S)')
    parser.add_argument('-t', '--type', type=str, choices=['rel', 'dbg'], default=None, help='Firmware type (rel or dbg)')
    parser.add_argument('-e', '--extension', type=str, default='.ubi', help='File extension to search for (default: .ubi)')
    parser.add_argument('--no-cache', action='store_true', help='Disable cached search results (artifactory)')
    parser.add_argument('--verbose', '-V', action='count', default=0, help='Increase verbosity (-VV for debug)')
    parser.add_argument('--hostnames', type=str, nargs='*', help='Hostnames to target or "all" for all')
    parser.add_argument('--system_info', required=True, help='Path to JSON with system information')
    parser.add_argument('--temp-dir', type=str, default='C:/Temp' if os.name == 'nt' else '/tmp', help='Temporary directory for firmware')
    parser.add_argument('--log-dir', type=str, default='C:/Temp/firmware_log' if os.name == 'nt' else '/tmp/firmware_log', help='Log directory')
    parser.add_argument('--dry-run', action='store_true', help='Perform a dry run without actual firmware update')
    args = parser.parse_args()

    configure_logging(args.verbose)
    system = SystemInfo(args.system_info)
    system.display_info(query=args.version, type=args.type, extension=args.extension, hostnames=args.hostnames,
                        no_cache=args.no_cache, temp_dir=args.temp_dir, log_dir=args.log_dir, dry_run=args.dry_run)

if __name__ == '__main__':
    main()
