REPO := $(shell pwd)
BIN  := $(HOME)/.local/bin
# Installed runtime. launchd jobs (the daemon, and cos/Ledger calling the CLIs)
# may not read ~/Documents, so they run this copy, never the checkout.
LIB  := $(HOME)/.local/lib/local-models
PYTHON ?= $(shell which python3)

.PHONY: install install-server menubar install-menubar uninstall status restart logs test

## Copy cli/ and server/ to $(LIB), link the CLIs onto PATH, and seed the
## registry if none exists. Rerun after every change to cli/ or server/.
install:
	mkdir -p $(BIN) $(LIB)
	rsync -a --delete --exclude __pycache__ cli server $(LIB)/
	git describe --always --dirty > $(LIB)/SOURCE_COMMIT
	ln -sf $(LIB)/cli/local-model $(BIN)/local-model
	ln -sf $(LIB)/cli/local-image $(BIN)/local-image
	@test -f $(HOME)/Models/models.json || \
		(mkdir -p $(HOME)/Models && cp $(REPO)/registry/models.example.json $(HOME)/Models/models.json && \
		 echo "seeded ~/Models/models.json from the example — edit paths before use")
	@echo "installed: $(LIB) ($$(cat $(LIB)/SOURCE_COMMIT)); local-model, local-image -> $(BIN)"

## Render + load the daemon launchd agent on the installed copy (separate,
## deliberate act). Pass PYTHON= to keep the interpreter that has mlx-vlm.
install-server: install
	sed -e 's|__LIB__|$(LIB)|g' -e 's|__PYTHON__|$(PYTHON)|g' -e 's|__HOME__|$(HOME)|g' \
		server/launchd/com.local-models.server.plist.template \
		> $(HOME)/Library/LaunchAgents/com.local-models.server.plist
	launchctl bootout gui/$$(id -u)/com.local-models.server 2>/dev/null || true
	launchctl bootstrap gui/$$(id -u) $(HOME)/Library/LaunchAgents/com.local-models.server.plist
	@echo "loaded: com.local-models.server (port 8078)"

## Build the menu-bar app bundle into dist/.
menubar:
	cd menubar/LocalModelsBar && swift build -c release
	rm -rf "dist/Local Models.app"
	mkdir -p "dist/Local Models.app/Contents/MacOS"
	cp menubar/LocalModelsBar/.build/release/LocalModelsBar "dist/Local Models.app/Contents/MacOS/"
	cp menubar/LocalModelsBar/Info.plist "dist/Local Models.app/Contents/Info.plist"
	mkdir -p "dist/Local Models.app/Contents/Resources"
	cp menubar/LocalModelsBar/Resources/AppIcon.icns "dist/Local Models.app/Contents/Resources/AppIcon.icns"
	@echo "built: dist/Local Models.app"

## Copy the menu-bar app to /Applications and launch it.
install-menubar: menubar
	rm -rf "/Applications/Local Models.app"
	cp -R "dist/Local Models.app" "/Applications/Local Models.app"
	open "/Applications/Local Models.app"

uninstall:
	rm -f $(BIN)/local-model $(BIN)/local-image
	launchctl bootout gui/$$(id -u)/com.local-models.server 2>/dev/null || true
	rm -rf $(LIB)
	rm -f $(HOME)/Library/LaunchAgents/com.local-models.server.plist
	rm -rf "/Applications/Local Models.app"

status:
	@curl -s -m 3 http://127.0.0.1:8078/health || echo "daemon not running (make install-server)"
	@local-model status 2>/dev/null || true

## Picks up code changes only after `make install`.
restart:
	launchctl kickstart -k gui/$$(id -u)/com.local-models.server

logs:
	tail -50 $(HOME)/Library/Logs/local-models.log

## Offline unit tests + daemon smoke + publish scrub. Live gates: tests/compat.sh.
test:
	python3 -m unittest discover -s tests -p "test_*.py"
	python3 tests/smoke_daemon.py
	sh tests/scrub.sh
