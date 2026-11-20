"""Render the manual-leveling prompt using Klipper's reported screw results.

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


class ManualLevelingPrompt(unittest.TestCase):
    def setUp(self):
        config = configparser.RawConfigParser(strict=False)
        config.read(MACROS)
        self.template = jinja2.Environment(
            variable_start_string="{", variable_end_string="}"
        ).from_string(config["gcode_macro _SCREWS_TILT_PROMPT"]["gcode"])
        # Reported values in the supplied web-UI example, including its base.
        self.results = {
            "screw1": {"z": -1.203, "is_base": True, "sign": "CCW", "adjust": "00:00"},
            "screw2": {"z": -1.114, "is_base": False, "sign": "CW", "adjust": "00:08"},
            "screw3": {"z": -1.327, "is_base": False, "sign": "CCW", "adjust": "00:11"},
            "screw4": {"z": -1.232, "is_base": False, "sign": "CCW", "adjust": "00:02"},
        }
        self.printer = {
            "screws_tilt_adjust": {"results": self.results},
            "gcode_macro _global_var": {"z_bed_level": -2},
            "gcode_macro _COSMOS_SETTINGS": {},
            "configfile": {"settings": {"stepper_z": {"position_endstop": 4}}},
        }

    def render(self, **params):
        output = self.template.render(
            printer=self.printer, params=params,
            rawparams=" ".join(f"{key}={value}" for key, value in params.items()),
        )
        return [
            dict(token.split("=", 1) for token in shlex.split(line)[1:])["MSG"]
            for line in output.splitlines()
            if line.strip().startswith("RESPOND ")
        ]

    def rows(self, **params):
        return [
            message.removeprefix("action:prompt_text ")
            for message in self.render(**params)
            if message.startswith("action:prompt_text ")
            and any(corner in message for corner in (
                "Front right", "Rear right", "Rear left", "Front left"
            ))
        ]

    def test_display_matches_the_web_ui_adjustments(self):
        self.assertEqual(self.rows(), [
            "Front right: BASE - leave unchanged",
            "Rear right: CW 00:08",
            "Rear left: CCW 00:11",
            "Front left: CCW 00:02",
        ])

    def test_fixed_height_settings_do_not_change_relative_adjustments(self):
        self.printer["gcode_macro _global_var"]["z_bed_level"] = -3.5
        self.printer["configfile"]["settings"]["stepper_z"]["position_endstop"] = 3
        self.assertEqual(self.rows()[1], "Rear right: CW 00:08")

    def test_uses_the_reported_reference_screw_and_full_turns(self):
        self.results["screw1"].update(is_base=False, sign="CW", adjust="01:20")
        self.results["screw3"].update(is_base=True, adjust="00:00")
        rows = self.rows()
        self.assertEqual(rows[0], "Front right: CW 01:20")
        self.assertEqual(rows[2], "Rear left: BASE - leave unchanged")

    def test_calibration_retains_close_and_retry_actions(self):
        messages = self.render(CALIBRATION="TRUE", BED_TEMP=70)
        self.assertIn("action:prompt_footer_button Done|_CLOSE_PROMPT", messages)
        self.assertIn(
            "action:prompt_footer_button Retry|SCREWS_TILT_CALCULATE CALIBRATION=TRUE BED_TEMP=70|warning",
            messages,
        )
        self.assertEqual(self.rows(CALIBRATION="TRUE"), self.rows())

    def test_normal_completion_retains_mesh_action_at_selected_temperature(self):
        self.assertIn(
            "action:prompt_footer_button Done|_SCREWS_TILT_MESH BED_TEMP=70",
            self.render(BED_TEMP=70),
        )


if __name__ == "__main__":
    unittest.main()
