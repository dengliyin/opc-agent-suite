#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opc_engine.features.script_generation import generate_product_script


class GenerateProductScriptTests(unittest.TestCase):
    def test_preserved_duration_restores_each_reference_shot_timecode(self):
        reference = """镜头 1 (00:00.000 - 00:01.000):

内容

镜头 2 (00:01.000 - 00:02.500):

内容
"""
        generated = """### 镜头 1 (00:00.000 - 00:02.000)

新内容

### 镜头 2 (00:02.000 - 00:04.000)

新内容
"""

        corrected, warnings = generate_product_script.enforce_output_timeline(
            {"script_total_duration": "不改变原脚本"},
            reference,
            generated,
        )

        self.assertIn("### 镜头 1 (00:00.000 - 00:01.000)", corrected)
        self.assertIn("### 镜头 2 (00:01.000 - 00:02.500)", corrected)
        self.assertEqual(len(warnings), 1)
        self.assertIn("已修正 2 个镜头", warnings[0])

    def test_preserved_duration_rejects_changed_shot_structure(self):
        reference = """镜头 1 (00:00.000 - 00:01.000):
镜头 2 (00:01.000 - 00:02.500):
"""
        generated = """### 镜头 1 (00:00.000 - 00:01.000)
### 镜头 3 (00:01.000 - 00:02.500)
"""

        with self.assertRaisesRegex(ValueError, "镜头编号或数量与参考稿不一致"):
            generate_product_script.enforce_output_timeline(
                {"script_total_duration": "不改变原脚本"},
                reference,
                generated,
            )

    def test_extra_shot_is_merged_into_reference_timeline_before_validation(self):
        reference = """### 镜头 1 (00:00.000 - 00:01.500)
### 镜头 2 (00:01.500 - 00:02.800)
### 镜头 3 (00:02.800 - 00:04.600)
### 镜头 4 (00:04.600 - 00:05.500)
### 镜头 5 (00:05.500 - 00:06.800)
### 镜头 6 (00:06.800 - 00:07.900)
"""
        generated = """### 镜头 1 (00:00.000 - 00:01.500)
内容一
### 镜头 2 (00:01.500 - 00:02.800)
内容二
### 镜头 3 (00:02.800 - 00:04.600)
内容三
### 镜头 4 (00:04.600 - 00:05.500)
内容四
### 镜头 5 (00:05.500 - 00:06.800)
内容五
### 镜头 6 (00:06.800 - 00:07.300)
内容六前半
### 镜头 7 (00:07.300 - 00:07.900)
内容六后半
"""

        corrected, warnings = generate_product_script.enforce_output_timeline(
            {"script_total_duration": "不改变原脚本"},
            reference,
            generated,
        )

        matches = list(generate_product_script.SHOT_HEADING_TIMECODE_PATTERN.finditer(corrected))
        self.assertEqual([int(match.group("number")) for match in matches], [1, 2, 3, 4, 5, 6])
        self.assertIn("### 镜头 6 (00:06.800 - 00:07.900)", corrected)
        self.assertIn("内容六前半", corrected)
        self.assertIn("内容六后半", corrected)
        self.assertNotIn("镜头 7", corrected)
        self.assertTrue(any("已自动合并并恢复参考时间轴" in warning for warning in warnings))

    def test_stale_explicit_duration_cannot_override_reference_timeline(self):
        reference = """镜头 1 (00:00.000 - 00:01.000):
镜头 2 (00:01.000 - 00:04.000):
"""
        generated = """### 镜头 1 (00:00.000 - 00:02.000)
### 镜头 2 (00:02.000 - 00:04.000)
"""

        corrected, warnings = generate_product_script.enforce_output_timeline(
            {"script_total_duration": "8秒"},
            reference,
            generated,
        )

        self.assertIn("### 镜头 1 (00:00.000 - 00:01.000)", corrected)
        self.assertIn("### 镜头 2 (00:01.000 - 00:04.000)", corrected)
        self.assertEqual(len(warnings), 1)
        self.assertIn("已按参考稿恢复", warnings[0])

    def test_multiple_mutations_are_validated_and_saved_independently(self):
        reference = """### 镜头 1 (00:00.000 - 00:01.000)
### 镜头 2 (00:01.000 - 00:03.000)
"""
        variant_one = """### 变体 #1
### 镜头 1 (00:00.000 - 00:02.000)
第一条
### 镜头 2 (00:02.000 - 00:04.000)
"""
        variant_two = """### 变体 #2
### 镜头 1 (00:00.000 - 00:02.000)
第二条
### 镜头 2 (00:02.000 - 00:04.000)
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference_path = root / "VN-author-1234567890123456789.md"
            reference_path.write_text(reference, encoding="utf-8")
            config = {
                "script_reference_script_path": str(reference_path),
                "script_product_document_path": str(root / "SIMC01-SIMC染发棒-产品信息.md"),
            }
            raw_response = {
                "final_stage": "mutation_rewrite",
                "mutation_rewrite_raw": {
                    "mutation_variants": [variant_one, variant_two],
                    "mutation_variant_numbers": [1, 2],
                },
            }

            with patch.object(
                generate_product_script,
                "enforce_output_timeline",
                wraps=generate_product_script.enforce_output_timeline,
            ) as enforce_timeline:
                output_paths, raw_paths = generate_product_script.write_script_outputs(
                    config,
                    str(root / "outputs"),
                    f"{variant_one}\n\n{variant_two}",
                    raw_response,
                )

            self.assertEqual(len(output_paths), 2)
            self.assertEqual(len(raw_paths), 2)
            self.assertEqual(enforce_timeline.call_count, 2)
            first_text = output_paths[0].read_text(encoding="utf-8")
            second_text = output_paths[1].read_text(encoding="utf-8")
            self.assertIn("第一条", first_text)
            self.assertNotIn("第二条", first_text)
            self.assertIn("第二条", second_text)
            self.assertNotIn("第一条", second_text)
            for saved_text in (first_text, second_text):
                self.assertIn("镜头 1 (00:00.000 - 00:01.000)", saved_text)
                self.assertIn("镜头 2 (00:01.000 - 00:03.000)", saved_text)

    def test_clone_is_timeline_validated_once(self):
        reference = """### 镜头 1 (00:00.000 - 00:01.000)
