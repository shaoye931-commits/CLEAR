<div align="center">

# CLEAR Experiment
### Multi-Agent Structured Diagnosis and Refinement

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Docker Enabled](https://img.shields.io/badge/Docker-Enabled-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-4c1)](LICENSE)

</div>

---

**CLEAR** Structured Iterative Reasoning via Multi-Agent Collaboration for Assignment Code Generation. This project is specifically optimized for **Aggregated Function Call Dependency Scenarios**.

## 1. Project Introduction

This project implements **CLEAR (Call-Level Evidence-guided Attribution and Refinement)**, a multi-agent framework for self-invoking code generation. CLEAR integrates dependency-guided code generation, call-level execution evidence, fault attribution, and constrained iterative refinement to improve the correctness of generated programs with explicit function dependencies.

Its key features include:

* **🧩 Dependency-Guided Code Generation**

  Guides the generation of main and auxiliary functions according to task specifications and required calling relationships.

* **🔍 AST-Based Structural Validation**

  Performs static Abstract Syntax Tree (AST) analysis to verify program syntax, required function definitions, and explicit calling relationships.

* **📊 Call-Level Evidence Collection**

  Uses dynamic instrumentation to collect auxiliary function arguments, return values, exceptions, and call sequences during test execution.

* **💡 Evidence-Guided Fault Attribution**

  Employs a diagnosis agent to analyze execution evidence and function specifications, distinguishing potential faults in auxiliary functions, function calls, and main functions.

* **🔄 Constrained Refinement**

  Translates fault attribution results into explicit modification constraints, guiding the generation agent to refine relevant code regions while preserving required function dependencies.

* **🔒 History and Freezing**

  Maintains historical execution and diagnosis information to reduce repeated failures and unintended modifications while preserving function implementations supported by available evidence.

* **🔁 Context Reset**

  Initiates a new code generation attempt using summarized historical feedback when preceding refinement iterations remain unsuccessful.

* **🛡️ Sandbox Execution**

  Executes generated programs and test cases within isolated Docker containers to support controlled and secure program evaluation.

## 2. Approach
CLEAR employs a multi-stage iterative process to ensure quality in Assignment Code Generation:
![CLEAR Framework](fame.png)

## 3. Project Structure
CLEAR_Experiment/
|-- data/                    # Dataset directory (HumanEval-Pro, MBPP-Pro)
|-- src/                     # Source code directory
|   |-- agents/              # Diagnosis agents
|   |-- deepseek_client.py   # DeepSeek API client
|   |-- dual_task_*.py       # Dependency compliance & diagnostics
|   |-- sandbox_executor.py  # Docker sandbox executor
|   `-- main.py              # Main entry point
|-- docker/                  # Docker configuration
|-- results/                 # Results output directory
`-- requirements.txt         # Python dependencies

## 4. Environment Setup
# 4.1 System Requirements
    Python: 3.12+
    Docker: Required for sandbox execution.
    Git: For version control.
# 4.2 Installation
    # 1. Clone the repository
    git clone https://github.com/yourusername/MA-SDR_Experiment.git
    cd MA-SDR_Experiment
    
    # 2. Create and activate virtual environment
    python -m venv venv
    source venv/bin/activate    # Linux/macOS
    # venv\Scripts\activate     # Windows
    
    # 3. Install dependencies
    pip install -r requirements.txt
# 4.3 Configuration
Create a .env file in the project root:
    DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
    DEEPSEEK_BASE_URL=https://api.deepseek.com
    MODEL_TO_TEST=deepseek-coder
## 5. Notes
    [!IMPORTANT]
    API Key Security: Ensure .env is added to your .gitignore file. Never commit your API keys to a public repository.
    [!TIP]
    Docker Permissions: On Linux, ensure your user is added to the docker group to run commands without sudo.
    [!WARNING]
    Resource Usage: Large-scale experiments may consume a significant amount of API tokens. Monitor your usage quotas.
## 6. Contact
    Maintainer: [Shao ye]
    Email: shaoye931@gmail.com



