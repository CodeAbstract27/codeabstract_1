# CodeAbstract

> **Privacy-Preserving CLI for Secure LLM Code Consultation**

CodeAbstract is a complete command-line interface (CLI) tool that implements a privacy-preserving framework enabling developers to safely consult Large Language Models (LLMs) on sensitive code without exposing intellectual property. 

The system performs AST-based semantic abstraction to transform proprietary Python code into a privacy-optimized intermediate representation, coupled with context-aware bidirectional mapping for actionable feedback translation.

---

## 🌟 Key Features

* **AST-Based Semantic Abstraction:** Intelligently parses Python code into an Abstract Syntax Tree (AST), replacing sensitive identifiers while preserving logic and structure.
* **Sensitivity Classification:** Automatically classifies nodes into `SECRET` (API keys, passwords, tokens) and `VALUE` (prices, rates, endpoints) using pattern matching.
* **Context-Aware Reconstruction:** Translates the LLM's feedback back to your original source code context, appending multi-line code snippets so you know exactly where to apply changes.
* **Secure Local Storage:** All mappings between original names and abstracted tokens are stored in a local SQLite database, encrypted using AES-128-CBC + HMAC-SHA256 (Fernet).
* **Interactive CLI Wizard:** A beautiful, fully guided terminal UI (built with Rich and Typer) makes the abstraction and translation process seamless.

---

## ⚙️ How It Works (The 4 Formal Algorithms)

CodeAbstract is built on four core algorithms:

1. **`ABSTRACT(S, k)`:** Parses source code into an AST, generates consistent tokens (e.g., `FUNC_0`, `SECRET_1`), extracts a context window of ±k lines, and replaces the nodes in the code.
2. **`CLASSIFY(E)`:** Evaluates each AST node against regex patterns to classify it as a `SECRET`, `VALUE`, or default `IDENTIFIER`.
3. **`RECONSTRUCT(R, M̃, K)`:** Takes an LLM response containing tokens, decrypts your local mapping table, restores the original identifiers, and appends a "Source Context" block for human readability.
4. **`ENCRYPT(M) / DECRYPT(M̃, K)`:** Uses high-grade Fernet symmetric encryption to ensure your mapping tables are stored securely at rest in your local database.

---

## 🚀 Installation

Ensure you have Python 3.9+ installed. It is highly recommended to install CodeAbstract inside a virtual environment.

```powershell
# Clone the repository
git clone https://github.com/yourusername/codeabstract.git
cd codeabstract

# Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\activate   # On Windows
# source .venv/bin/activate # On macOS/Linux

# Install the application
pip install -e ".[dev]"
```

---

## 🔑 API Key Configuration

To use the automated code review feature (`codeabstract review`), you must configure your Google Gemini API key using one of the following methods (ordered by resolution priority):

1. **CLI Argument**: Pass it directly with the `--api-key` option:
   ```powershell
   codeabstract review path/to/file.py --api-key YOUR_API_KEY
   ```
2. **Environment Variable**: Set it in your terminal:
   - **PowerShell**: `$env:GEMINI_API_KEY="YOUR_API_KEY"`
   - **Bash/Zsh**: `export GEMINI_API_KEY="YOUR_API_KEY"`
3. **Environment File (`.env`)**: Create a file named `.env` in the current working directory or repository root containing:
   ```env
   GEMINI_API_KEY=YOUR_API_KEY
   ```
4. **Application Configuration**: Store it in your persistent global configuration file:
   ```powershell
   codeabstract config set gemini_api_key YOUR_API_KEY
   ```

---

## 🏃 How to Run

### 1. Activate Virtual Environment
Ensure your virtual environment is active:
```powershell
# Windows PowerShell
.\.venv\Scripts\activate

# Windows CMD
.\.venv\Scripts\activate.bat

# Linux / macOS
source .venv/bin/activate
```

### 2. Execution Options
You can run commands using `python cli.py <command>` or `codeabstract <command>`.

#### 🧙 Interactive Guided Wizard (Recommended)
The interactive wizard guides you step-by-step through selecting a file, abstracting code, copying to clipboard, and translating responses:
```powershell
python cli.py interactive
# Or: codeabstract interactive
```

#### 🤖 Automated Code Review (Uses `.env` API Key)
Runs end-to-end abstraction, sends the code to Gemini, and translates the response back automatically:
```powershell
python cli.py review demo_payment.py
# Or: codeabstract review demo_payment.py
```

#### 🔒 Manual Workflow: Abstracting Code
Parses a Python file, replaces sensitive identifiers with privacy-optimized tokens, and copies safe code to your clipboard:
```powershell
python cli.py abstract path/to/your_file.py --copy --show-mapping
```

