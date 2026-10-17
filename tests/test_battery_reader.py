#!/usr/bin/env python3
"""
Unit test suite for the Redragon M916 Pro battery reader.
Verifies packet parsing, strict checksum verification, range validation,
negative rejection cases (bad CRC, out-of-range %, truncated reports),
dual-mode priority, and CLI outputs.
"""

import unittest
import json
import subprocess
import os
import sys
from unittest.mock import patch

# Dynamically resolve project root directory
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TEST_DIR)
sys.path.insert(0, PROJECT_ROOT)

from redragon_battery import (
    parse_battery_packet,
    calculate_compx_crc,
    build_battery_query,
    get_battery_info
)

class TestRedragonBatteryReader(unittest.TestCase):

    def test_real_wireless_packet_regression(self):
        """
        Regression: Validates the actual hardware telemetry packet captured over 2.4 GHz:
        08 04 00 00 00 02 0f 00 0d dd 00 00 00 00 00 00 4e
        Level: 15% (0x0F)
        Voltage: 3549 mV (0x0D 0xDD = 3.55 V)
        Charging: False (byte 7 == 0x00)
        Checksum: 0x4E
        """
        raw_hex = "08 04 00 00 00 02 0f 00 0d dd 00 00 00 00 00 00 4e"
        data = bytes.fromhex(raw_hex.replace(" ", ""))

        result = parse_battery_packet(data)
        self.assertIsNotNone(result)
        self.assertTrue(result["valid"])
        self.assertEqual(result["percentage"], 15)
        self.assertFalse(result["is_charging"])
        self.assertEqual(result["voltage_mv"], 3549)
        self.assertEqual(result["voltage_v"], 3.55)
        self.assertTrue(result["crc_valid"])

    def test_usb_wired_charging_packet(self):
        """
        Validates packet format when connected via USB cable and charging:
        Level: 75% (0x4B), Charging: True (byte 7 == 0x01), Voltage: 4120 mV (0x10 0x18)
        """
        pkt = bytearray(17)
        pkt[0] = 0x08
        pkt[1] = 0x04
        pkt[6] = 75
        pkt[7] = 1  # is_charging
        pkt[8] = (4120 >> 8) & 0xFF
        pkt[9] = 4120 & 0xFF
        pkt[16] = calculate_compx_crc(pkt)

        result = parse_battery_packet(bytes(pkt))
        self.assertIsNotNone(result)
        self.assertTrue(result["valid"])
        self.assertEqual(result["percentage"], 75)
        self.assertTrue(result["is_charging"])
        self.assertEqual(result["voltage_mv"], 4120)
        self.assertEqual(result["voltage_v"], 4.12)
        self.assertTrue(result["crc_valid"])

    def test_negative_invalid_checksum_rejected(self):
        """A packet with a corrupted or mismatched checksum MUST be rejected."""
        raw_hex = "08 04 00 00 00 02 0f 00 0d dd 00 00 00 00 00 00 4e"
        data = bytearray(bytes.fromhex(raw_hex.replace(" ", "")))
        # Invalidate checksum byte
        data[16] = 0x00
        self.assertIsNone(parse_battery_packet(bytes(data)))

        data[16] = 0x4F  # 1 byte off
        self.assertIsNone(parse_battery_packet(bytes(data)))

    def test_negative_out_of_range_percentage_rejected(self):
        """
        Out-of-range percentages (e.g. 250% or 101%) must NOT be clamped to 100%;
        they represent corrupt readings and must return None.
        """
        # Test 250% (0xFA)
        pkt = bytearray(17)
        pkt[0] = 0x08
        pkt[1] = 0x04
        pkt[6] = 250
        pkt[7] = 0
        pkt[8] = 0x0E
        pkt[9] = 0x10
        pkt[16] = calculate_compx_crc(pkt)
        self.assertIsNone(parse_battery_packet(bytes(pkt)))

        # Test 101%
        pkt[6] = 101
        pkt[16] = calculate_compx_crc(pkt)
        self.assertIsNone(parse_battery_packet(bytes(pkt)))

    def test_negative_truncated_packets_rejected(self):
        """Truncated packets (< 17 bytes) missing the full payload or CRC must be rejected."""
        # 10 bytes response
        raw_10 = bytes.fromhex("08 04 00 00 00 02 0f 00 0d dd".replace(" ", ""))
        self.assertIsNone(parse_battery_packet(raw_10))

        # 16 bytes response (missing byte 16 checksum)
        raw_16 = bytes.fromhex("08 04 00 00 00 02 0f 00 0d dd 00 00 00 00 00 00".replace(" ", ""))
        self.assertIsNone(parse_battery_packet(raw_16))

        # Empty or tiny buffer
        self.assertIsNone(parse_battery_packet(b""))
        self.assertIsNone(parse_battery_packet(b"\x08\x04"))

    def test_negative_wrong_headers_rejected(self):
        """Packets with wrong Report ID or wrong Opcode must be rejected."""
        pkt = bytearray(17)
        pkt[0] = 0x09  # Wrong Report ID (expected 0x08)
        pkt[1] = 0x04
        pkt[6] = 50
        pkt[16] = calculate_compx_crc(pkt)
        self.assertIsNone(parse_battery_packet(bytes(pkt)))

        pkt[0] = 0x08
        pkt[1] = 0x05  # Wrong Opcode (expected 0x04 BatteryLevel)
        pkt[16] = calculate_compx_crc(pkt)
        self.assertIsNone(parse_battery_packet(bytes(pkt)))

    def test_negative_implausible_voltage_rejected(self):
        """Voltage exceeding 5000 mV in a 1S LiPo cell indicates corrupted data."""
        pkt = bytearray(17)
        pkt[0] = 0x08
        pkt[1] = 0x04
        pkt[6] = 50
        pkt[8] = (6200 >> 8) & 0xFF
        pkt[9] = 6200 & 0xFF
        pkt[16] = calculate_compx_crc(pkt)
        self.assertIsNone(parse_battery_packet(bytes(pkt)))

    def test_checksum_calculation(self):
        """Validates the official Compx checksum algorithm: (0x55 - sum(bytes[:16])) & 0xFF"""
        raw_hex = "08 04 00 00 00 02 0f 00 0d dd 00 00 00 00 00 00"
        data = bytes.fromhex(raw_hex.replace(" ", ""))
        crc = calculate_compx_crc(data)
        self.assertEqual(crc, 0x4E)

    @patch("redragon_battery.os.access")
    @patch("redragon_battery.query_node")
    @patch("redragon_battery.find_redragon_devices")
    def test_usb_priority_over_wireless(self, mock_find, mock_query, mock_access):
        """
        Ensures that when direct USB cable connection (3554:f55e) is present and responding,
        it is prioritized over the 2.4 GHz wireless receiver (3554:f55d).
        """
        mock_access.return_value = True
        mock_find.return_value = [
            {"node": "/dev/hidraw1", "pid": "f55d", "type": "wireless", "interface": 1},
            {"node": "/dev/hidraw7", "pid": "f55e", "type": "usb", "interface": 1},
        ]
        mock_query.return_value = {
            "valid": True,
            "percentage": 50,
            "is_charging": True,
            "voltage_mv": 3950,
            "voltage_v": 3.95
        }

        info = get_battery_info()
        self.assertTrue(info["valid"])
        self.assertEqual(info["connection"], "usb")
        self.assertEqual(info["node"], "/dev/hidraw7")
        self.assertEqual(info["percentage"], 50)
        self.assertTrue(info["is_charging"])

    @patch("redragon_battery.os.access")
    @patch("redragon_battery.query_node")
    @patch("redragon_battery.find_redragon_devices")
    def test_wireless_fallback_when_usb_fails_or_unplugged(self, mock_find, mock_query, mock_access):
        """
        Ensures that when USB cable is absent or timing out, the reader falls back to 2.4 GHz dongle.
        """
        mock_access.return_value = True
        mock_find.return_value = [
            {"node": "/dev/hidraw1", "pid": "f55d", "type": "wireless", "interface": 1},
        ]
        mock_query.return_value = {
            "valid": True,
            "percentage": 30,
            "is_charging": False,
            "voltage_mv": 3688,
            "voltage_v": 3.69
        }

        info = get_battery_info()
        self.assertTrue(info["valid"])
        self.assertEqual(info["connection"], "wireless")
        self.assertEqual(info["node"], "/dev/hidraw1")
        self.assertEqual(info["percentage"], 30)
        self.assertFalse(info["is_charging"])

    def test_cli_execution_with_test_packet(self):
        """Validates CLI execution and JSON output parsing with --test-packet"""
        script = os.path.join(PROJECT_ROOT, "redragon_battery.py")
        raw_hex = "0804000000020f000ddd0000000000004e"
        proc = subprocess.run([sys.executable, script, "--test-packet", raw_hex], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)

        data = json.loads(proc.stdout.strip())
        self.assertTrue(data["connected"])
        self.assertTrue(data["valid"])
        self.assertEqual(data["percentage"], 15)
        self.assertFalse(data["is_charging"])
        self.assertEqual(data["voltage_mv"], 3549)
        self.assertEqual(data["voltage_v"], 3.55)

if __name__ == "__main__":
    unittest.main()
