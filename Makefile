.PHONY: venv run test clean

VENV = .venv
PY = $(VENV)/bin/python
PIP = $(VENV)/bin/pip

venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run:
	$(PY) slate.py

test:
	xvfb-run -a $(PY) -m pytest tests/ -v

clean:
	rm -rf $(VENV) __pycache__ .pytest_cache tests/__pycache__
