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
    A([Start]) --> B["Initial Assignment Code Gen<br>(Chain-of-Thought)"]
    B --> C{"AST Compliance?"}
    
    C -- Fail --> D[Generate Error Report]
    C -- Pass --> E[Docker Sandbox Execution]
    
    E --> F{"Tests Passed?"}
    F -- Yes --> G([✅ Task Success])
    
    F -- No --> H[Error Diagnosis Analysis]
    
    D --> I{"Max Iters?"}
    H --> I
    
    I -- No --> J["Iterative Refinement"]
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
