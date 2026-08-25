#!/usr/bin/env python3
from __future__ import annotations

import unittest
from unittest.mock import patch

from opc_engine.features.script_generation.modelmesh_client import (
    endpoint_variants,
    extract_text,
    get_api_key,
)


class ModelMeshClientTests(unittest.TestCase):
    def test_extract_text_reads_candidate_parts(self):
        response = {"candidates": [{"content": {"parts": [{"text": "第一段"}, {"text": "第二段"}]}}]}
        self.assertEqual(extract_text(response), "第一段\n第二段")

    def test_endpoint_variants_support_encoded_and_raw_model_names(self):
        variants = endpoint_variants("https://example.test/api/", "provider/model")
        self.assertEqual(variants[0], ("https://example.test/api/v1beta/models/provider%2Fmodel:generateContent", "encoded-model"))
        self.assertEqual(variants[1], ("https://example.test/api/v1beta/models/provider/model:generateContent", "raw-model"))

    def test_global_text_profile_has_priority(self):
        with patch(
            "opc_engine.features.script_generation.modelmesh_client.load_profile",
            return_value={"api_key": "global-key"},
        ):
            self.assertEqual(get_api_key({"modelmesh_api_key": "legacy-agent-key"}), "global-key")


if __name__ == "__main__":
    unittest.main()
