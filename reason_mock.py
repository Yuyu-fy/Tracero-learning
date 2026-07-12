import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def build_prompt(mock_data):
    return f"""
你是 Tracero 的机器人故障分析助手。

请只基于下面的 evidence 做分析，不要编造没有证据支持的信息。
输出必须包含三行：
【事实】...
【推理】...
【建议】...

重要规则：
1. 每一行结论都必须引用至少一个 evidence_id，例如 [E-01]。
2. 如果证据不足，要明确说“证据不足”，但仍然引用相关 evidence_id。
3. 不要输出 Markdown 表格。

mock evidence:
{json.dumps(mock_data, ensure_ascii=False, indent=2)}
""".strip()


def call_deepseek(prompt, model):
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("没有找到环境变量 DEEPSEEK_API_KEY")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是一个严格基于证据回答的机器人故障分析助手。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }

    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API 请求失败：{exc.code} {error_body}") from exc

    return body["choices"][0]["message"]["content"]


def main():
    parser = argparse.ArgumentParser(description="Run Tracero mock evidence reasoning.")
    parser.add_argument("json_path", help="Path to mock evidence JSON file")
    parser.add_argument("--model", default="deepseek-chat", help="DeepSeek model name")
    args = parser.parse_args()

    with open(args.json_path, "r", encoding="utf-8") as file:
        mock_data = json.load(file)

    prompt = build_prompt(mock_data)

    try:
        output = call_deepseek(prompt, args.model)
    except Exception as exc:
        print(f"出错了：{exc}", file=sys.stderr)
        print("\n如果你还没设置 key，先运行：", file=sys.stderr)
        print("export DEEPSEEK_API_KEY='你的 API Key'", file=sys.stderr)
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
