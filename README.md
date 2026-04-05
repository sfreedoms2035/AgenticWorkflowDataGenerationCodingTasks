# 🚀 AgenticWorkflowDataGeneration — 4QDR.AI

**Hardened, Autonomous Pipeline for High-Complexity AD/ADAS Synthetic Coding Tasks**

[![Pipeline Status](https://img.shields.io/badge/Pipeline-Verified-success.svg?style=flat-square)](https://4qdr.ai)
[![QA Gates](https://img.shields.io/badge/QA_Gates-10+-blueviolet.svg?style=flat-square)](https://4qdr.ai)
[![Auto-Repair](https://img.shields.io/badge/Auto--Repair-Integrated-03dac6.svg?style=flat-square)](https://4qdr.ai)

---

## 📖 Overview

The **AgenticWorkflowBrowser** is an autonomous engineering pipeline that transforms raw AD/ADAS technical documents (SOTIF, functional safety, ISO standards) into a "Gold Standard" dataset of expert-level coding tasks. It simulates a pair of elite engineers—one generating complex software solutions and another performing rigorous quality assurance—to produce training data with industrial-grade depth.

By leveraging **Gemini 3.1 Pro** via a headless **Playwright** browser and a multi-layered validation logic, the pipeline ensures every task meets a minimum volume of **10,000+ characters** of logic and **300+ lines** of production-ready code.

---

## 🏗️ Agentic Architecture

The pipeline follows a **Predictive-Corrective Architecture** to maximize throughput while minimizing human intervention.

```mermaid
graph TD
    A[Input PDF] --> B{Orchestrator}
    B -->|Variation Schema| C[CodingTaskGenerator]
    C -->|Synthesize| D[Playwright / Gemini]
    D -->|Raw JSON| E{DataQualityChecker}
    E -->|PASS| F[Output/json]
    E -->|FAIL: Locally Fixable| G[AutoRepairEngine]
    G -->|Fix| E
    E -->|FAIL: Needs Regen| H[Repair Prompt Builder]
    H -->|Retry [Max 3]| D
    F --> I[Statistical Dashboard]
```

---

## 🧠 Core Concepts & Roles

### 1. PRINCIPAL SYNTHETIC DATA ENGINEER (`CodingTaskGenerator`)
Responsible for high-fidelity immersion. It doesn't "generate tasks"—it **solves engineering crises** within the software stack of a simulated ADAS platform. Every task must include an 8-step internal monologue (Chain of Thought) detailing mathematical derivations and trade-off matrices.

### 2. STRICT QUALITY ASSURANCE (`DataQualityChecker`)
A gatekeeper that uses `validate_task.py` to enforce 10+ rigid thresholds:
- **CoT Volume**: ≥ 9,000 chars of dense reasoning.
- **Answer Volume**: ≥ 10,000 chars of structured content.
- **Code Volume**: ≥ 300 lines of functional C++, Rust, or Python.
- **Structural Integrity**: 8 parent headers and 31 sub-elements mandatory.

### 3. AUTONOMOUS REPAIR (`RepairEngine`)
`auto_repair.py` acts as a local expert to resolve non-destructive failures:
- **Semantic Vocab Fix**: Replaces banned "meta" phrases with in-universe language.
- **Metadata Synthesis**: Formulates missing documentation or requirements automatically.
- **Syntax Correction**: Cleans up redundant LLM tags (e.g., duplicate `<think>` tags).

---

## 📊 Analytics & Dashboards

The pipeline prioritizes **cost and performance transparency**.

- **Console Stats**: Real-time feedback on CoT size, Answer size, Code lines, and Duration.
- **`statistics.json`**: Long-term tracking of timing distributions (min/max/mean/stddev) and repair success rates.
- **Glassmorphism Dashboard**: An auto-opening HTML visualization featuring rich charts and a per-task detail table.

---

## 📥 Installation

### Prerequisites
- **Python 3.10+** (Recommend Anaconda/Miniconda)
- **Node.js 18+**
- **Playwright** for browser automation
- **PowerShell** (for Windows implementation)

### Setup Steps
1. **Clone the repository**:
   ```powershell
   git clone https://your-repo/AgenticWorkflowDataGeneration.git
   cd AgenticWorkflowDataGeneration
   ```
2. **Install Python dependencies**:
   ```powershell
   pip install playwright jsonpath-ng
   ```
3. **Install Playwright Browsers**:
   ```powershell
   playwright install chromium
   ```
4. **Environment Variables** (Optional):
   Set `MODEL_NAME` to override the default metadata label.

---

## 🚀 Usage Tutorial

### 1. Basic Generation
Place your source PDFs in the `Input/` directory and run:
```powershell
python pipeline.py
```
*The pipeline will automatically detect the PDF type (Technical vs Regulatory), assign variation strategies, and start the 8-turn (16-task) loop.*

### 2. Resuming Execution
If the pipeline is interrupted, it can pick up exactly where it left off:
```powershell
python pipeline.py --resume
```

### 3. Validating Existing Data
To re-run the quality gates and update the dashboard without generating new data:
```powershell
python pipeline.py --validate-only
```

### 4. Advanced Controls
```powershell
# Limit to specific PDF and turn
python pipeline.py --pdf "ISO_26262.pdf" --turn 3 --task 1

# Limit task count for high-speed testing
python pipeline.py --limit-tasks 2
```

---

## 📂 Project Structure

```text
.
├── Input/                  # Source PDFs (Technical/Regulatory)
├── Output/
│   ├── json/               # Final task JSONs
│   ├── thinking/           # Plaintext CoT traces
│   ├── progress.json       # Pipeline state & stats
│   └── dashboard.html      # Visual metrics
├── .agent/
│   ├── scripts/            # Validator & Repair Engine
│   ├── skills/             # System Roles & Constraints
│   └── workflows/          # Execution logic
└── pipeline.py             # Orchestrator Entry Point
```

---

## ⚖️ License & Ownership
**Copyright by 4QDR.AI · AD Knowledge Bot v1.0**
Internal Use Only. All data generated by this pipeline is the intellectual property of **4QDR.AI**.
