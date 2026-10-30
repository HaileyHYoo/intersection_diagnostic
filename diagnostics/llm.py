"""LLM access for the two templates, and the check that keeps its answers inside the evidence.

The LLM only words the evidence. Its answer is accepted when it is the requested JSON, every number in it
appears in the evidence (at the precision the evidence offers), and it uses none of the forbidden claims
(fault, cause, automatic timing change). Otherwise the template's code-written answer is used and the
rejection is recorded. Without an LLM (no key, or --no-llm) the code-written answer is the answer.

    OpenAIChat   local runs: OPENAI_API_KEY / OPENAI_MODEL from .env
    HostLLM      production: the host chatbot's own client (bot.llm), same model as its template matching
"""
from __future__ import annotations

import json
import re

NUMBER = re.compile(r"(?<![A-Za-z])-?\d+(?:\.\d+)?")
FORBIDDEN = re.compile(r"\b(caused by|is causing|are causing|due to the signal\w*|fault(y|s)?|malfunction\w*|"
                       r"failed|failure|broken|optimi[sz]\w*|retim\w*|"
                       r"should (increase|decrease|change|reduce|extend|shorten))\b", re.I)


class LLMUnavailable(RuntimeError):
    pass


class OpenAIChat:
    """Chat completions with temperature 0 and a seed, stepping down if the model rejects them."""
    _plain = False

    def __init__(self, api_key: str, model: str):
        if not api_key or not model:
            raise LLMUnavailable("OPENAI_API_KEY and OPENAI_MODEL are required for the LLM wording.")
        from openai import OpenAI
        self._client, self.model = OpenAI(api_key=api_key), model

    def complete(self, system: str, user: str) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if not OpenAIChat._plain:
            try:
                r = self._client.chat.completions.create(model=self.model, messages=messages, temperature=0, seed=1234,
                                                         response_format={"type": "json_object"})
                return r.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001 - only an argument complaint steps down
                if not any(w in str(exc).lower() for w in ("temperature", "seed", "response_format", "unsupported",
                                                           "not supported", "invalid_request_error")):
                    raise
                OpenAIChat._plain = True
        r = self._client.chat.completions.create(model=self.model, messages=messages)
        return r.choices[0].message.content or ""


class HostLLM:
    """The intersection chatbot's LLMClient (bot.llm), called through its _chat(system, user, temperature)."""

    def __init__(self, client):
        self._client = client
        self.model = getattr(client, "_model", "host")

    def complete(self, system: str, user: str) -> str:
        return self._client._chat(system, user, 0.0)


def parse_json(raw: str) -> dict | None:
    text = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip()
    try:
        value = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def allowed_numbers(*objects) -> set[str]:
    """Every number of the evidence, as written there and rounded to 0, 1 and 2 decimals, signed and unsigned."""
    out = set()

    def add(x: float):
        for v in (x, abs(x)):
            out.update({f"{v:.0f}", f"{v:.1f}", f"{v:.2f}", f"{v:g}"})
            if float(v).is_integer():
                out.add(str(int(v)))

    def walk(o):
        if isinstance(o, bool) or o is None:
            return
        if isinstance(o, (int, float)):
            add(float(o))
        elif isinstance(o, str):
            for token in NUMBER.findall(o):
                add(float(token))
        elif isinstance(o, dict):
            for k, v in o.items():
                walk(k)
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)

    for o in objects:
        walk(o)
    return out


def check(answer: dict | None, keys: list[str], allowed: set[str]) -> list[str]:
    """Problems with an LLM answer; empty when it can be used."""
    if answer is None:
        return ["the answer is not JSON"]
    problems = [f"missing '{k}'" for k in keys if k not in answer]
    text = json.dumps({k: answer.get(k) for k in keys}, ensure_ascii=False)
    invented = sorted({n for n in NUMBER.findall(text) if n not in allowed and n.lstrip("-") not in allowed})
    if invented:
        problems.append("numbers not in the evidence: " + ", ".join(invented[:8]))
    claims = sorted({m.group(0).lower() for m in FORBIDDEN.finditer(text)})
    if claims:
        problems.append("forbidden wording: " + ", ".join(claims))
    return problems


def word(llm, system: str, user: str, keys: list[str], evidence: dict, fallback: dict) -> dict:
    """{'answer', 'generated_by', 'rejected'}: the LLM's answer when it passes the check, else the fallback."""
    if llm is None:
        return {"answer": fallback, "generated_by": "code", "rejected": None}
    try:
        raw = llm.complete(system, user)
    except Exception as exc:  # noqa: BLE001 - the report is still produced from code
        return {"answer": fallback, "generated_by": "code", "rejected": f"LLM call failed ({type(exc).__name__})"}
    answer = parse_json(raw)
    problems = check(answer, keys, allowed_numbers(evidence, fallback))
    if problems:
        return {"answer": fallback, "generated_by": "code", "rejected": "; ".join(problems)}
    return {"answer": {k: answer[k] for k in keys}, "generated_by": f"llm:{getattr(llm, 'model', '')}", "rejected": None}
