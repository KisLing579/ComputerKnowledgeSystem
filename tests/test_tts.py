import tempfile
import unittest
import wave
import io
import sys
import types
from unittest.mock import Mock, patch
from pathlib import Path

from resource_planning.tts import AzureTTS, add_narration, wav_duration
from rendering.manim.script_generator import ManimScriptGenerator


class TTSTests(unittest.TestCase):
    def test_azure_uses_memory_output_and_closes_file_before_rename(self):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(24000)
            f.writeframes(b"\x00\x00" * 24000)
        sdk = types.ModuleType("azure.cognitiveservices.speech")
        sdk.SpeechConfig = Mock()
        sdk.SpeechSynthesisOutputFormat = types.SimpleNamespace(Riff24Khz16BitMonoPcm=1)
        sdk.ResultReason = types.SimpleNamespace(SynthesizingAudioCompleted=1)
        sdk.SpeechSynthesizer = Mock()
        sdk.SpeechSynthesizer.return_value.speak_text_async.return_value.get.return_value = types.SimpleNamespace(
            reason=1, audio_data=buffer.getvalue())
        azure = types.ModuleType("azure")
        cognitive = types.ModuleType("azure.cognitiveservices")
        azure.cognitiveservices = cognitive
        cognitive.speech = sdk
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {
            "azure": azure, "azure.cognitiveservices": cognitive, "azure.cognitiveservices.speech": sdk,
        }):
            engine = AzureTTS(key="test-key")
            path, duration = engine.synthesize("test", "voice", directory)
            self.assertEqual(duration, 1)
            self.assertEqual(Path(path).read_bytes(), buffer.getvalue())
            self.assertEqual(list(Path(directory).glob("*.wav")), [Path(path)])
            self.assertIsNone(sdk.SpeechSynthesizer.call_args.kwargs["audio_config"])
            self.assertEqual(engine.synthesize("test", "voice", directory), (path, duration))
            sdk.SpeechSynthesizer.assert_called_once()

    def test_consecutive_subtitles_share_audio_and_repeated_text_is_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "voice.wav"
            with wave.open(str(audio), "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(24000)
                f.writeframes(b"\x00\x00" * 24000)
            self.assertEqual(wav_duration(audio), 1)
            class Engine:
                calls = []
                def synthesize(self, text, voice, output_dir):
                    self.calls.append(text)
                    return str(audio), 1
            engine = Engine()
            plan = {"question": "A", "scenes": [{"beats": [{"narration": text} for text in ("A", "A", "", "B", "A")]}]}
            result = add_narration(plan, engine, directory)
            beats = result["scenes"][0]["beats"]
            self.assertEqual(engine.calls, ["A", "B"])
            self.assertEqual(result["opening_audio"], {"path": str(audio.resolve()), "duration": 1})
            self.assertNotIn("opening_audio", plan)
            self.assertIn("audio", beats[0])
            self.assertNotIn("audio_end", beats[0])
            self.assertNotIn("audio", beats[1])
            self.assertTrue(beats[1]["audio_end"])
            self.assertNotIn("audio", beats[2])
            self.assertTrue(beats[4]["audio_end"])
            self.assertNotIn("audio", plan["scenes"][0]["beats"][0])
            script = ManimScriptGenerator().generate_payload(result, Path(directory) / "scene.py")
            compile(script.read_text(encoding="utf-8"), str(script), "exec")
            from rendering.manim.render import audio_references
            self.assertEqual(audio_references(script)[0], str(audio.resolve()))

    def test_failed_synthesis_is_not_silently_accepted(self):
        class Engine:
            def synthesize(self, *args): return "", 0
        with self.assertRaises(ValueError):
            add_narration({"scenes": [{"beats": [{"narration": "A"}]}]}, Engine(), ".")
