# Ollama Qwen3-4B Sibling 使用说明

本文说明如何在本机 RTX 4060 Laptop 8GB 上运行攻击侧 `SIBLING_MODEL`。本地模型
只用于 MEntA 输入生成、IA/DCMI attacker 和可选 Spoof，不替换 victim Generator。

## 当前固定配置

| 项目 | 值 |
|---|---|
| Ollama 程序 | `D:\Ollama` |
| Ollama 版本 | `0.32.5` |
| 模型目录 | `D:\Ollama\models` |
| 上游模型 | `qwen3:4b-q4_K_M` |
| 项目别名 | `pcv-qwen3-4b:q4km-8k` |
| 项目模型 ID | `39297c75a309` |
| 上下文 | 8192 |
| KV cache | `q8_0` |
| 并发 | 1 |
| sibling 限速 | 无令牌桶、无固定间隔 |
| victim 限速 | 保持 `generation.requests_per_minute=4` |

## 本机验证状态

- OpenAI-compatible 冒烟：返回 model 与别名一致，JSON 正常，thinking 为空；冷启动 53.167s。
- 30 条功能门禁：Edgar/Enron/PubMed 各 10 条全部通过，p95 分别为
  2.462s、1.834s、2.403s。
- 50 条稳定性门禁：50/50 通过，p95 1.735s，最大单条 1.910s。
- BGE 同驻：`ollama ps` 为 100% GPU、8192 context；GPU 峰值
  3983MiB/8188MiB，无 OOM、超时或 CPU fallback。

## 环境变量

这些变量已写入当前 Windows 用户环境。新终端和重新登录后自动生效：

```text
OLLAMA_HOST=127.0.0.1:11434
OLLAMA_MODELS=D:\Ollama\models
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KV_CACHE_TYPE=q8_0
OLLAMA_KEEP_ALIVE=10m
```

核对命令：

```powershell
reg query HKCU\Environment
```

## 启动与停止

健康检查成功时无需重复启动：

```powershell
curl.exe -fsS http://127.0.0.1:11434/api/version
```

手动启动隐藏服务：

```powershell
Start-Process -FilePath "D:\Ollama\ollama.exe" `
  -ArgumentList "serve" -WindowStyle Hidden
```

停止 Ollama：

```powershell
Stop-Process -Name "ollama","ollama app" -Force -ErrorAction SilentlyContinue
```

修改 Ollama 环境变量后必须重启服务。

## 模型安装与别名

拉取固定量化模型：

```powershell
D:\Ollama\ollama.exe pull qwen3:4b-q4_K_M
```

创建项目 8K 别名：

```powershell
D:\Ollama\ollama.exe create pcv-qwen3-4b:q4km-8k `
  -f configs\qwen3_4b_q4km_8k.Modelfile
D:\Ollama\ollama.exe list
```

`ollama list` 的 `ID` 是需要冻结的实际模型摘要。不要用模型名或占位文本代替。

## 项目 `.env`

```dotenv
PCV_SIBLING_PROFILE=ollama_qwen3_4b
PCV_SIBLING_API_KEY=ollama
PCV_SIBLING_BASE_URL=http://127.0.0.1:11434/v1
PCV_SIBLING_MODEL=pcv-qwen3-4b:q4km-8k
PCV_SIBLING_MODEL_VERSION=ollama:39297c75a309
```

`PCV_SIBLING_API_KEY=ollama` 只是 OpenAI-compatible 客户端的兼容字段，Ollama 会忽略。
本地 profile 要求实际 ID，缺失或漂移会在请求前 fail closed。

## API 冒烟测试

```powershell
$body = @{
  model = "pcv-qwen3-4b:q4km-8k"
  messages = @(@{role = "user"; content = 'Return JSON only: {"ok": true}'})
  temperature = 0
  max_tokens = 64
  reasoning_effort = "none"
  seed = 42
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri "http://127.0.0.1:11434/v1/chat/completions" `
  -Method Post -ContentType "application/json" -Body $body
