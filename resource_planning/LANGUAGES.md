# 中文与英文演示

完整流水线默认语言为英文；中文输出请显式传入 `--language zh`。`--language en` 在最终渲染计划阶段翻译展示文本，不重新生成英文版的检索或教学方案。

完整流程：

```powershell
.venv/Scripts/python.exe -m resource_planning.pipeline "高速缓存如何减少访存延迟？" --language en --tts --out-dir out_student_en
```

已有成功内容推荐使用独立转换入口，保留中文版：

```powershell
.venv/Scripts/python.exe -m resource_planning.localization out_student/render_plan.json --out-dir out_student_en --tts
```

输出包括英文 `render_plan.json`、启用 TTS 时的 `render_plan_voiced.json` 和 `audio/`，以及英文 `generated_explanation.py`。随后使用现有 renderer 渲染新脚本。

翻译覆盖问题、子问题、前置概念标题、旁白、字幕、节点名称/定义、摘要以及生成脚本内的固定动画文字。节点、关系及 beat 的标识保留；旧音频引用移除，重新合成英文音频。中文原文件不受独立转换入口影响，输出目录应使用不同目录。

中文默认语音 `zh-CN-YunxiNeural`，英文默认 `en-US-JennyNeural`，可通过 `--voice` 指定。英文文本翻译使用现有 Deepseek 配置；音频使用现有 Azure Speech 配置。省略 `--tts` 可只生成英文文本和脚本。

翻译批次会检查数量、非空和残留中文，失败时明确报错，不静默混用两种语言。语义忠实度和英文长标签布局仍需人工视觉检查；当前单元测试不代表已通过在线翻译和视频渲染验收。
