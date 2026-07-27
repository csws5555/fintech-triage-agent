# Fintech Risk & Support Triage Agent

This is a fictional portfolio prototype for local banking-intent
classification and deterministic support-risk routing. It is not a
production banking platform and is not connected to customer accounts.

Detailed progress and verified command results are maintained in
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

## Activate the backend environment

```powershell
cd backend
venv\Scripts\Activate.ps1
```

## Backend validation

Run these commands from `backend`:

```powershell
python -m compileall app scripts tests
python -m pytest -q
python scripts/verify_phase1_baseline.py
python scripts/validate_policies.py
python -m pip check
```

The unit tests do not load the full DistilBERT weights or require
Ollama. The two validation scripts verify the protected local model
artifacts and the approved policy documents.

## Dependency maintenance

After deliberately changing the environment:

```powershell
python -m pip freeze > requirements.txt
```
