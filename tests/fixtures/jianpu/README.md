# 真实简谱测试图片

这里放用户提供的印刷/截图简谱。识别基线不要求所有图片都有标注：

- 有 `<图片名>.expected.txt`：输出音级、时值、小节四项指标。
- 没有 expected：只输出结构统计（音符数、警告数、弧线数、低置信度比例），并标记为未标注。
- 不把识别器自己的输出当作 ground truth。

## expected 格式

使用 `pitchlens.core.jianpu_text` 的紧凑格式，例如：

```text
1=C 4/4 90
| 1 2 3 5 | 6 5 3 - | 2 3 5 3 | 1 - - - |
```

`1'` 高八度，`1,` 低八度，`1_` 八分音符，`1__` 十六分，`1.` 附点，`-` 延长一拍，`0` 休止，`#4`/`b7` 升降音。

## 运行

```powershell
$env:PITCHLENS_REAL_OCR = "1"
.\.venv\Scripts\python.exe -m unittest tests.test_recognition_real -v
```

报告写入 `baseline_report.json`。真实图片的标注工作量较大，建议先标注 3–5 张最具代表性的，再逐步扩展。
