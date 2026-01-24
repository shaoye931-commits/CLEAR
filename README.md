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

## 2. Approach
MA-SDR employs a multi-stage iterative process to ensure quality in Assignment Code Generation:
![MA-SDR Framework](docs/figs/masdr_framework.png)

