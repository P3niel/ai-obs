"""Unit tests for the shared payload-coercion helpers."""

import unittest

from app.payload_coercion import as_mapping
from app.payload_coercion import copy_mapping
from app.payload_coercion import copy_value
from app.payload_coercion import optional_number
from app.payload_coercion import optional_text
from app.payload_coercion import sequence_of_mappings


class OptionalTextTest(unittest.TestCase):
    def test_none_returns_none(self) -> None:
        self.assertIsNone(optional_text(None))

    def test_blank_string_returns_none(self) -> None:
        self.assertIsNone(optional_text("   "))

    def test_non_string_is_coerced_and_stripped(self) -> None:
        self.assertEqual(optional_text(42), "42")
        self.assertEqual(optional_text("  hello  "), "hello")


class OptionalNumberTest(unittest.TestCase):
    def test_none_returns_none(self) -> None:
        self.assertIsNone(optional_number(None))

    def test_invalid_value_returns_none(self) -> None:
        self.assertIsNone(optional_number("not-a-number"))
        self.assertIsNone(optional_number(object()))

    def test_valid_value_is_coerced_to_float(self) -> None:
        self.assertEqual(optional_number("12.5"), 12.5)
        self.assertEqual(optional_number(7), 7.0)


class AsMappingTest(unittest.TestCase):
    def test_non_mapping_returns_empty_dict(self) -> None:
        self.assertEqual(as_mapping(None), {})
        self.assertEqual(as_mapping([1, 2, 3]), {})

    def test_mapping_is_returned_without_copying(self) -> None:
        source = {"a": 1}
        self.assertIs(as_mapping(source), source)


class SequenceOfMappingsTest(unittest.TestCase):
    def test_non_sequence_returns_empty_tuple(self) -> None:
        self.assertEqual(sequence_of_mappings(None), ())
        self.assertEqual(sequence_of_mappings("abc"), ())

    def test_filters_non_mapping_items(self) -> None:
        result = sequence_of_mappings([{"a": 1}, "skip", {"b": 2}, 3])
        self.assertEqual(result, ({"a": 1}, {"b": 2}))


class CopyMappingTest(unittest.TestCase):
    def test_deep_copies_nested_structures(self) -> None:
        source = {"a": {"b": [1, {"c": 2}]}}
        copied = copy_mapping(source)
        self.assertEqual(copied, source)
        self.assertIsNot(copied, source)
        self.assertIsNot(copied["a"], source["a"])
        self.assertIsNot(copied["a"]["b"], source["a"]["b"])

    def test_copy_value_passes_through_scalars(self) -> None:
        self.assertEqual(copy_value("text"), "text")
        self.assertEqual(copy_value(5), 5)


if __name__ == "__main__":
    unittest.main()
