#!/usr/bin/env python3
"""
Lector de batería autónomo y de solo lectura para Redragon M916 Pro 1K.
Soporta modo cableado USB directo (3554:f55e) y modo inalámbrico 2.4 GHz (3554:f55d).
Prioriza la conexión USB cuando está disponible y respondiendo.
Produce salida JSON estructurada sin bloquear ni modificar configuraciones del mouse.
"""

import sys
import os
import glob
import json
import fcntl
import select
import time
import argparse

# Evitar la generación de artefactos __pycache__
sys.dont_write_bytecode = True

def _IOC(dir_flag, type_char, nr, size):
    return (dir_flag << 30) | (size << 16) | (ord(type_char) << 8) | nr

IOC_READ = 2
IOC_WRITE = 1
HIDIOCSFEATURE_17 = _IOC(IOC_READ | IOC_WRITE, "H", 0x06, 17)

def calculate_compx_crc(packet_bytes):
    """Calcula el checksum del protocolo Compx: (0x55 - suma) & 0xFF"""
    total = sum(packet_bytes[:16]) & 0xFF
    return (0x55 - total) & 0xFF

def build_battery_query():
    """Genera el paquete OutputReport8 de consulta de batería (Opcode 4)."""
    pkt = bytearray(17)
    pkt[0] = 0x08  # Report ID 8
    pkt[1] = 0x04  # UsbCommandId::BatteryLevel (4)
    pkt[16] = calculate_compx_crc(pkt)
    return bytes(pkt)

def parse_battery_packet(resp):
    """
    Decodifica la respuesta de telemetría de batería del protocolo Compx CX52850P.
    Valida estrictamente la longitud (17 bytes), encabezado, integridad de checksum CRC,
    rango de porcentaje (0..100) y plausibilidad de voltaje.
    Retorna un diccionario estructurado o None si la trama es inválida o corrupta.
    """
    # Exigir tamaño completo de 17 bytes (formato oficial OutputReport8 con CRC)
    if not resp or len(resp) < 17:
        return None

    # Verificar encabezado: Report ID 8 y Opcode BatteryLevel (4)
    if resp[0] != 0x08 or resp[1] != 0x04:
        return None

    # Verificación estricta de checksum CRC: (0x55 - suma(0..15)) & 0xFF == byte 16
    expected_crc = calculate_compx_crc(resp[:16])
    if resp[16] != expected_crc:
        return None

    raw_level = int(resp[6])
    # Rechazar datos corruptos o fuera del rango real 0..100%
    if raw_level > 100 or raw_level < 0:
        return None

    # Byte 7 es el estado de carga en el protocolo Compx (confirmado por desensamblado)
    is_charging = bool(resp[7] > 0)
    voltage_mv = (int(resp[8]) << 8) | int(resp[9])

    # En celdas Li-ion 1S el rango físico es 3.0V a 4.4V. Si excede 5000 mV es dato inválido.
    if voltage_mv > 5000:
        return None

    voltage_v = round(voltage_mv / 1000.0, 2) if voltage_mv > 0 else None

    return {
        "valid": True,
        "percentage": raw_level,
        "is_charging": is_charging,
        "voltage_mv": voltage_mv,
        "voltage_v": voltage_v,
        "crc_valid": True
    }

