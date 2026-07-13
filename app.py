import json
import os
import re
import urllib.error
import urllib.request

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(title="Tracero Backend")


class ReasonRequest(BaseModel):
    evidence_type: str
    evidence: list[dict]


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


def call_deepseek(prompt, model="deepseek-chat"):
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


def collect_evidence_ids(mock_data):
    evidence_ids = set()
    for item in mock_data.get("evidence", []):
        evidence_id = item.get("evidence_id")
        if evidence_id:
            evidence_ids.add(evidence_id)
    return evidence_ids


def verify_output(output, valid_evidence_ids):
    errors = []
    required_sections = ["【事实】", "【推理】", "【建议】"]

    for section in required_sections:
        matching_lines = [
            line.strip()
            for line in output.splitlines()
            if line.strip().startswith(section)
        ]

        if not matching_lines:
            errors.append(f"缺少 {section} 这一行")
            continue

        line = matching_lines[0]
        cited_ids = set(re.findall(r"\[(E-\d+)\]", line))

        if not cited_ids:
            errors.append(f"{section} 没有引用 evidence_id")
            continue

        unknown_ids = cited_ids - valid_evidence_ids
        if unknown_ids:
            errors.append(
                f"{section} 引用了不存在的 evidence_id: {', '.join(sorted(unknown_ids))}"
            )

    return errors


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/debug/reason")
def reason(request: ReasonRequest):
    mock_data = request.dict()
    prompt = build_prompt(mock_data)
    output = call_deepseek(prompt)
    valid_evidence_ids = collect_evidence_ids(mock_data)
    errors = verify_output(output, valid_evidence_ids)

    return {
        "output": output,
        "verified": len(errors) == 0,
        "errors": errors,
        "valid_evidence_ids": sorted(valid_evidence_ids),
    }
