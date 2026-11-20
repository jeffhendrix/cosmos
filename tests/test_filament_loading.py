"""Render the real Klipper macros and check the loading prompt/command sequence.

Run with: python3 -m unittest discover -s tests -v
Requires Jinja2, as used by Klipper itself.
"""
import configparser
from pathlib import Path
import shlex
import unittest

import jinja2


MACROS = Path(__file__).resolve().parents[1] / (
    "meta-opencentauri/recipes-apps/klipper/files/shared-macros.cfg"
)


class LoadingMacros(unittest.TestCase):
    def setUp(self):
        config = configparser.RawConfigParser(strict=False)
        config.read(MACROS)
        self.macros = {
            section.removeprefix("gcode_macro "): config[section]["gcode"]
            for section in config.sections()
            if section.startswith("gcode_macro ") and "gcode" in config[section]
        }
        self.env = jinja2.Environment(
            variable_start_string="{", variable_end_string="}"
        )
        self.printer = {
            "gcode_macro _global_var": {
                "extruder_temp": {"loading": 220, "probing": 150},
                "target_extruder": 205,
            },
            "gcode_macro _COSMOS_SETTINGS": {"toolhead_led": "false"},
            "extruder": {"temperature": 220, "target": 220, "can_extrude": True},
            "pause_resume": {"is_paused": False},
        }

    def render(self, macro, **params):
        def raise_error(message):
            raise RuntimeError(message)

        output = self.env.from_string(self.macros[macro]).render(
            printer=self.printer, params=params, action_raise_error=raise_error
        )
        commands = []
        for line in output.splitlines():
            line = line.split(";", 1)[0].strip()
            if not line or line.startswith("#"):
                continue
            commands.append(line)
        return commands

    @staticmethod
    def prompt_before(commands, command):
        boundary = commands.index(command)
        messages = [
            dict(token.split("=", 1) for token in shlex.split(line)[1:])["MSG"]
            for line in commands[:boundary]
            if line.startswith("RESPOND ") and "action:prompt_text " in line
        ]
        return messages[-1]

    def test_status_tracks_homing_moving_and_heating(self):
        commands = self.render("LOAD_FILAMENT")
        self.assertIn("Homing", self.prompt_before(commands, "_CG28 AXIS=XY"))
        self.assertIn("tray", self.prompt_before(commands, "MOVE_TO_TRAY"))
        self.assertIn(
            "Heating", self.prompt_before(
                commands, "TEMPERATURE_WAIT SENSOR=extruder MINIMUM=220 MAXIMUM=225"
            )
        )
        self.assertLess(commands.index("M104 S220"), commands.index(
            "TEMPERATURE_WAIT SENSOR=extruder MINIMUM=220 MAXIMUM=225"
        ))
        self.assertLess(commands.index("MOVE_TO_TRAY"), commands.index("M104 S220"))

    def test_custom_temperature_still_controls_the_wait(self):
        commands = self.render("LOAD_FILAMENT", EXTRUDER_TEMP=240)
        self.assertIn("M104 S240", commands)
        self.assertIn("TEMPERATURE_WAIT SENSOR=extruder MINIMUM=240 MAXIMUM=245", commands)
        self.assertTrue(any("LOAD|_LOAD_FILAMENT_STEP_PUSH" in c for c in commands))
        self.assertTrue(any("CANCEL|_LOAD_FILAMENT_CANCEL" in c for c in commands))

    def test_purge_readout_matches_the_commanded_feed(self):
        commands = self.render("_LOAD_FILAMENT_STEP_PUSH")
        message = self.prompt_before(commands, "G1 E70 F420")
        self.assertIn("70 mm", message)
        self.assertIn("7", message)
        self.assertIn("mm/s", message)
        self.assertLess(commands.index("G1 E70 F420"), commands.index("M400"))
        self.assertTrue(any("Purge more|_LOAD_FILAMENT_STEP_PUSH" in c for c in commands))
        self.assertTrue(any("Done|_LOAD_FILAMENT_STEP_DONE" in c for c in commands))

    def test_cold_extrusion_is_still_rejected(self):
        self.printer["extruder"]["temperature"] = 100
        with self.assertRaisesRegex(RuntimeError, "not hot enough"):
            self.render("_LOAD_FILAMENT_STEP_PUSH")

    def test_cancel_and_paused_completion_keep_existing_heater_behavior(self):
        self.assertIn("M104 S0", self.render("_LOAD_FILAMENT_CANCEL"))
        self.printer["pause_resume"]["is_paused"] = True
        commands = self.render("_LOAD_FILAMENT_STEP_DONE")
        self.assertIn("M104 S205", commands)
        self.assertNotIn("M104 S0", commands)
        self.assertNotIn("CLEAN_NOZZLE", commands)


if __name__ == "__main__":
    unittest.main()
