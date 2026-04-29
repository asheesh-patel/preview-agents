import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

def parse_diff(diff_text: str) -> Dict[str, List[str]]:
    """
    Parse unified diff and return added/removed/context lines.
    Focus is on code lines, not diff metadata.
    """
    added: List[str] = []
    removed: List[str] = []
    context: List[str] = []

    for raw_line in diff_text.splitlines():
        if raw_line.startswith(("diff --git", "index ", "@@")):
            continue
        if raw_line.startswith(("+++", "---")):
            continue

        if raw_line.startswith("+"):
            added.append(raw_line[1:])
        elif raw_line.startswith("-"):
            removed.append(raw_line[1:])
        elif raw_line.startswith(" "):
            context.append(raw_line[1:])
        else:
            # Keep unknown lines as context for resiliency.
            context.append(raw_line)

    return {"added": added, "removed": removed, "context": context}


class LLMClient:
    """
    OpenAI-first JSON generator with deterministic mock fallback.
    """

    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0.2):
        self.model = model
        self.temperature = temperature
        self._client = None
        self._openai_available = False
        self._setup_openai()

    def _setup_openai(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return

        try:
            from openai import OpenAI  # type: ignore

            self._client = OpenAI(api_key=api_key)
            self._openai_available = True
        except Exception:
            self._client = None
            self._openai_available = False

    def generate_json(
        self,
        system_prompt: str,
        user_payload: Dict[str, Any],
        fallback: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Return JSON from OpenAI if available, otherwise return fallback.
        """
        if not self._openai_available or self._client is None:
            print("OpenAI not available. Mock the response.")
            return fallback

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload)},
                ],
            )
            content = response.choices[0].message.content or "{}"
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
            return fallback
        except Exception:
            return fallback


@dataclass
class AgentContext:
    diff_raw: str
    diff_parsed: Dict[str, List[str]]
    previous_outputs: Dict[str, Dict[str, Any]]


class BaseAgent:
    name = "BaseAgent"
    system_prompt = "You are a precise code analysis assistant."

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(self, ctx: AgentContext) -> Dict[str, Any]:
        raise NotImplementedError


class PRAnalyzer(BaseAgent):
    name = "PRAnalyzer"

    system_prompt = f"""
        You are CodeUnderstandingAgent.

        TASK:
        - Summarize the PR changes
        - Identify change type: feature / bugfix / refactor
        - Explain behavioral impact

        Return strict JSON:
        {{
        "summary": "",
        "change_type": "",
        "impacted_logic": "what behavior changed"
        }}
        """

    def run(self, ctx: AgentContext) -> Dict[str, Any]:
        added = ctx.diff_parsed["added"]
        removed = ctx.diff_parsed["removed"]
        change_type = "refactor"
        if any("fix" in line.lower() or "bug" in line.lower() for line in added):
            change_type = "bugfix"
        elif any(("def " in line or "class " in line or "return " in line) for line in added):
            change_type = "feature"

        fallback = {
            "summary": f"PR introduces {len(added)} added and {len(removed)} removed lines.",
            "change_type": change_type,
            "behavioral_impact": "Behavior likely changes in areas touched by added logic.",
            "added_focus_notes": "Assessment prioritized newly added lines over unchanged context.",
        }
        payload = {"diff": ctx.diff_parsed, "instruction": "Focus primarily on added lines."}

        return self.llm.generate_json(self.system_prompt, payload, fallback)


class QualityReviewer(BaseAgent):
    name = "QualityReviewer"

    system_prompt = f"""
    You are QualityReviewer. You are expert in code quality review.

    TASK:
    - Review code quality only for added/modified lines in the diff.
    - Check readability, logic issues, maintainability
    - Ignore unrelated pre-existing code.

    Return JSON:
    {{
    "issues": [
        {{
        "issues": [],
        "recommendations": [],
        "added_line_assessment": ""
        }}
    ]
    }}
    """

    def run(self, ctx: AgentContext) -> Dict[str, Any]:
        added = ctx.diff_parsed["added"]
        issues: List[str] = []
        recommendations: List[str] = []

        for line in added:
            stripped = line.strip()
            if "TODO" in stripped:
                issues.append("Added code contains TODO markers that reduce maintainability.")
            if len(stripped) > 120:
                issues.append("Added line exceeds typical readability limits.")
            if stripped.startswith("print("):
                issues.append("Debug print found in added code.")
            if "except Exception" in stripped:
                issues.append("Broad exception handling in new code may hide logic issues.")

        if not issues:
            recommendations.append("No major quality concerns found in added lines.")
        else:
            recommendations.append("Refine new logic for clarity and narrower error handling.")

        fallback = {
            "issues": issues,
            "recommendations": recommendations,
            "added_line_assessment": "Quality review focused on added lines.",
        }
        payload = {
            "diff": ctx.diff_parsed,
            "analysis": ctx.previous_outputs.get("PRAnalyzer", {}),
            "instruction": "Focus primarily on added lines.",
        }
        return self.llm.generate_json(self.system_prompt, payload, fallback)


class SecurityAgent(BaseAgent):
    name = "SecurityAgent"

    system_prompt = f"""
    You are SecurityAgent. You are expert in finding security vulnerabilities in code.

    TASK:
    - Identify security risks introduced or worsened by added lines.
    - Ignore pre-existing issues

    Return JSON:
    {{
    "security_risks": [
        {{
        "risks": [],
        "severity": "low|medium|high",
        "added_line_security_notes": ""
        }}
    ]
    }}
    """

    def run(self, ctx: AgentContext) -> Dict[str, Any]:
        added = ctx.diff_parsed["added"]
        risks: List[str] = []
        sev = "low"

        for line in added:
            low_line = line.lower()
            if "eval(" in low_line or "exec(" in low_line:
                risks.append("Dynamic code execution introduced in added code.")
                sev = "high"
            if "password" in low_line and ("=" in low_line or "print(" in low_line):
                risks.append("Potential credential exposure in added lines.")
                sev = "high"
            if "subprocess" in low_line and "shell=true" in low_line:
                risks.append("Command injection risk via shell=True in new code.")
                sev = "high"
            if "jwt" in low_line and "verify" in low_line and "false" in low_line:
                risks.append("Token verification appears disabled in added logic.")
                sev = "high"

        fallback = {
            "risks": risks,
            "severity": sev,
            "added_line_security_notes": "Security review prioritized newly introduced lines.",
        }
        payload = {
            "diff": ctx.diff_parsed,
            "quality_review": ctx.previous_outputs.get("QualityReviewer", {}),
            "instruction": "Focus primarily on added lines.",
        }
        return self.llm.generate_json(self.system_prompt, payload, fallback)


class TestAgent(BaseAgent):
    name = "TestAgent"
    system_prompt = f"""
        You are TestAgent. You are an expert in reviewing test cases.

        TASK:
        - Suggest missing test cases for newly added or changed logic
        - Focus on edge cases and regressions

        Return strict JSON:
        {{
        "test_cases": [
            {{
            "scenario": "",
            "expected_behavior": ""
            }}
        ]
        }}
        """

    def run(self, ctx: AgentContext) -> Dict[str, Any]:
        added = ctx.diff_parsed["added"]
        recommended: List[str] = []
        regressions: List[str] = []

        if any("if " in line for line in added):
            recommended.append("Add branch coverage tests for each new conditional path.")
        if any("except " in line for line in added):
            recommended.append("Add tests validating expected behavior under raised exceptions.")
        if any("return " in line for line in added):
            recommended.append("Add assertions for new return values and boundary inputs.")
        if any("for " in line or "while " in line for line in added):
            recommended.append("Add tests for loop boundaries (empty/single/large collections).")

        if not recommended:
            recommended.append("Add at least one regression test covering the new added logic path.")
        regressions.append("Changed behavior in added lines may break caller assumptions.")

        fallback = {
            "recommended_tests": recommended,
            "regression_risks": regressions,
            "added_line_test_focus": "Test suggestions are driven by newly added lines.",
        }
        payload = {
            "diff": ctx.diff_parsed,
            "analysis": ctx.previous_outputs.get("PRAnalyzer", {}),
            "security": ctx.previous_outputs.get("SecurityAgent", {}),
            "instruction": "Focus primarily on added lines.",
        }
        return self.llm.generate_json(self.system_prompt, payload, fallback)


class Aggregator(BaseAgent):
    name = "Aggregator"
    system_prompt = """
        You are Aggregator. You will combine outputs from multiple agents into final PR review.
        Return strict JSON :
        {{
        "summary": "",
        "key_findings": [],
        "issues": [],
        "security_risks": [],
        "test_recommendations": [],
        "final_verdict": "approve | request_changes",
        "confidence": "low | medium | high"
        }}
    """
    
    def run(self, ctx: AgentContext) -> Dict[str, Any]:
        analyzer = ctx.previous_outputs.get("PRAnalyzer", {})
        quality = ctx.previous_outputs.get("QualityReviewer", {})
        security = ctx.previous_outputs.get("SecurityAgent", {})
        tests = ctx.previous_outputs.get("TestAgent", {})

        issues = quality.get("issues", [])
        security_risks = security.get("risks", [])
        test_recs = tests.get("recommended_tests", [])

        verdict = "approve"
        confidence = "high"

        if security.get("severity") == "high" or issues:
            verdict = "request_changes"
            confidence = "medium"
        if security_risks and security.get("severity") == "high":
            confidence = "high"

        key_findings = [
            f"Change type: {analyzer.get('change_type', 'unknown')}",
            f"Quality issues found: {len(issues)}",
            f"Security risks found: {len(security_risks)}",
            f"Test recommendations: {len(test_recs)}",
        ]

        fallback = {
            "summary": analyzer.get("summary", "PR reviewed with multi-agent pipeline."),
            "key_findings": key_findings,
            "issues": issues,
            "security_risks": security_risks,
            "test_recommendations": test_recs,
            "final_verdict": verdict,
            "confidence": confidence,
        }
        payload = {
            "agent_outputs": ctx.previous_outputs,
            "diff": ctx.diff_parsed,
            "instruction": "Focus primarily on added lines when synthesizing.",
        }
        return self.llm.generate_json(self.system_prompt, payload, fallback)


def run_pipeline(diff_text: str) -> Dict[str, Any]:
    """
    Orchestrates multi-agent PR review in sequence.
    """
    llm = LLMClient(model="gpt-4o-mini", temperature=0.2)
    parsed_diff = parse_diff(diff_text)
    outputs: Dict[str, Dict[str, Any]] = {}
    ctx = AgentContext(diff_raw=diff_text, diff_parsed=parsed_diff, previous_outputs=outputs)

    agents = [
        PRAnalyzer(llm),
        #QualityReviewer(llm),
        #SecurityAgent(llm),
        #TestAgent(llm),
        Aggregator(llm),
    ]

    for agent in agents:
        outputs[agent.name] = agent.run(ctx)

    return {
        "parsed_diff": parsed_diff,
        "agent_outputs": outputs,
        "final_review": outputs["Aggregator"],
    }


if __name__ == "__main__":
    sample_diff = """diff --git a/app/service.py b/app/service.py
index 1122334..5566778 100644
--- a/app/service.py
+++ b/app/service.py
@@ -1,7 +1,16 @@
 def calculate_total(price, tax):
-    return price + tax
+    if price < 0:
+        raise ValueError("price must be non-negative")
+    total = price + tax
+    print("debug total", total)
+    return total

 def handler(user_input):
-    return "ok"
+    result = eval(user_input)
+    return result
"""

    result = run_pipeline(sample_diff)
    print(json.dumps(result, indent=2))
