#!/usr/bin/env python3

"""Low-overhead Linux system statistics for the Waybar performance panel."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import time


PROC = Path("/proc")
SYS = Path("/sys")


def read_text(path, default=""):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, ValueError):
        return default


def read_number(path, default=None, scale=1.0):
    try:
        return float(read_text(path)) / scale
    except (TypeError, ValueError):
        return default


def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


class SystemStats:
    """Samples /proc and /sys; external tools are only a GPU fallback."""

    def __init__(self):
        self.cpu_model = self._cpu_model()
        self.threads = os.cpu_count() or 1
        self.cores = self._physical_cores()
        self.previous_cpu = self._cpu_totals()
        self.net_interface = self._default_interface()
        self.previous_net = self._network_totals(self.net_interface)
        self.previous_net_time = time.monotonic()
        self.gpu = self._find_gpu()

    @staticmethod
    def _cpu_model():
        for line in read_text(PROC / "cpuinfo").splitlines():
            if line.startswith("model name") and ":" in line:
                return re.sub(r"\s+", " ", line.split(":", 1)[1]).strip()
        return "Linux CPU"

    @staticmethod
    def _physical_cores():
        pairs = set()
        physical = core = None
        for line in (read_text(PROC / "cpuinfo") + "\n\n").splitlines():
            if line.startswith("physical id"):
                physical = line.split(":", 1)[1].strip()
            elif line.startswith("core id"):
                core = line.split(":", 1)[1].strip()
            elif not line.strip():
                if physical is not None and core is not None:
                    pairs.add((physical, core))
                physical = core = None
        return len(pairs) or (os.cpu_count() or 1)

    @staticmethod
    def _cpu_totals():
        line = read_text(PROC / "stat").splitlines()[0]
        values = [int(value) for value in line.split()[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle

    def _cpu_usage(self):
        current = self._cpu_totals()
        total_delta = current[0] - self.previous_cpu[0]
        idle_delta = current[1] - self.previous_cpu[1]
        self.previous_cpu = current
        if total_delta <= 0:
            return 0.0
        return clamp(100.0 * (total_delta - idle_delta) / total_delta)

    @staticmethod
    def _cpu_frequency():
        frequencies = []
        for path in (SYS / "devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_cur_freq"):
            value = read_number(path, scale=1_000_000.0)
            if value:
                frequencies.append(value)
        if frequencies:
            return sum(frequencies) / len(frequencies)
        for line in read_text(PROC / "cpuinfo").splitlines():
            if line.startswith("cpu MHz") and ":" in line:
                try:
                    frequencies.append(float(line.split(":", 1)[1]) / 1000.0)
                except ValueError:
                    pass
        return sum(frequencies) / len(frequencies) if frequencies else None

    @staticmethod
    def _memory():
        values = {}
        for line in read_text(PROC / "meminfo").splitlines():
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            try:
                values[key] = int(raw.split()[0]) * 1024
            except (IndexError, ValueError):
                pass
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", values.get("MemFree", 0))
        used = max(0, total - available)
        cached = values.get("Cached", 0) + values.get("SReclaimable", 0)
        return {
            "total": total,
            "used": used,
            "available": available,
            "cached": cached,
            "percent": 100.0 * used / total if total else 0.0,
        }

    @staticmethod
    def _storage():
        stats = os.statvfs("/")
        total = stats.f_blocks * stats.f_frsize
        free = stats.f_bavail * stats.f_frsize
        used = max(0, total - free)
        return {
            "mount": "/",
            "total": total,
            "used": used,
            "free": free,
            "percent": 100.0 * used / total if total else 0.0,
        }

    @staticmethod
    def _default_interface():
        for line in read_text(PROC / "net/route").splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 4 and fields[1] == "00000000":
                try:
                    if int(fields[3], 16) & 2:
                        return fields[0]
                except ValueError:
                    pass
        for path in (SYS / "class/net").glob("*"):
            if path.name != "lo" and read_text(path / "operstate") == "up":
                return path.name
        return None

    @staticmethod
    def _network_totals(interface):
        if not interface:
            return None
        root = SYS / "class/net" / interface / "statistics"
        received = read_number(root / "rx_bytes")
        transmitted = read_number(root / "tx_bytes")
        if received is None or transmitted is None:
            return None
        return received, transmitted

    def _network(self):
        now = time.monotonic()
        interface = self._default_interface()
        if interface != self.net_interface:
            self.net_interface = interface
            self.previous_net = self._network_totals(interface)
            self.previous_net_time = now
        current = self._network_totals(interface)
        down = up = 0.0
        if current is not None and self.previous_net is not None:
            elapsed = max(0.001, now - self.previous_net_time)
            down = max(0.0, current[0] - self.previous_net[0]) / elapsed
            up = max(0.0, current[1] - self.previous_net[1]) / elapsed
        self.previous_net = current
        self.previous_net_time = now
        return {"interface": interface or "", "down": down, "up": up}

    @staticmethod
    def _find_gpu():
        cards = []
        drm_root = SYS / "class/drm"
        for card in drm_root.glob("card*"):
            if not card.name.removeprefix("card").isdigit() or not (card / "device").exists():
                continue
            device = card / "device"
            vendor = read_text(device / "vendor").lower()
            if vendor not in {"0x1002", "0x10de", "0x8086"}:
                continue
            cards.append((card, device, vendor))
        if not cards:
            return None
        card, device, vendor = cards[0]
        vendor_names = {"0x1002": "AMD Radeon Graphics", "0x10de": "NVIDIA Graphics", "0x8086": "Intel Graphics"}
        name = vendor_names[vendor]
        address = device.resolve().name.removeprefix("0000:")
        if shutil.which("lspci"):
            try:
                result = subprocess.run(
                    ["lspci", "-s", address], capture_output=True, text=True,
                    timeout=1.0, check=False,
                )
                description = result.stdout.strip().split(": ", 1)
                if len(description) == 2:
                    name = re.sub(r"\s+\(rev [^)]+\)$", "", description[1]).replace("[AMD/ATI] ", "")
            except (OSError, subprocess.SubprocessError):
                pass
        return {"card": card, "device": device, "vendor": vendor, "name": name}

    @staticmethod
    def _active_clock(path):
        for line in read_text(path).splitlines():
            if "*" in line:
                match = re.search(r"([0-9.]+)\s*(Mhz|MHz|Ghz|GHz)", line)
                if match:
                    value = float(match.group(1))
                    return value * 1000.0 if match.group(2).lower().startswith("g") else value
        return None

    def _gpu_stats(self, temperatures):
        if self.gpu is None:
            return None
        device = self.gpu["device"]
        data = {"name": self.gpu["name"], "temperature": temperatures.get("gpu")}
        busy = read_number(device / "gpu_busy_percent")
        if busy is None:
            busy = read_number(device / "gt_busy_percent")
        data["percent"] = clamp(busy) if busy is not None else None
        data["vram_used"] = read_number(device / "mem_info_vram_used")
        data["vram_total"] = read_number(device / "mem_info_vram_total")
        data["clock_mhz"] = self._active_clock(device / "pp_dpm_sclk")
        intel_clock = read_number(device / "gt/gt0/rps/cur_freq_mhz")
        if data["clock_mhz"] is None and intel_clock is not None:
            data["clock_mhz"] = intel_clock
        if self.gpu["vendor"] == "0x10de" and shutil.which("nvidia-smi"):
            self._nvidia_stats(data)
        return data

    @staticmethod
    def _nvidia_stats(data):
        query = "name,utilization.gpu,temperature.gpu,memory.used,memory.total,clocks.current.graphics"
        try:
            result = subprocess.run(
                ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=1.2, check=False,
            )
            fields = [field.strip() for field in result.stdout.splitlines()[0].split(",")]
            if len(fields) == 6:
                data.update({
                    "name": fields[0], "percent": clamp(float(fields[1])),
                    "temperature": float(fields[2]), "vram_used": float(fields[3]) * 1024**2,
                    "vram_total": float(fields[4]) * 1024**2, "clock_mhz": float(fields[5]),
                })
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            pass

    @staticmethod
    def _temperatures():
        result = {}
        for root in (SYS / "class/hwmon").glob("hwmon*"):
            driver = read_text(root / "name").lower()
            for input_path in root.glob("temp*_input"):
                value = read_number(input_path, scale=1000.0)
                if value is None or not -10 <= value <= 125:
                    continue
                stem = input_path.name.removesuffix("_input")
                sensor_label = read_text(root / f"{stem}_label").lower()
                if driver in {"k10temp", "zenpower", "coretemp"} and "cpu" not in result:
                    if not sensor_label or sensor_label in {"tctl", "tdie", "package id 0"}:
                        result["cpu"] = value
                elif driver in {"amdgpu", "nouveau", "nvidia"} and "gpu" not in result:
                    if not sensor_label or sensor_label in {"edge", "junction", "gpu"}:
                        result["gpu"] = value
                elif driver == "nvme" and "ssd" not in result:
                    if not sensor_label or sensor_label == "composite":
                        result["ssd"] = value
        if "cpu" not in result:
            for root in (SYS / "class/thermal").glob("thermal_zone*"):
                kind = read_text(root / "type").lower()
                if kind in {"x86_pkg_temp", "acpitz", "cpu-thermal", "soc_thermal"}:
                    value = read_number(root / "temp", scale=1000.0)
                    if value is not None and -10 <= value <= 125:
                        result["cpu"] = value
                        break
        return result

    def sample(self):
        temperatures = self._temperatures()
        load = [float(value) for value in read_text(PROC / "loadavg", "0 0 0").split()[:3]]
        cpu = {
            "name": self.cpu_model,
            "percent": self._cpu_usage(),
            "frequency_ghz": self._cpu_frequency(),
            "temperature": temperatures.get("cpu"),
            "cores": self.cores,
            "threads": self.threads,
            "load": load,
        }
        return {
            "cpu": cpu,
            "gpu": self._gpu_stats(temperatures),
            "memory": self._memory(),
            "temperatures": temperatures,
            "storage": self._storage(),
            "network": self._network(),
        }