### 镜头 2 (00:01.000 - 00:03.000)
"""
        clone = """### 镜头 1 (00:00.000 - 00:02.000)
### 镜头 2 (00:02.000 - 00:04.000)
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference_path = root / "VN-author-1234567890123456789.md"
            reference_path.write_text(reference, encoding="utf-8")
            config = {
                "script_reference_script_path": str(reference_path),
                "script_product_document_path": str(root / "SIMC01-SIMC染发棒-产品信息.md"),
            }
            with patch.object(
                generate_product_script,
                "enforce_output_timeline",
                wraps=generate_product_script.enforce_output_timeline,
            ) as enforce_timeline:
                output_paths, _raw_paths = generate_product_script.write_script_outputs(
                    config,
                    str(root / "outputs"),
                    clone,
                    {},
                )

            self.assertEqual(len(output_paths), 1)
            self.assertEqual(enforce_timeline.call_count, 1)

    def test_audio_parser_uses_real_target_language_line_after_delivery_description(self):
        script = """### 镜头 1 (00:00.000 - 00:01.000)

* **[音频文案]** on-screen。男子喘着粗气，语速急促。
(意大利语): “Ma che dice questo adesso?”
"""

        profiles = generate_product_script.extract_audio_profiles(script)

        self.assertEqual(profiles["001"]["audio"], "(意大利语): “Ma che dice questo adesso?”")
        self.assertEqual(profiles["001"]["word_count"], 5)

    def test_audio_parser_treats_environment_sound_notes_as_no_spoken_audio(self):
        script = """### 镜头 1 (00:00.000 - 00:01.100)

[音频文案] （无口播，仅有金属工具碰撞声和沉重的呼吸声）

### 镜头 2 (00:01.100 - 00:02.000)

[音频文案] （无声，仅有按键的轻微“滴”声）
"""

        self.assertEqual(generate_product_script.extract_audio_profiles(script), {})

    def test_audio_fit_uses_shot_duration_and_rejects_overlong_italian_dialogue(self):
        script = """### 镜头 1 (00:00.000 - 00:01.000)

* **[声音/语气]**：男子急促地说。
* **[音频文案]**：(意大利语): “Uno due tre quattro cinque sei sette otto nove dieci undici.”（中文翻译对照：测试。）
"""

        issues = generate_product_script.validate_audio_fit(script)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["shot_key"], "001")
        self.assertEqual(issues[0]["word_count"], 11)
        self.assertEqual(issues[0]["max_word_count"], 4)

    def test_fast_tiktok_pacing_warns_but_does_not_block_below_hard_limit(self):
        script = """### 镜头 1 (00:00.000 - 00:02.100)

* **[音频文案]**：(英语): “One two three four five six seven eight.”（中文翻译对照：测试。）
"""

        self.assertFalse(generate_product_script.validate_audio_fit(script))
        warnings = generate_product_script.audio_pacing_warnings(script)
        self.assertEqual(len(warnings), 1)
        self.assertIn("8 词", warnings[0])
        self.assertIn("建议 7 词", warnings[0])
        self.assertIn("硬上限 8 词", warnings[0])

    def test_fast_tiktok_pacing_blocks_only_above_hard_limit(self):
        script = """### 镜头 1 (00:00.000 - 00:02.100)

* **[音频文案]**：(英语): “One two three four five six seven eight nine.”（中文翻译对照：测试。）
"""

        issues = generate_product_script.validate_audio_fit(script)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["target_word_count"], 7)
        self.assertEqual(issues[0]["max_word_count"], 8)

    def test_overlong_spoken_dialogue_is_rejected_before_markdown_is_written(self):
        reference = """### 镜头 1 (00:00.000 - 00:01.000)

* **[音频文案]**：(意大利语): “Ciao.”（中文翻译对照：你好。）
"""
        clone = """### 镜头 1 (00:00.000 - 00:01.000)

* **[音频文案]**：(意大利语): “Uno due tre quattro cinque sei sette otto nove dieci undici.”（中文翻译对照：测试。）
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "outputs"
            reference_path = root / "IT-author-1234567890123456789.md"
            reference_path.write_text(reference, encoding="utf-8")
            config = {
                "script_reference_script_path": str(reference_path),
                "script_product_document_path": str(root / "DRN-E99Pro无人机-产品信息.md"),
            }

            with self.assertRaisesRegex(RuntimeError, "真实口播仍超过镜头时长"):
                generate_product_script.write_script_outputs(
                    config,
                    str(output_dir),
                    clone,
                    {},
                )

            self.assertFalse(list(output_dir.glob("*.md")))

    def test_audio_repair_shortens_real_dialogue_and_preserves_reference_timeline(self):
        reference = """### 镜头 1 (00:00.000 - 00:01.000)