def find_redragon_devices(target_vid="3554", target_pids=("f55e", "f55d")):
    """
    Localiza dinámicamente los nodos /dev/hidraw* correspondientes al mouse o dongle.
    Identifica la interfaz en sysfs y clasifica por tipo de conexión:
    - 3554:f55e -> "usb" (cableado directo)
    - 3554:f55d -> "wireless" (receptor 2.4 GHz)
    """
    devices = []
    pids_lower = [p.lower() for p in target_pids]

    for path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        uevent_file = os.path.join(path, "device", "uevent")
        if not os.path.exists(uevent_file):
            continue

        try:
            with open(uevent_file, "r") as f:
                content = f.read()

            vid = None
            pid = None
            for line in content.splitlines():
                if line.startswith("HID_ID="):
                    parts = line.split("=")[1].split(":")
                    if len(parts) >= 3:
                        vid = parts[1].lstrip("0").lower()
                        pid = parts[2].lstrip("0").lower()

            if vid == target_vid.lower() and pid in pids_lower:
                node = "/dev/" + os.path.basename(path)

                # Identificar número de interfaz USB en sysfs
                iface_num = None
                cur = os.path.realpath(os.path.join(path, "device"))
                while cur and cur != "/":
                    b_iface = os.path.join(cur, "bInterfaceNumber")
                    if os.path.exists(b_iface):
                        try:
                            with open(b_iface, "r") as bf:
                                iface_num = int(bf.read().strip(), 16)
                        except Exception:
                            pass
                        break
                    cur = os.path.dirname(cur)

                conn_type = "usb" if pid == "f55e" else "wireless"

                devices.append({
                    "node": node,
                    "pid": pid,
                    "type": conn_type,
                    "interface": iface_num if iface_num is not None else 99
                })
        except Exception:
            continue

    return devices

def query_node(node, timeout_sec=0.4):
    """Envía la consulta de batería al nodo hidraw y espera respuesta con timeout acotado."""
    try:
        fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)
    except PermissionError:
        return {"error": "Permission denied"}
    except Exception as e:
        return {"error": str(e)}

    try:
        query = build_battery_query()

        # Enviar Feature Report vía ioctl (estándar Compx)
        sent = False
        try:
            fcntl.ioctl(fd, HIDIOCSFEATURE_17, query)
            sent = True
        except Exception:
            try:
                os.write(fd, query)
                sent = True
            except Exception as write_err:
                return {"error": f"Write failed: {write_err}"}

        if not sent:
            return {"error": "Could not send report"}

        # Esperar respuesta con polling acotado
        start = time.time()
        while time.time() - start < timeout_sec:
            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                try:
                    resp = os.read(fd, 64)
                except BlockingIOError:
                    continue
                except Exception as e:
                    return {"error": f"Read error: {e}"}

                if resp:
                    parsed = parse_battery_packet(resp)
                    if parsed:
                        return parsed

        return {"error": "Timeout"}
    finally:
        os.close(fd)

def filter_optimal_candidates(dev_list):
    """
    Filtra los dispositivos candidatos. En controladores Compx CX52850P, la interfaz 1
    es el canal vendor dedicado a Feature Reports. Las interfaces 0 y 2 corresponden a
    movimiento/teclado y no responden a estos comandos.
    """
    iface1 = [d for d in dev_list if d["interface"] == 1]
    if iface1:
        return iface1
    # Fallback si sysfs no expuso bInterfaceNumber
    dev_list_sorted = sorted(dev_list, key=lambda d: 0 if d["interface"] == 1 else (d["interface"] + 1))
    return dev_list_sorted[:1]

