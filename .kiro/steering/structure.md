---
inclusion: always
---
# Project structure

- app.py: Streamlit entry point. Wires loader -> core -> UI.
- src/canalcast/models.py, calculations.py, comparison.py, results.py, explain.py:
  the pure core. No file or network I/O. Never imports Streamlit.
- src/canalcast/loader.py: the only module that reads data/. Read-only CSV;
  attaches provenance (source or assumption rationale, status, data date) to every value.
- src/canalcast/ui/: Streamlit controls, views and charts. Imports the core.
- data/: read-only CSV inputs. Every row needs a status: sourced, approximate,
  assumption or derived.
- tests/: pytest and Hypothesis. Core tests must pass before UI work.
- .kiro/specs/canalcast: requirements, design and tasks. Record decisions here before code.