* **[音频文案]**：(意大利语): “Ciao.”（中文翻译对照：你好。）
"""
        overlong = """### 镜头 1 (00:00.000 - 00:02.000)

* **[声音/语气]**：男子急促地说。
* **[音频文案]**：(意大利语): “Uno due tre quattro cinque sei.”（中文翻译对照：测试。）
"""
        repaired = json.dumps(
            {"001": {"audio": "Solo ora.", "translation": "就是现在。"}},
            ensure_ascii=False,
        )
        config = {"script_target_language": "意大利语"}
        args = argparse.Namespace(backend="api")

        with patch.object(
            generate_product_script,
            "call_text_model",
            return_value=(repaired, {"id": "repair"}, "openai-chat", "content"),
        ) as call_model:
            result, metadata = generate_product_script.repair_script_audio(
                config,
                args,
                overlong,
                reference,
                "测试音频缩写",
            )

        self.assertEqual(call_model.call_count, 1)
        self.assertIn("镜头 1 (00:00.000 - 00:01.000)", result)
        self.assertIn("Solo ora", result)
        self.assertFalse(generate_product_script.validate_audio_fit(result))
        self.assertTrue(metadata["repair_requested"])

    def test_audio_repair_runs_second_round_when_first_result_is_still_overlong(self):
        reference = """### 镜头 1 (00:00.000 - 00:01.000)

