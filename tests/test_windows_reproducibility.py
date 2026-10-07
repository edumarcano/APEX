from __future__ import annotations

import importlib.util
import json
import marshal
from pathlib import Path
import sys
import unittest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "reproducibility.py"
_SPEC = importlib.util.spec_from_file_location("apex_windows_reproducibility", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
_analyze_code_pair = _MODULE._analyze_code_pair
_safe_names = _MODULE._safe_names


class FrozenExecutableDiagnosticsTests(unittest.TestCase):
    def test_compiled_code_reports_field_names_without_filename_or_constants(self) -> None:
        left = marshal.dumps(compile("sentinel_value = 'private marker'", "C:/Users/example/first.py", "exec"))
        right = marshal.dumps(compile("sentinel_value = 'different marker'", "C:/Users/example/second.py", "exec"))

        report = _analyze_code_pair(left, right, 10)
        encoded = json.dumps(report)

        self.assertTrue(report["parsed"])
        self.assertIn("co_filename", report["changed_fields"])
        self.assertIn("co_consts", report["changed_fields"])
        self.assertNotIn("C:/Users/example", encoded)
        self.assertNotIn("private marker", encoded)
        self.assertNotIn("different marker", encoded)

    def test_code_field_list_is_capped(self) -> None:
        left = compile("x = 1", "first.py", "exec")
        right = compile("x = 2", "second.py", "exec")

        report = _analyze_code_pair(marshal.dumps(left), marshal.dumps(right), 1)

        self.assertLessEqual(len(report["changed_fields"]), 1)
        self.assertTrue(all(field.startswith("co_") for field in report["changed_fields"]))

    def test_equal_constant_values_ignore_marshal_reference_sharing(self) -> None:
        first_value = "".join(("distinct-string-", "constant"))
        second_value = "".join(("distinct-string-", "constant"))
        self.assertEqual(first_value, second_value)
        self.assertIsNot(first_value, second_value)
        template = compile("value = None", "safe_module.py", "exec")
        left_code = template.replace(co_consts=((first_value, second_value), None))
        right_code = template.replace(co_consts=((first_value, first_value), None))
        left_bytes = marshal.dumps(left_code)
        right_bytes = marshal.dumps(right_code)
        self.assertNotEqual(left_bytes, right_bytes)

        report = _analyze_code_pair(left_bytes, right_bytes, 10)

        self.assertTrue(report["parsed"])
        self.assertEqual(report["changed_fields"], [])
        self.assertTrue(report["serialization_only"])

    def test_names_are_capped_and_unsafe_paths_are_omitted(self) -> None:
        names = [f"safe_{index}" for index in range(12)] + ["../private", "C:/Users/example/private"]

        result = _safe_names(names, 4)

        self.assertEqual(len(result), 4)
        self.assertTrue(all("/" not in name and "\\" not in name for name in result))


if __name__ == "__main__":
    unittest.main()
