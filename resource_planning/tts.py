"""Azure narration preparation; also works on an existing render_plan.json."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import uuid
import wave
from abc import ABC, abstractmethod
from pathlib import Path


class BaseTTS(ABC):
    @abstractmethod
    def synthesize(self, text: str, voice: str, output_dir: str, language: str = "") -> tuple[str, float]:
        raise NotImplementedError

    def release(self):
        pass


class AzureTTS(BaseTTS):
    def __init__(self, region: str = "", key: str = ""):
        self.region = region or os.getenv("AZURE_SPEECH_REGION", "westus")
        self.key = key or os.getenv("AZURE_SPEECH_KEY", "")

    def synthesize(self, text, voice, output_dir, language=""):
        voice = voice or "zh-CN-YunxiNeural"
        digest = hashlib.sha256(json.dumps([text, voice, self.region, "pcm24-v1"], ensure_ascii=False).encode()).hexdigest()
        target = Path(output_dir).resolve() / f"{digest}.wav"
        if target.exists():
            try:
                return str(target), wav_duration(target)
            except (wave.Error, EOFError, ValueError):
                pass
        if not self.key:
            raise ValueError("Set AZURE_SPEECH_KEY before enabling Azure narration")
        try:
            import azure.cognitiveservices.speech as sdk
        except ImportError as exc:
            raise RuntimeError("Install requirements-tts.txt to enable Azure narration") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{digest}.{uuid.uuid4().hex}.wav")
        try:
            config = sdk.SpeechConfig(subscription=self.key, region=self.region)
            config.speech_synthesis_voice_name = voice
            config.set_speech_synthesis_output_format(sdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm)
            # Keep Azure's native file handles out of the cache lifecycle.
            synth = sdk.SpeechSynthesizer(speech_config=config, audio_config=None)
            result = synth.speak_text_async(text).get()
            if result.reason != sdk.ResultReason.SynthesizingAudioCompleted:
                raise RuntimeError("Azure speech synthesis failed; check credentials, region and voice")
            temporary.write_bytes(result.audio_data)
            duration = wav_duration(temporary)
            temporary.replace(target)
            return str(target), duration
        finally:
            temporary.unlink(missing_ok=True)


def wav_duration(path):
    with wave.open(str(path), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    if duration <= 0:
        raise ValueError("TTS produced empty audio")
    return duration


def add_narration(payload: dict, engine: BaseTTS, output_dir: str, voice=None) -> dict:
    voice = voice or ('en-US-JennyNeural' if payload.get('metadata', {}).get('language') == 'en' else 'zh-CN-YunxiNeural')
    from rendering.subgraph import add_subquestion_intros, group_subquestions
    result = add_subquestion_intros(group_subquestions(payload))
    cache = {}
    result.pop("opening_audio", None)
    question = result.get("question", "").strip()
    if question:
        path, duration = engine.synthesize(question, voice, output_dir)
        if not path or duration <= 0 or not Path(path).is_file():
            raise ValueError("TTS returned invalid opening audio")
        cache[question] = (path, duration)
        result["opening_audio"] = {"path": str(Path(path).resolve()), "duration": duration}
    for scene in result.get("scenes", []):
        beats = scene.get("beats", [])
        for beat in beats:
            beat.pop("audio", None)
            beat.pop("audio_end", None)
        i = 0
        while i < len(beats):
            text = beats[i].get("narration", "").strip()
            end = i + 1
            while end < len(beats) and beats[end].get("narration", "").strip() == text:
                end += 1
            if text:
                if text not in cache:
                    cache[text] = engine.synthesize(text, voice, output_dir)
                path, duration = cache[text]
                if not path or duration <= 0 or not Path(path).is_file():
                    raise ValueError("TTS returned invalid audio")
                beats[i]["audio"] = {"path": str(Path(path).resolve()), "duration": duration}
                beats[end - 1]["audio_end"] = True
            i = end
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--voice", default=None)
    args = parser.parse_args()
    from rendering.manim.script_generator import ManimScriptGenerator
    payload = add_narration(json.loads(args.plan.read_text(encoding="utf-8")), AzureTTS(),
                            str(args.plan.resolve().parent / "audio"), args.voice)
    output = args.plan.with_name("render_plan_voiced.json")
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    script = ManimScriptGenerator().generate_payload(payload, args.plan.with_name("generated_explanation.py"))
    print(f"Voiced script: {script}")


if __name__ == "__main__":
    main()