* **[音频文案]**：(英语): “Go.”（中文翻译对照：走。）
"""
        overlong = """### 镜头 1 (00:00.000 - 00:01.000)

* **[音频文案]**：(英语): “One two three four five six.”（中文翻译对照：测试。）
"""
        still_overlong = json.dumps(
            {"001": {"audio": "One two three four five.", "translation": "测试。"}},
            ensure_ascii=False,
        )
        repaired = json.dumps(
            {"001": {"audio": "Go now.", "translation": "现在走。"}},
            ensure_ascii=False,
        )
        config = {"script_target_language": "英语"}
        args = argparse.Namespace(backend="api")

        with patch.object(
            generate_product_script,
            "call_text_model",
            side_effect=[
                (still_overlong, {"id": "repair-1"}, "openai-chat", "content"),
                (repaired, {"id": "repair-2"}, "openai-chat", "content"),
            ],
        ) as call_model:
            result, metadata = generate_product_script.repair_script_audio(
                config,
                args,
                overlong,
                reference,
                "测试音频缩写",
            )

        self.assertEqual(call_model.call_count, 2)
        self.assertIn("Go now", result)
        self.assertEqual(len(metadata["attempts"]), 2)

    def test_sfx_audio_description_is_not_counted_as_spoken_dialogue(self):
        script = """### 镜头 1 (00:00.000 - 00:01.000)

[音频文案] 揉搓胡须的声效（SFX）。

[音频交付模式] voiceover
"""

        self.assertEqual(
            generate_product_script.classify_audio_content("揉搓胡须的声效（SFX）。"),
            "sfx",
        )
        self.assertFalse(generate_product_script.validate_audio_fit(script))
        self.assertNotIn("001", generate_product_script.extract_audio_profiles(script))

        normalized = generate_product_script.normalize_nonspoken_audio_fields(script)
        self.assertIn("[环境音/音效] 揉搓胡须的声效（SFX）。", normalized)
        self.assertNotIn("[音频文案]", normalized)

    def test_mixed_spoken_dialogue_and_sfx_counts_only_quoted_dialogue(self):
        metrics = generate_product_script.spoken_audio_metrics(
            '"Wait now!" followed by a loud splash sound effect.'
        )

        self.assertEqual(
            generate_product_script.classify_audio_content(
                '"Wait now!" followed by a loud splash sound effect.'
            ),
            "spoken",
        )
        self.assertEqual(metrics["spoken_text"], "Wait now!")
        self.assertEqual(metrics["word_count"], 2)

    def test_silent_reference_shot_removes_generated_voice_fields_only(self):
        reference = """### 镜头 1 (00:00.000 - 00:01.000)

[背景音乐] 悬疑音乐

### 镜头 2 (00:01.000 - 00:03.000)

[音频文案] (意大利语): “Guarda qui.”（中文翻译对照：看这里。）
"""
        generated = """### 镜头 1 (00:00.000 - 00:01.000)

* **[声音/语气]**：紧张急促。
* **[音频文案]** on-screen。男子大喊。
(意大利语): “Corri subito.”
* **[音频交付模式]** on-screen
* **[背景音乐]**：悬疑音乐

### 镜头 2 (00:01.000 - 00:03.000)

