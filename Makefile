REPO := $(shell pwd)
BIN  := $(HOME)/.local/bin
PYTHON := $(shell which python3)

.PHONY: install install-server menubar install-menubar uninstall status restart logs test

## Symlink the CLIs onto PATH and seed the registry if none exists.
install:
	mkdir -p $(BIN)
	ln -sf $(REPO)/cli/local-model $(BIN)/local-model
	ln -sf $(REPO)/cli/local-image $(BIN)/local-image
	@test -f $(HOME)/Models/models.json || \
		(mkdir -p $(HOME)/Models && cp $(REPO)/registry/models.example.json $(HOME)/Models/models.json && \
		 echo "seeded ~/Models/models.json from the example — edit paths before use")
	@echo "installed: local-model, local-image -> $(BIN)"

## Render + load the daemon launchd agent (separate, deliberate act).
install-server:
	sed -e 's|__REPO__|$(REPO)|g' -e 's|__PYTHON__|$(PYTHON)|g' -e 's|__HOME__|$(HOME)|g' \
		server/launchd/com.local-models.server.plist.template \
		> $(HOME)/Library/LaunchAgents/com.local-models.server.plist
	launchctl unload $(HOME)/Library/LaunchAgents/com.local-models.server.plist 2>/dev/null || true
	launchctl load $(HOME)/Library/LaunchAgents/com.local-models.server.plist
	@echo "loaded: com.local-models.server (port 8078)"

## Build the menu-bar app bundle into dist/.
menubar:
	cd menubar/LocalModelsBar && swift build -c release
	rm -rf "dist/Local Models.app"
	mkdir -p "dist/Local Models.app/Contents/MacOS"
	cp menubar/LocalModelsBar/.build/release/LocalModelsBar "dist/Local Models.app/Contents/MacOS/"
	cp menubar/LocalModelsBar/Info.plist "dist/Local Models.app/Contents/Info.plist"
	@echo "built: dist/Local Models.app"

## Copy the menu-bar app to /Applications and launch it.
install-menubar: menubar
	rm -rf "/Applications/Local Models.app"
	cp -R "dist/Local Models.app" "/Applications/Local Models.app"
	open "/Applications/Local Models.app"

uninstall:
	rm -f $(BIN)/local-model $(BIN)/local-image
	launchctl unload $(HOME)/Library/LaunchAgents/com.local-models.server.plist 2>/dev/null || true
	rm -f $(HOME)/Library/LaunchAgents/com.local-models.server.plist
	rm -rf "/Applications/Local Models.app"

status:
	@curl -s -m 3 http://127.0.0.1:8078/health || echo "daemon not running (make install-server)"
	@local-model status 2>/dev/null || true

restart:
	launchctl kickstart -k gui/$$(id -u)/com.local-models.server

logs:
	tail -50 $(HOME)/Library/Logs/local-models.log

## Offline unit tests + daemon smoke + publish scrub. Live gates: tests/compat.sh.
test:
	python3 -m unittest discover -s tests -p "test_*.py"
	python3 tests/smoke_daemon.py
	sh tests/scrub.sh
