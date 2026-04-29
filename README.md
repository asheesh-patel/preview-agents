# PReview Agents — A multi-agent system for intelligent pull request review

## Problem Chosen

The project addresses automated pull request review for **diffs** (not full codebases) using a **true multi-agent architecture**.  
The goal is to produce a structured, actionable review that covers:

- change intent and behavior impact
- code quality concerns
- security risks introduced by the change
- missing test scenarios
- a final merge recommendation

This setup is designed to demonstrate agent separation and orchestration rather than a single all-in-one prompt.

## Agent Design and Workflow

The system is implemented in `pr_review_multi_agent.py` and includes five distinct agents:

1. **PRAnalyzer**
  - Summarizes the PR change
  - Classifies change type (`feature | bugfix | refactor`)
  - Explains expected behavioral impact
2. **QualityReviewer**
  - Reviews only newly introduced logic in the diff
  - Flags readability, maintainability, and logic-quality issues
3. **SecurityAgent**
  - Evaluates security risk introduced by new lines
  - Ignores pre-existing issues unless worsened
4. **TestAgent**
  - Proposes missing tests for changed/new logic
  - Focuses on edge cases and regressions
5. **Aggregator**
  - Combines prior outputs into one final structured review JSON
  - Produces verdict: `approve` or `request_changes`
  - Produces confidence: `low | medium | high`

### Pipeline Orchestration

`run_pipeline(diff)` performs these steps:

1. Parse unified diff into:
  - `added`
  - `removed`
  - `context`
2. Run agents sequentially:
  - `PRAnalyzer` -> `QualityReviewer` -> `SecurityAgent` -> `TestAgent` -> `Aggregator`
3. Pass previous outputs forward as additional context
4. Return:
  - parsed diff sections
  - per-agent outputs
  - final aggregated review

All agents are instructed to prioritize reasoning on **added lines**.

## Assumptions and Trade-offs

### Assumptions

- Input diff is a standard unified git diff.
- Review objective is to assess **newly introduced risk** first.
- Structured JSON output is preferred over free-form prose.
- OpenAI API usage is optional (falls back to deterministic local mock behavior).

### Trade-offs

- **Simplicity over framework complexity:** no LangChain/CrewAI; easy to read, easier to extend manually.
- **Sequential orchestration over parallelism:** simpler data flow and reproducibility, but potentially slower at scale.
- **Heuristic fallback logic:** predictable and testable, but less nuanced than model reasoning.
- **Diff-only context:** reduces token cost and noise, but limits architectural understanding outside touched lines.

## What I Would Improve With More Time

- Introduce strict JSON schema validation for every agent output.
- Add optional parallel execution for independent agents with deterministic merge.
- Add regression tests and benchmark fixtures across real PR datasets (Golden Datasets).
- Add configurable policy profiles (e.g., strict security mode, startup speed mode).
- Modularize the code and project structure
- Use Agentic AI framework (my preference is OpenAI ADK or CrewAI)
- Use tools and MCP servers to use linters, security tools etc
- Use model agnostic code for LLM call by using LiteLLM or LangChain
- Use smaller model for simpler task like Aggregrater and bigger model for other complex tasks 

## How AI Tools Were Used

AI assistance was used to accelerate design, iteration, and code generation while preserving explicit architecture choices.

### Approach

- Started from a requirements-first breakdown:
  - required agents
  - required responsibilities
  - required output schemas
  - orchestration order and data handoff
- Used ChatGPT to generate and refine prompt
- Used Cursor AI to build and iterate python code
- Refactored agent prompts and some code manually
- Created UV project, Intalled dependencies, 
- Added OpenAI API key in .env file and tested the workflow
- Used Cursor AI to generate initial template of README.md file and then updated it

### Example Prompt Style

- `initial_prompt.txt`

### Workflow With AI Assistant

1. Define constraints and acceptance criteria.
2. Generate inital prompt to implement the code.
3. Generate an initial implementation.
4. Validate run output using sample diff.
5. Refine prompts and output contracts.
6. Keep code readable, framework-free, and easy to demo.