* **[声音/语气]**：自然。
* **[音频文案]**：(意大利语): “Guarda qui.”（中文翻译对照：看这里。）
* **[音频交付模式]** voiceover
"""

        corrected, warnings = generate_product_script.enforce_reference_audio_structure(reference, generated)

        first_shot, second_shot = corrected.split("### 镜头 2", 1)
        self.assertNotIn("[声音/语气]", first_shot)
        self.assertNotIn("[音频文案]", first_shot)
        self.assertNotIn("[音频交付模式]", first_shot)
        self.assertNotIn("Corri subito", first_shot)
        self.assertIn("[背景音乐]", first_shot)
        self.assertIn("[音频文案]", second_shot)
        self.assertIn("Guarda qui", second_shot)
        self.assertEqual(len(warnings), 1)
        self.assertIn("镜头 ['001']", warnings[0])

    def test_all_silent_reference_saves_clone_without_model_added_audio(self):
        reference = """### 镜头 1 (00:00.000 - 00:01.000)

[背景音乐] 轻快音乐
"""
        clone = """### 镜头 1 (00:00.000 - 00:01.000)

* **[声音/语气]**：兴奋。
* **[音频文案]**：(意大利语): “Compra ora.”（中文翻译对照：立即购买。）
* **[音频交付模式]** voiceover
* **[背景音乐]**：轻快音乐
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference_path = root / "IT-author-1234567890123456789.md"
            reference_path.write_text(reference, encoding="utf-8")
            config = {
                "script_reference_script_path": str(reference_path),
                "script_product_document_path": str(root / "DRN-E99Pro无人机-产品信息.md"),
            }

            output_paths, _raw_paths = generate_product_script.write_script_outputs(
                config,
                str(root / "outputs"),
                clone,
                {},
            )

            saved = output_paths[0].read_text(encoding="utf-8")
            self.assertNotIn("[声音/语气]", saved)
            self.assertNotIn("[音频文案]", saved)
            self.assertNotIn("[音频交付模式]", saved)
            self.assertIn("[背景音乐]", saved)

    def test_subject_type_lock_detects_skeleton_replaced_by_real_person(self):
        reference = """### 镜头 1 (00:00.000 - 00:02.000)

[主体] 一个头顶稀疏的人体骨骼模型。

### 镜头 2 (00:02.000 - 00:04.000)

[主体] 无人物主体，画面中心为毛囊动画。
"""
        generated = """### 镜头 1 (00:00.000 - 00:02.000)

* **[主体]**：一个30岁的意大利真人男性，头顶发量稀疏。

### 镜头 2 (00:02.000 - 00:04.000)

* **[主体]**：一个年轻真人女性正在观察头皮。
"""

        issues = generate_product_script.validate_subject_type_lock(reference, generated)

        self.assertEqual([issue["shot_key"] for issue in issues], ["001", "002"])
        self.assertEqual(issues[0]["reference_type"], "skeleton")
        self.assertEqual(issues[0]["generated_type"], "human")
        self.assertEqual(issues[1]["reference_type"], "no_person")

    def test_subject_type_repair_restores_skeleton_and_reference_timeline(self):
        reference = """### 镜头 1 (00:00.000 - 00:02.000)

[主体] 一个头顶稀疏的人体骨骼模型。
"""
        generated = """### 镜头 1 (00:00.000 - 00:03.000)

* **[主体]**：一个30岁的意大利真人男性。
"""
        repaired = """### 镜头 1 (00:00.000 - 00:04.000)

* **[主体]**：一个头顶稀疏、穿意大利家居服的人体骨骼模型。
"""
        config = {}
        args = argparse.Namespace(backend="api")

        with patch.object(
            generate_product_script,
            "call_text_model",
            return_value=(repaired, {"id": "subject-repair"}, "openai-chat", "content"),
        ):
            result, metadata = generate_product_script.repair_script_subject_type(
                config,
                args,
                generated,
                reference,
                "测试主体类型纠正",
            )

        self.assertIn("镜头 1 (00:00.000 - 00:02.000)", result)
        self.assertIn("人体骨骼模型", result)
        self.assertFalse(generate_product_script.validate_subject_type_lock(reference, result))
        self.assertTrue(metadata["repair_requested"])

    def test_subject_type_mismatch_is_rejected_before_markdown_is_written(self):
        reference = """### 镜头 1 (00:00.000 - 00:02.000)

[主体] 一个头顶稀疏的人体骨骼模型。
"""
        generated = """### 镜头 1 (00:00.000 - 00:02.000)

* **[主体]**：一个30岁的意大利真人男性。
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "outputs"
            reference_path = root / "IT-author-1234567890123456789.md"
            reference_path.write_text(reference, encoding="utf-8")
            config = {
                "script_reference_script_path": str(reference_path),
                "script_product_document_path": str(root / "TR05-TROIL生发精华-产品信息.md"),
            }

            with self.assertRaisesRegex(RuntimeError, "主体类型校验失败"):
                generate_product_script.write_script_outputs(
                    config,
                    str(output_dir),
                    generated,
                    {},
                )

            self.assertFalse(list(output_dir.glob("*.md")))

    def test_recloning_overwrites_existing_clone_and_raw_response(self):
        reference = """### 镜头 1 (00:00.000 - 00:01.000)
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "outputs"
            reference_path = root / "VN-author-1234567890123456789.md"
            reference_path.write_text(reference, encoding="utf-8")
            config = {
                "script_reference_script_path": str(reference_path),
                "script_product_document_path": str(root / "SIMC01-SIMC染发棒-产品信息.md"),
            }

            first_paths, first_raw_paths = generate_product_script.write_script_outputs(
                config,
                str(output_dir),
                "### 镜头 1 (00:00.000 - 00:01.000)\n第一次复刻",
                {"generation_marker": "first"},
            )
            second_paths, second_raw_paths = generate_product_script.write_script_outputs(
                config,
                str(output_dir),
                "### 镜头 1 (00:00.000 - 00:01.000)\n第二次复刻",
                {"generation_marker": "second"},
            )

            self.assertEqual(second_paths, first_paths)
            self.assertEqual(second_raw_paths, first_raw_paths)
            self.assertIn("第二次复刻", second_paths[0].read_text(encoding="utf-8"))
            self.assertNotIn("第一次复刻", second_paths[0].read_text(encoding="utf-8"))
            raw_payload = json.loads(second_raw_paths[0].read_text(encoding="utf-8"))
            self.assertEqual(raw_payload["generation_marker"], "second")
            self.assertEqual(len(list(output_dir.glob("复刻-*.md"))), 1)
            self.assertEqual(len(list(output_dir.glob("复刻-*.raw.json"))), 1)

    def test_vietnam_and_philippines_country_defaults(self):
        self.assertEqual(generate_product_script.COUNTRY_DEFAULT_LANGUAGE["越南"], "越南语")
        self.assertEqual(generate_product_script.COUNTRY_DEFAULT_LANGUAGE["菲律宾"], "菲律宾语")
        self.assertEqual(generate_product_script.COUNTRY_FILENAME_CODE["越南"], "VN")
        self.assertEqual(generate_product_script.COUNTRY_FILENAME_CODE["菲律宾"], "PH")

    def test_local_model_settings_override_shared_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            shared = root / "model_defaults.json"
            local = root / "model_settings.json"
            inputs = root / "inputs.json"
            shared.write_text(
                json.dumps({"modelmesh_base_url": "https://shared.test", "script_generation_model": "shared-model"}),
                encoding="utf-8",
            )
            local.write_text(
                json.dumps({"modelmesh_api_key": "secret", "modelmesh_base_url": "https://stale.test"}),
                encoding="utf-8",
            )
            inputs.write_text("{}", encoding="utf-8")

            with (
                patch.object(generate_product_script, "SHARED_MODEL_SETTINGS_PATH", shared),
                patch.object(generate_product_script, "LOCAL_MODEL_SETTINGS_PATH", local),
                patch.object(generate_product_script, "SCRIPT_INPUTS_PATH", inputs),
                patch.object(generate_product_script, "ensure_runtime_model_defaults"),
            ):
                config = generate_product_script.load_script_generation_config()

        self.assertEqual(config["modelmesh_base_url"], "https://stale.test")
        self.assertEqual(config["script_generation_model"], "shared-model")
        self.assertEqual(config["modelmesh_api_key"], "secret")

    def test_runtime_model_defaults_are_created_without_bundled_config_access(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shared = Path(temp_dir) / "runtime" / "model_defaults.json"

            with patch.object(generate_product_script, "SHARED_MODEL_SETTINGS_PATH", shared):
                generate_product_script.ensure_runtime_model_defaults()

            defaults = json.loads(shared.read_text(encoding="utf-8"))
            self.assertEqual(defaults["modelmesh_base_url"], generate_product_script.DEFAULT_BASE_URL)
            self.assertEqual(defaults["script_generation_model"], generate_product_script.DEFAULT_MODEL)
            self.assertEqual(shared.stat().st_mode & 0o777, 0o600)

    def test_legacy_local_configs_migrate_to_runtime_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_inputs = root / "legacy" / "inputs.json"
            legacy_model = root / "legacy" / "model_settings.json"
            runtime_inputs = root / "runtime" / "inputs.json"
            runtime_model = root / "runtime" / "model_settings.json"
            legacy_inputs.parent.mkdir()
            legacy_inputs.write_text(json.dumps({"script_country": "美国"}), encoding="utf-8")
            legacy_model.write_text(json.dumps({"modelmesh_api_key": "secret"}), encoding="utf-8")

            with (
                patch.object(generate_product_script, "LEGACY_LOCAL_INPUTS_PATH", legacy_inputs),
                patch.object(generate_product_script, "LEGACY_LOCAL_MODEL_SETTINGS_PATH", legacy_model),
                patch.object(generate_product_script, "LOCAL_INPUTS_PATH", runtime_inputs),
                patch.object(generate_product_script, "LOCAL_MODEL_SETTINGS_PATH", runtime_model),
            ):
                migrated = generate_product_script.migrate_legacy_local_configs()

            self.assertEqual(migrated, [runtime_inputs, runtime_model])
            self.assertEqual(json.loads(runtime_inputs.read_text(encoding="utf-8"))["script_country"], "美国")
            self.assertEqual(json.loads(runtime_model.read_text(encoding="utf-8"))["modelmesh_api_key"], "secret")
            self.assertEqual(runtime_inputs.stat().st_mode & 0o777, 0o600)
            self.assertEqual(runtime_model.stat().st_mode & 0o777, 0o600)

    def test_main_creates_explicit_product_output_dir_without_saved_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "JR01-天然矿石戒指"
            args = argparse.Namespace(
                product_doc=str(Path(temp_dir) / "JR01-天然矿石戒指-产品信息.md"),
                output_dir=str(output_dir),
                dry_run=False,
            )

            def run_pipeline(_config, _args):
                self.assertTrue(output_dir.is_dir())
                return "script", {}, "endpoint", "field"

            with (
                patch.object(generate_product_script, "parse_args", return_value=args),
                patch.object(generate_product_script, "load_script_generation_config", return_value={}),
                patch.object(generate_product_script, "apply_cli_overrides", return_value={"script_product_document_path": args.product_doc}),
                patch.object(generate_product_script, "product_project_ready", return_value=False),
                patch.object(generate_product_script, "require_product_project") as require_project,
                patch.object(generate_product_script, "run_script_pipeline", side_effect=run_pipeline),
                patch.object(generate_product_script, "write_script_outputs", return_value=([], [])),
            ):
                generate_product_script.main()

            require_project.assert_not_called()


if __name__ == "__main__":
    unittest.main()