def get_battery_info():
    """
    Consulta la batería del mouse Redragon dinámicamente con tiempos acotados.
    Estrategia de prioridad:
    1. Si hay conexión USB directa (3554:f55e), consulta su canal vendor (Interfaz 1).
    2. Si responde con telemetría válida, retorna inmediatamente en modo 'usb'.
    3. Si no hay USB o entra en timeout, consulta el canal vendor del dongle 2.4 GHz (3554:f55d).
    """
    devices = find_redragon_devices("3554", ("f55e", "f55d"))

    if not devices:
        return {
            "connected": False,
            "valid": False,
            "connection": None,
            "percentage": None,
            "voltage_mv": None,
            "voltage_v": None,
            "is_charging": False,
            "device": None,
            "node": None,
            "error": "Disconnected"
        }

    usb_candidates = filter_optimal_candidates([d for d in devices if d["type"] == "usb"])
    wireless_candidates = filter_optimal_candidates([d for d in devices if d["type"] == "wireless"])

    # --- Intento 1: Conexión cableada directa (3554:f55e) ---
    last_usb_error = None
    for dev in usb_candidates:
        node = dev["node"]
        if not os.access(node, os.R_OK | os.W_OK):
            return {
                "connected": True,
                "valid": False,
                "connection": "usb",
                "percentage": None,
                "voltage_mv": None,
                "voltage_v": None,
                "is_charging": False,
                "device": "Redragon M916 Pro 1K (USB)",
                "node": node,
                "error": f"Permission denied on {node}"
            }

        result = query_node(node, timeout_sec=0.4)
        if result and result.get("valid"):
            return {
                "connected": True,
                "valid": True,
                "connection": "usb",
                "percentage": result["percentage"],
                "voltage_mv": result["voltage_mv"],
                "voltage_v": result["voltage_v"],
                "is_charging": result["is_charging"],
                "device": "Redragon M916 Pro 1K (USB)",
                "node": node,
                "error": None
            }
        else:
            last_usb_error = result.get("error", "No response")

    # --- Intento 2: Receptor inalámbrico 2.4 GHz (3554:f55d) ---
    last_wireless_error = None
    for dev in wireless_candidates:
        node = dev["node"]
        if not os.access(node, os.R_OK | os.W_OK):
            return {
                "connected": True,
                "valid": False,
                "connection": "wireless",
                "percentage": None,
                "voltage_mv": None,
                "voltage_v": None,
                "is_charging": False,
                "device": "Redragon M916 Pro 1K (2.4GHz)",
                "node": node,
                "error": f"Permission denied on {node}"
            }

        result = query_node(node, timeout_sec=0.45)
        if result and result.get("valid"):
            return {
                "connected": True,
                "valid": True,
                "connection": "wireless",
                "percentage": result["percentage"],
                "voltage_mv": result["voltage_mv"],
                "voltage_v": result["voltage_v"],
                "is_charging": result["is_charging"],
                "device": "Redragon M916 Pro 1K (2.4GHz)",
                "node": node,
                "error": None
            }
        else:
            last_wireless_error = result.get("error", "No response")

    # Si ninguno respondió válidamente
    if usb_candidates:
        return {
            "connected": True,
            "valid": False,
            "connection": "usb",
            "percentage": None,
            "voltage_mv": None,
            "voltage_v": None,
            "is_charging": False,
            "device": "Redragon M916 Pro 1K (USB)",
            "node": usb_candidates[0]["node"],
            "error": last_usb_error or "USB connected, waiting for telemetry"
        }
    else:
        return {
            "connected": True,
            "valid": False,
            "connection": "wireless",
            "percentage": None,
            "voltage_mv": None,
            "voltage_v": None,
            "is_charging": False,
            "device": "Redragon M916 Pro 1K (2.4GHz)",
            "node": wireless_candidates[0]["node"] if wireless_candidates else None,
            "error": last_wireless_error or "Dongle connected, mouse asleep or unreachable"
        }

def main():
    parser = argparse.ArgumentParser(description="Lector de batería para Redragon M916 Pro 1K (USB y 2.4GHz)")
    parser.add_argument("--test-packet", type=str, help="Hex string de paquete para probar parser")
    parser.add_argument("--pretty", action="store_true", help="Salida JSON formateada")
    args = parser.parse_args()

    if args.test_packet:
        try:
            raw = bytes.fromhex(args.test_packet.replace(" ", ""))
            parsed = parse_battery_packet(raw)
            out = {
                "connected": True,
                "valid": bool(parsed and parsed.get("valid")),
                "connection": "simulated",
                "percentage": parsed["percentage"] if parsed else None,
                "voltage_mv": parsed["voltage_mv"] if parsed else None,
                "voltage_v": parsed["voltage_v"] if parsed else None,
                "is_charging": parsed["is_charging"] if parsed else False,
                "device": "Redragon M916 Pro 1K (Simulated)",
                "node": "mock",
                "error": None if parsed else "Invalid packet"
            }
        except Exception as e:
            out = {"connected": True, "valid": False, "error": f"Parse error: {e}"}
    else:
        out = get_battery_info()

    if args.pretty:
        print(json.dumps(out, indent=2))
    else:
        print(json.dumps(out))

if __name__ == "__main__":
    main()
