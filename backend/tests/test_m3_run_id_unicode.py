import json
import unittest

import m2_demo
from app.m3_behavioral_stability import M3ContractInputError
from app.m3_behavioral_stability import evaluate_m3_behavioral_stability


def _payload(count: int) -> dict:
    structure = m2_demo._SUCCESS
    return json.loads(json.dumps(m2_demo._m3_input([structure] * count)))


class M3RunIdUnicodeTest(unittest.TestCase):
    def test_unpaired_surrogate_run_id_is_a_contract_error(self) -> None:
        # A JSON-decoded "\ud800" is a str that is not valid Unicode; it must
        # be rejected at validation and never reach the canonical digest.
        for text in ('"\\ud800"', '"\\udc00"', '"run-\\udbff-x"'):
            for count in (1, 9, 10, 12):
                with self.subTest(run_id=text, runs=count):
                    payload = _payload(count)
                    payload["runs"][0]["run_id"] = json.loads(text)
                    with self.assertRaises(M3ContractInputError) as ctx:
                        evaluate_m3_behavioral_stability(payload)
                    self.assertEqual(
                        ctx.exception.errors,
                        [
                            {
                                "code": "INVALID_RUN_RECORD",
                                "field_path": "runs[0].run_id",
                            }
                        ],
                    )

    def test_invalid_unicode_run_ids_are_not_duplicates(self) -> None:
        payload = _payload(2)
        bad = json.loads('"\\ud800"')
        payload["runs"][0]["run_id"] = bad
        payload["runs"][1]["run_id"] = bad
        with self.assertRaises(M3ContractInputError) as ctx:
            evaluate_m3_behavioral_stability(payload)
        self.assertEqual(
            [error["field_path"] for error in ctx.exception.errors],
            ["runs[0].run_id", "runs[1].run_id"],
        )
        self.assertEqual(
            {error["code"] for error in ctx.exception.errors},
            {"INVALID_RUN_RECORD"},
        )

    def test_valid_non_ascii_run_ids_stay_valid(self) -> None:
        # A paired surrogate decodes to one astral code point: valid.
        for text in ('"run-\\u00e9"', '"run-\\ud83d\\ude00"', '"\\u5b9f"'):
            with self.subTest(run_id=text):
                payload = _payload(10)
                payload["runs"][0]["run_id"] = json.loads(text)
                result = evaluate_m3_behavioral_stability(payload)
                self.assertTrue(result["evaluable"])
                self.assertEqual(result["m3"], 1.0)


if __name__ == "__main__":
    unittest.main()