```

返回的 `model` 必须精确等于 `pcv-qwen3-4b:q4km-8k`，回答不得包含 `<think>`。

## 30 条功能门禁

小样本必须写入诊断目录，不能写入正式 `menta_inputs`：

```powershell
$python = "D:\python\anaconda\envs\mia_model\python.exe"
$datasets = "edgar","enron","pubmed"
foreach ($dataset in $datasets) {
  & $python -B scripts\27_prepare_menta_inputs.py `
    --dataset $dataset `
    --sibling-profile ollama_qwen3_4b `
    --max-targets 10 `
    --max-p95-seconds 30 `
    --output-dir artifacts\v20\local_sibling_gate\functional `
    --force
}
```

脚本会 fail closed 检查：HTTP/JSON 成功、每条恰好 5 个唯一问题、无 thinking
泄漏、provider model ID 一致、profile/model 摘要不漂移。manifest 中的
`latency_p95_ms` 必须不超过 30000，`latency_gate_passed` 必须为 `true`。

## 50 次稳定性与 GPU 门禁

先让正式 BGE retriever 驻留，再运行至少 50 次 sibling 请求：

```powershell
$env:HF_HUB_OFFLINE = "1"
$python = "D:\python\anaconda\envs\mia_model\python.exe"
& $python -B -c "from sentence_transformers import SentenceTransformer; m=SentenceTransformer('BAAI/bge-base-en-v1.5', revision='a5beb1e3e68b9ab74eb54cfd186867f64f240e1a', local_files_only=True, device='cuda'); m.encode(['BGE residency probe'], convert_to_tensor=True); print('BGE_READY'); input('Press Enter to release BGE: ')"
```

看到 `BGE_READY` 后保持该终端不关闭，在另一个终端运行 50 条门禁：

```powershell
$python = "D:\python\anaconda\envs\mia_model\python.exe"
& $python -B scripts\27_prepare_menta_inputs.py `
  --dataset enron `
  --sibling-profile ollama_qwen3_4b `
  --max-targets 50 `
  --max-p95-seconds 30 `
  --output-dir artifacts\v20\local_sibling_gate\stability `
  --force
```

运行期间另开终端监控：

```powershell
D:\Ollama\ollama.exe ps
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv -l 1
```

门禁要求：`ollama ps` 显示 100% GPU、无 OOM/超时，独显峰值约不超过 7.2GiB。
本地 sibling 不设置令牌桶；单并发由 `OLLAMA_NUM_PARALLEL=1` 保证。victim 仍使用
独立 4 RPM 令牌桶。

若某次 JSON 结构或问题唯一性校验失败，准备脚本最多做 2 次带纠错提示的重试；
模型身份漂移、thinking 泄漏和 provider model ID 漂移仍立即失败，不会被重试掩盖。

## 正式 MEntA 输入

只有功能和稳定性门禁全部通过后，才允许在 clean release commit 上运行：

```powershell
D:\python\anaconda\envs\mia_model\python.exe -B `
  scripts\27_prepare_menta_inputs.py `
  --dataset enron `
  --sibling-profile ollama_qwen3_4b
```

Edgar、Enron、PubMed 必须分别生成；不得将诊断目录或旧云端 sibling 结果复制到正式目录。

## 4K 显存降级

只有 8K 门禁发生 OOM、CPU fallback 或峰值显存超限时才降级。复制 Modelfile，
把 `num_ctx` 改为 4096，并创建新别名，例如 `pcv-qwen3-4b:q4km-4k`。随后更新
profile/`.env`、冻结新 ID，并从 30 条功能门禁开始全部重跑。禁止沿用 8K 产物。

## 常见问题

- `connection refused`：Ollama 服务未启动，先运行健康检查和启动命令。
- `actual model ID` 报错：`.env` 缺少真实 `PCV_SIBLING_MODEL_VERSION`。
- `provider_model_identity_drift`：服务返回了别的模型，停止并检查 alias/服务实例。
- 出现 `<think>`：thinking 关闭失败，禁止继续生成正式 artifact。
- 模型写入 C 盘：检查桌面用户的 `OLLAMA_MODELS`，重启服务后再 pull。
- sibling 请求仍等待 20 秒：确认 profile 为 `ollama_qwen3_4b`；其 RPM/interval
  必须都是 0。不要修改 victim 的 `generation.requests_per_minute=4`。