#### 🔄 Manual Workflow: Translating Responses
Translates LLM response tokens back to your original code variable names:
```powershell
# Using direct text response from LLM
python cli.py translate <SESSION_ID> "The bug is in FUNC_0."

# Reading from a saved response text file
python cli.py translate <SESSION_ID> --file response.txt
```

#### 🌐 Web Interface
Serves the workbench on `http://127.0.0.1:5000` — your code and the abstracted code side by side,
the privacy report inline, and the model's suggestions mapped back onto your own names:
```powershell
pip install "flask>=3.0.0"     # or: pip install -e ".[web]"
python cli.py web
# Or: codeabstract web --port 8000
```

The page shows all five outputs the design calls for: the **abstracted code** that is about to be
sent, the **local vault** (your mapping table, which never leaves the machine), the **raw LLM
analysis** still in tokens, the **mapped feedback** with your names restored, and the **privacy
report**. Clicking any token scrolls the original pane to the line it came from.

Three things the web interface does that the CLI does not need to:

* **Secret values are masked everywhere on the page**, including inside the reconstructed feedback
  and its source-context blocks. A terminal is your own screen; a browser tab is history, extensions
  and whatever you are screen-sharing. `--allow-reveal` turns the masking off if you want it off.
* **No file is ever read from the server.** The filename you type only picks the language adapter —
  the code that gets abstracted is the code in the editor.
* **It refuses to bind anywhere but loopback** without `--expose`, because nothing in it
  authenticates a caller and the vault is on the other side of the port.

#### 📊 Session & Statistics Management
View saved local sessions and global usage statistics:
```powershell
python cli.py sessions list           # View recent sessions
python cli.py sessions show <ID>      # View details of a specific session
python cli.py sessions delete <ID>    # Delete a session
python cli.py stats                   # View global usage statistics
```

---

## 🔒 Privacy Levels

When running the `abstract` command (or using the interactive wizard), you can specify a privacy level that dictates how aggressive the abstraction should be:

| Level | Description | Behavior |
|-------|-------------|----------|
| `low` | Secrets Only | Abstract only `SECRET` patterns (API keys, passwords, auth tokens). Endpoints and rates survive — they are business VALUEs, not credentials. |
| `medium` | Recommended | Abstracts `SECRET` and business `VALUE` patterns (rates, fees, endpoints). |
| `high` | Strict | Abstracts all multi-character identifiers, secrets, and values. |
| `critical` | Maximum | Abstracts absolutely everything, including single-character loop variables. |

Use it manually via: `codeabstract abstract file.py --privacy high`

### Comments

Comments are **stripped by default, in every language**. A comment is prose written by the people who
own the code, and it is where business context lives most densely — `# 2.5% Stripe commission,
renegotiated Q3` gives away more than the identifier above it. `--keep-comments` re-injects them, and
even then each one is screened: comments that trip the secret or business-value classifier are
dropped, and identifiers named inside the survivors are rewritten to their tokens.

---

## 🧪 Testing

CodeAbstract ships with a comprehensive test suite covering the core algorithms, encryption, CLI commands, and end-to-end workflows. 

**650 tests pass.** Run them with `pytest`:

```powershell
# Run the full test suite
pytest tests/ -v

# Just the web interface (201 tests)
pytest tests/test_web/ -v

# Run tests with a coverage report
pytest tests/ --cov --cov-report=term-missing
```

The suite is organised by the phase that introduced each guarantee, so a failure names what broke:

| Directory | Covers |
|---|---|
| `tests/test_algorithms/test_phase0_regressions.py` | Every credential leak path, at all four privacy levels |
| `tests/test_algorithms/test_phase1_mapping.py` | Scope-aware mapping, occurrence records, line translation |
| `tests/test_algorithms/test_phase2_detection.py` | Context-based detection a name-regex cannot catch |
| `tests/test_algorithms/test_phase3_adversary.py` | The linkage attack and Code Privacy Entropy |
| `tests/test_algorithms/test_phase4_platform.py` | Providers, audit log, key storage, JavaScript |
| `tests/test_algorithms/test_leak_regressions.py` | Six leak paths the phase suites missed — see the file's header table |
| `tests/test_web/` | The web interface — see `test_web_privacy.py` for the guarantee itself |

---

## 🛠️ Technology Stack
- **CLI Framework:** `typer` & `questionary`
- **Web Interface:** `flask` (optional — `pip install -e ".[web]"`)
- **Terminal UI:** `rich` & `pygments`
- **Parsing:** Python standard `ast` library
- **Security:** `cryptography` (Fernet)
- **Database:** Local `sqlite3`
