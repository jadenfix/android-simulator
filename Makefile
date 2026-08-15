.PHONY: help bootstrap doctor test smoke lint install uninstall

help:
	@printf '%s\n' \
	  'make bootstrap  Install tools and create the default Play Store AVD' \
	  'make doctor     Validate the local environment' \
	  'make test       Run offline unit and syntax tests' \
	  'make smoke      Boot the default AVD and run a macOS integration smoke test' \
	  'make lint       Run shellcheck when available' \
	  'make install    Install the Python CLI into the active environment' \
	  'make uninstall  Remove the local CLI wrapper and shell block'

bootstrap:
	./scripts/bootstrap-macos.sh

doctor:
	python3 -m android_simulator doctor

test:
	./scripts/ci.sh

smoke:
	./scripts/smoke-macos.sh

lint:
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck scripts/*.sh; else echo 'shellcheck not installed; skipped'; fi

install:
	./scripts/install-local.sh

uninstall:
	./scripts/uninstall-local.sh
