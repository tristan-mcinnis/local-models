import AppKit
import SwiftUI

/// Menu-bar app delegate. Owns the status item, the panel, the polling model,
/// and the settings window. Local Models is an `.accessory` app: no Dock icon,
/// and it never takes the foreground unless a row asks for it.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {

    private var statusItem: NSStatusItem!
    private var settingsWindowController: NSWindowController?
    private var defaultsObserver: NSObjectProtocol?

    private let model = PanelModel()
    private lazy var panel = MenuBarPanelController(model: model)
    /// The menu bar shown while a normal window is open.
    private lazy var settingsMenu = SettingsMenu(showSettings: { [weak self] in self?.openSettings() })

    func applicationDidFinishLaunching(_ notification: Notification) {
        UserDefaults.standard.register(defaults: [
            // Dark is the house default; light is first-class.
            AppearancePreference.key: AppearancePreference.dark.rawValue,
            PanelModel.pollIntervalKey: 60.0,
        ])
        AppearancePreference.applyCurrent()

        model.onOpenSettings = { [weak self] in
            self?.panel.close()
            self?.openSettings()
        }
        model.onQuit = { NSApp.terminate(nil) }
        model.onStateChange = { [weak self] in self?.updateStatusItem() }

        setupStatusItem()
        observeAppearancePreference()
        model.start()
    }

    // MARK: - Status item

    private func setupStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem = item
        item.button?.target = self
        item.button?.action = #selector(togglePanel)
        updateStatusItem()
    }

    /// The status item says the same thing the panel header does, in one
    /// glyph: the chip from the app icon, filled while a model is warm, so
    /// icon and status item read as one app. Always a template image.
    private func updateStatusItem() {
        guard let button = statusItem?.button else { return }
        let symbol = model.daemonUp && model.warmCount > 0 ? "cpu.fill" : "cpu"
        let description = "Local Models — \(model.headline)"
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: description)?
            .withSymbolConfiguration(
                NSImage.SymbolConfiguration(pointSize: House.Control.statusGlyph, weight: .medium)
            )
        image?.isTemplate = true
        button.image = image
        button.toolTip = description
    }

    @objc private func togglePanel() {
        panel.toggle(relativeTo: statusItem.button)
    }

    // MARK: - Appearance

    private func observeAppearancePreference() {
        defaultsObserver = NotificationCenter.default.addObserver(
            forName: UserDefaults.didChangeNotification, object: nil, queue: .main
        ) { _ in
            MainActor.assumeIsolated { AppearancePreference.applyCurrent() }
        }
    }

    // MARK: - Settings

    @objc private func openSettings() {
        if let controller = settingsWindowController, let window = controller.window {
            controller.showWindow(nil)
            present(window)
            return
        }

        let hosting = NSHostingController(rootView: SettingsView(model: model))
        let window = NSWindow(contentViewController: hosting)
        window.title = "Local Models"
        window.styleMask = [.titled, .closable, .miniaturizable, .fullSizeContentView]
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.backgroundColor = House.NSColorToken.surface
        window.appearance = AppearancePreference.current.nsAppearance
        window.setContentSize(NSSize(width: 760, height: 500))
        window.minSize = NSSize(width: 720, height: 460)

        window.isReleasedWhenClosed = false
        window.delegate = self
        let controller = NSWindowController(window: window)
        controller.showWindow(self)
        window.center()
        present(window)
        settingsWindowController = controller
    }

    /// A normal window is up: install the menu bar it needs (Edit for its
    /// text fields, Window for minimise and close) and take the keyboard.
    /// An accessory app cannot activate itself on request alone, so
    /// `AppActivation` asks LaunchServices when the request is refused.
    private func present(_ window: NSWindow) {
        if NSApp.mainMenu == nil { NSApp.mainMenu = settingsMenu.makeMenu() }
        AppActivation.becomeRegularApp(showing: window)
    }
}

extension AppDelegate: NSWindowDelegate {
    /// The last normal window is closing: hand the menu bar back and become
    /// a menu-bar app again.
    func windowWillClose(_ notification: Notification) {
        guard let window = notification.object as? NSWindow else { return }
        if window === settingsWindowController?.window { settingsWindowController = nil }
        AppActivation.settleAfterClosing(window)
    }
}
