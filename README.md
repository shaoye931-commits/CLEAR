MA-SDR is a test-driven iterative framework designed to evaluate the performance of Large Language Models (LLMs) in Assignment Code Generation tasks. This project is specifically optimized for Aggregated Function Call Dependency Scenarios.

✨ Project Introduction
This project implements a closed-loop automated Assignment Code Generation and repair system. Its key features include:

🧩 Aggregated Function Call Dependency Support
Supports the collaborative generation of Auxiliary Functions and Main Functions, ensuring logical decoupling and correct call dependencies between functions.
🔍 AST Compliance Check
Performs static Abstract Syntax Tree (AST) analysis before code execution to enforce structural norms, ensuring the Main Function correctly calls the Auxiliary Function.
🔄 Iterative Refinement
Supports multi-round self-correction, combining error diagnosis reports with targeted code refactoring.
🛡️ Sandbox Execution
Uses Docker containers to execute generated code and test cases safely, preventing host system contamination.
💡 Guided Diagnostics
Intelligently analyzes Runtime Errors and Assertion Failures to provide precise repair suggestions.


🛠️ Workflow
MA-SDR employs a multi-stage iterative process to ensure quality in Assignment Code Generation:
code
Mermaid
graph TD
    A[Start] --> B[Initial Assignment Code Generation<br>(Chain-of-Thought)]
    B --> C{AST Compliance Check}
    C -- Fail --> D[Generate Compliance Error Report]
    C -- Pass --> E[Docker Sandbox Execution]
    E --> F{Tests Passed?}
    F -- Yes --> G[✅ Task Success]
    F -- No --> H[Error Diagnosis Analysis]
    D --> I{Max Iterations Reached?}
    H --> I
    I -- No --> J[Iterative Refinement<br>(Guided Diagnostics / Reset Mode)]
    J --> C
    I -- Yes --> K[❌ Task Failed]

📂 Project Structure
code
Text
MA-SDR_Experiment/
├── data/                    # 📊 Dataset directory
│   ├── humaneval_pro.json   # HumanEval-Pro Dataset
│   └── mbpp_pro.json        # MBPP-Pro Dataset
├── src/                     # 🧠 Source code directory
│   ├── agents/              # Diagnosis agents
│   │   └── diagnosis_agent.py
│   ├── main.py              # Main entry point
│   ├── main_ablation.py     # Ablation study script
│   ├── config.py            # Configuration management
│   ├── llm_handler.py       # LLM handler
│   ├── deepseek_client.py   # DeepSeek API client
│   ├── prompt_factory.py    # Prompt factory
│   ├── dual_task_compliance.py  # Dependency compliance check
│   ├── dual_task_diagnostics.py # Dependency diagnostics
│   ├── sandbox_executor.py  # Docker sandbox executor
│   └── mbpp_utils.py        # MBPP dataset utilities
├── docker/                  # 🐳 Docker configuration
│   └── Dockerfile           # Sandbox image definition
├── docs/                    # 📝 Documentation
│   ├── method_framework.mmd
│   └── method_framework.tex
├── results/                 # 📈 Results output directory
└── .gitignore               # Git ignore configuration

⚙️ Environment Setup
1. System Requirements
Python: 3.12+
Docker & Docker Compose: Required for sandbox execution.
Git: For version control.
1. Installation
code
Bash
# 1. Clone the repository
git clone https://github.com/yourusername/MA-SDR_Experiment.git
cd MA-SDR_Experiment

# 2. Create and activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
3. Configuration
Create a .env file in the project root directory and configure the following environment variables:
code
Ini
# --- LLM API Configuration ---
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com

# (Optional) OpenRouter Configuration
USE_OPENROUTER=false
OPENROUTER_API_KEY=sk-or-xxxxxxxx
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# --- Experiment Defaults ---
MODEL_TO_TEST=deepseek-coder
4. Build Sandbox Image
Before running experiments, you must build the Docker image used for code execution:
code
Bash
docker build -t masdr-sandbox:latest -f docker/Dockerfile .
💻 Usage
Basic Execution
Run the main program to process the MBPP dataset:
code
Bash
python -m src.main --data data/mbpp_pro.json --limit 5 --max_iters 3
Arguments
Argument	Description	Default
--data	Path to the dataset file (JSON)	Required
--limit	Limit the number of tasks (for debugging)	None (Process all)
--max_iters	Maximum number of refinement iterations	3
--results_dir	Directory to save results	results/
--image	Docker image name	masdr-sandbox:latest
📄 Output Results
Experiment results are saved in the results/ directory in .jsonl format. The filename includes a timestamp (e.g., ma-sdr_run_20240101_120000.jsonl).
Result Fields:
task_id: Unique Task ID.
problem: Problem description.
final_status: Final status (success | fail | pass_by_review).
iterations: Detailed logs for each iteration.
iteration: Iteration number.
prompt: The prompt used.
code: Generated code.
success: Boolean indicating success.
exit_code: Execution exit code.
stdout / stderr: Standard output and error.
failed_assert: The specific assertion that failed (if any).
actual_output / expected_output: Comparison of outputs.


⚠️ Notes
[!IMPORTANT]
API Key Security: Ensure .env is added to your .gitignore file. Never commit your API keys to a public repository.
[!TIP]
Docker Permissions: On Linux, ensure your user is added to the docker group (sudo usermod -aG docker $USER) to run Docker commands without sudo.
[!WARNING]
Resource Usage: Large-scale experiments may consume a significant amount of API tokens and time. Please monitor your usage quotas.

📧 Contact
For questions or suggestions, please contact:
Maintainer: [Your Name]
Email: [your.email@example.com]