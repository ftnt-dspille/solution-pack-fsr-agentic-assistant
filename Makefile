PY ?= python3

.PHONY: build clean
build:
	$(PY) scripts/build.py
clean:
	rm -rf dist cache
