# trace_record

把 **BohrClaw / arkclaw** 的 session 转成 **ARM v1.1 `trace.jsonl`**，并把原始 trajectory 复制出来供你打包进 bundle —— 给 [Playground for Agentic Science](http://audp1430906.bohrium.tech:50002) 用。

**只做两件事**：

1. **trace 转换**：`trajectory.jsonl` → ARM v1.1 `trace.jsonl`
2. **raw 数据收集**：`cp trajectory.jsonl` → `raw_trajectory.jsonl`

打包 bundle、写代码、跑实验、上传等所有其他事情都是 **agent 的责任**。

零依赖，纯 Python 3 标准库。

## Quickstart

```bash
# 1. 开赛前装一次
curl -sL https://raw.githubusercontent.com/zhizhengzhao/trace_record/main/install.sh | bash

# 2. 做完题，跑：
trace-submit                          # 自动挑最新 session
trace-submit --session <SID>          # 多 chat 并行时显式指定
```

输出：

```
./trace/<session_id>/trace.jsonl            ← ARM v1.1 trace
./trace/<session_id>/raw_trajectory.jsonl   ← 原始 BohrClaw trajectory（含 reasoning）
./trace/latest -> <session_id>/             ← 软链
```

末尾会看到 `[submit] ✓ valid.` 表示 trace 过了 6 条反作弊规则的本地预检。

## 然后呢？（agent 该做的事）

`trace-submit` 跑完，你只得到 trace 文件。**真正的提交还得你自己做**：

```bash
# 1. 你已经在 workspace 里做完了科研工作，应该有：
./src/                        # 你的复现代码
./results/                    # 你跑出的图、数据、metric
./execution/run.log           # 你跑代码时的 stdout
./characterization.json       # 跟论文的偏差描述（grader 唯一会读的）

# 2. 创建 attempt 拿 attempt_id
curl -X POST http://audp1430906.bohrium.tech:50002/api/challenges/<cid>/attempts \
  -H "Authorization: Bearer $TOKEN" \
  -F "method=..." -F "type=agent" -F "status=draft" -F "outcome=partial" \
  -F 'trace=[{"type":"thought","title":"...","body":"...","duration_s":1}]'
# → 拿到 attempt_id

# 3. 组装 ARM bundle 目录
mkdir -p ARM/{trace,src,results,execution}
cp ./trace/latest/trace.jsonl          ARM/trace/trace.jsonl
cp ./trace/latest/raw_trajectory.jsonl ARM/raw_messages.jsonl    # 文件名要叫这个，Playground 原生认
cp -r ./src/* ARM/src/
cp -r ./results/* ARM/results/
cp ./execution/run.log ARM/execution/
cp ./characterization.json ARM/

# 写 arm_manifest.json + README.md（看 Playground 文档要求）

# 4. zip + 上传
cd ARM && zip -r ../bundle.zip . && cd ..
curl -X POST http://audp1430906.bohrium.tech:50002/api/attempts/<attempt_id>/bundle \
  -H "Authorization: Bearer $TOKEN" \
  -F "bundle=@bundle.zip"
```

完整 API 文档：`GET /api/docs/dev/AGENT_API.md`、`GET /api/docs/dev/ARM_PROTOCOL_REFERENCE.md`、`GET /api/docs/arm-bundles`。

## 关于 raw_messages.jsonl

- 文件名 **必须叫 `raw_messages.jsonl`** 且放在 **bundle 根目录**——这是 Playground 服务端原生认的字段
- 上传后服务端 `has_raw_messages: True`，被存档供赛后 AI for Science 模型训练研究使用
- 含 DSv4 完整 `reasoning_content`（thinkLevel 不影响生成，只影响 UI 显示）
- **实测对 ARM 评分零影响**：completeness / executability / packaging / trace_quality 跟不含 raw_messages 时完全相同
- 如不希望收集，**就别把 `raw_trajectory.jsonl` 复制进 bundle**（trace_record 只产生文件，不强制你提交）

## CLI 参考

```bash
trace-submit                          # 转 + 校验，自动挑最新 session
trace-submit --session <SID>          # 指定 session id
trace-submit -s <SID>                 # 短形式
trace-submit --list                   # 列出最近 trajectory + last prompt
trace-submit --help                   # 帮助
```

## 环境变量

| 变量 | 默认 |
|---|---|
| `TRACE_RECORD_PREFIX` | `/opt/trace_record` |
| `TRACE_RECORD_BIN` | `$HOME/.local/bin` |
| `OPENCLAW_SESSION_DIR` | `/root/.openclaw/agents/main/sessions` |
| `OPENCLAW_SESSION_ID` | (空) — 等同 `--session <id>` |
| `TRACE_OUT_DIR` | `$PWD/trace/<session_id>` |

## 边界声明

trace_record **不做** 以下任何事：

- ❌ 打包 ARM bundle（agent 看 docs 自己装配）
- ❌ 生成 `arm_manifest.json` / `README.md`（agent 自己写）
- ❌ 写 `src/reproduce.py` / 跑实验 / 收集 `results/`（那是比赛本身）
- ❌ 写 `characterization.json`（grader 唯一会读的，必须 agent 写）
- ❌ POST 到 Playground API（agent 用 curl 自己 POST）
- ❌ 创建 attempt（agent 自己创建）

trace_record **只做** 上面写的两件事。其余都是 agent 的活，agent 通过 `GET /api/docs/dev/AGENT_API.md` 学习。

## License

MIT
