<div align="center">

# MA-SDR Experiment
### Model-Agnostic Self-Diagnostic Refinement

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Docker Enabled](https://img.shields.io/badge/Docker-Enabled-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-4c1)](LICENSE)

</div>

---

**MA-SDR** is a test-driven iterative framework designed to evaluate the performance of Large Language Models (LLMs) in **Assignment Code Generation** tasks. This project is specifically optimized for **Aggregated Function Call Dependency Scenarios**.

## 1. Project Introduction

This project implements a closed-loop automated **Assignment Code Generation** and repair system. Its key features include:

*   **🧩 Aggregated Function Call Dependency Support**
    Supports the collaborative generation of **Auxiliary Functions** and **Main Functions**, ensuring logical decoupling and correct call dependencies between functions.

*   **🔍 AST Compliance Check**
    Performs static Abstract Syntax Tree (AST) analysis before code execution to enforce structural norms, ensuring the Main Function correctly calls the Auxiliary Function.

*   **🔄 Iterative Refinement**
    Supports multi-round self-correction, combining error diagnosis reports with targeted code refactoring.

*   **🛡️ Sandbox Execution**
    Uses Docker containers to execute generated code and test cases safely, preventing host system contamination.

*   **💡 Guided Diagnostics**
    Intelligently analyzes Runtime Errors and Assertion Failures to provide precise repair suggestions.

## 2. Workflow

MA-SDR employs a multi-stage iterative process to ensure quality in Assignment Code Generation:

```mermaid
graph TD
    A([Start]) --> B[Initial Assignment Code Gen<br>(Chain-of-Thought)]
    B --> C{AST Compliance?}
    
    C -- Fail --> D[Generate Error Report]
    C -- Pass --> E[Docker Sandbox Execution]
    
    E --> F{Tests Passed?}
    F -- Yes --> G([✅ Task Success])
    
    F -- No --> H[Error Diagnosis Analysis]
    
    D --> I{Max Iters?}
    H --> I
    
    I -- No --> J[Iterative Refinement]
    J --> C
    
    I -- Yes --> K([❌ Task Failed])

    style A fill:#90EE90,stroke:#333,stroke-width:2px
    style G fill:#90EE90,stroke:#333,stroke-width:2px
    style K fill:#FFCCCB,stroke:#333,stroke-width:2px
    style C fill:#FFFACD,stroke:#333,stroke-width:2px
    style F fill:#FFFACD,stroke:#333,stroke-width:2px
    style I fill:#FFFACD,stroke:#333,stroke-width:2px
    style B fill:#E6E6FA,stroke:#333,stroke-width:2px
    style E fill:#E6E6FA,stroke:#333,stroke-width:2px
    style J fill:#E6E6FA,stroke:#333,stroke-width:2px
    style D fill:#E6E6FA,stroke:#333,stroke-width:2px
    style H fill:#E6E6FA,stroke:#333,stroke-width:2px
3. Project Structure
code
Text
MA-SDR_Experiment/
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
4. Environment Setup
4.1 System Requirements
Python: 3.12+
Docker: Required for sandbox execution.
Git: For version control.
4.2 Installation
code
Bash
# 1. Clone the repository
git clone https://github.com/yourusername/MA-SDR_Experiment.git
cd MA-SDR_Experiment

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate    # Linux/macOS
# venv\Scripts\activate     # Windows

# 3. Install dependencies
pip install -r requirements.txt
4.3 Configuration
Create a .env file in the project root:
code
Ini
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
MODEL_TO_TEST=deepseek-coder
4.4 Build Sandbox Image
code
Bash
docker build -t masdr-sandbox:latest -f docker/Dockerfile .
5. Usage
5.1 Basic Execution
code
Bash
python -m src.main --data data/mbpp_pro.json --limit 5 --max_iters 3
5.2 Arguments
Argument	Description	Default
--data	Path to the dataset file (JSON)	Required
--limit	Limit the number of tasks (for debugging)	None
--max_iters	Maximum number of refinement iterations	3
--results_dir	Directory to save results	results/
--image	Docker image name	masdr-sandbox
6. Output Results
Results are saved in results/ as .jsonl files. Key fields include:
final_status: success | fail | pass_by_review
iterations: Detailed logs (code, stdout, stderr, failed assertions).
7. Notes
[!IMPORTANT]
API Key Security: Ensure .env is added to your .gitignore file. Never commit your API keys to a public repository.
[!TIP]
Docker Permissions: On Linux, ensure your user is added to the docker group to run commands without sudo.
[!WARNING]
Resource Usage: Large-scale experiments may consume a significant amount of API tokens. Monitor your usage quotas.
8. Contact
Maintainer: [Your Name]
Email: your.email@example.com
