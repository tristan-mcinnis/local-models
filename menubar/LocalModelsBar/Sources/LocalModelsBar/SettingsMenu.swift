import AppKit

/// The menu bar while a normal window (Settings) is open.
///
/// Local Models is a menu-bar app with no main menu, so a window it opened had no
/// Edit menu: Copy, Paste, Select All and Undo did nothing in its text
/// fields, and there was no Close or Minimize either. This menu is installed
/// when the window opens and removed once no normal window is open
/// (`AppActivation.settleAfterClosing`), so the panel keeps its own keys.
///
/// `⌘Q` closes the window, not the app: the status item and the panel must
/// survive a stray `⌘Q`. Quit Local Models is `⌥⌘Q`. Every item that acts on a
/// window is enabled only while one of the app's normal windows is key, so
/// nothing here acts from a menu-bar-only state.
///
/// Follows Quick Launch's `AIChatMenu` (`Sources/App/AIChatMenu.swift`), the
/// reference app.
@MainActor
final class SettingsMenu: NSObject, NSMenuItemValidation {
    static let appName = "Local Models"
    static let closeTitle = "Close Window"
    static let quitTitle = "Quit \(appName)"

    /// Brings the Settings window back, for the app menu's Settings item.
    private let showSettings: () -> Void

    init(showSettings: @escaping () -> Void) {
        self.showSettings = showSettings
        super.init()
    }

    func makeMenu() -> NSMenu {
        let main = NSMenu()

        let app = submenu(in: main, title: Self.appName)
        app.addItem(item("About \(Self.appName)", #selector(about), ""))
        app.addItem(.separator())
        app.addItem(item("Settings…", #selector(openSettings), ","))
        app.addItem(.separator())
        app.addItem(item("Hide \(Self.appName)", #selector(hideApp), "h"))
        app.addItem(.separator())
        app.addItem(item(Self.closeTitle, #selector(close), "q"))
        app.addItem(item(Self.quitTitle, #selector(quit), "q", [.command, .option]))

        let edit = submenu(in: main, title: "Edit")
        edit.addItem(responderItem("Undo", Selector(("undo:")), "z"))
        edit.addItem(responderItem("Redo", Selector(("redo:")), "z", [.command, .shift]))
        edit.addItem(.separator())
        edit.addItem(responderItem("Cut", #selector(NSText.cut(_:)), "x"))
        edit.addItem(responderItem("Copy", #selector(NSText.copy(_:)), "c"))
        edit.addItem(responderItem("Paste", #selector(NSText.paste(_:)), "v"))
        edit.addItem(responderItem("Select All", #selector(NSText.selectAll(_:)), "a"))

        let window = submenu(in: main, title: "Window")
        window.addItem(item("Minimize", #selector(minimize), "m"))
        window.addItem(item("Zoom", #selector(zoom), ""))
        window.addItem(.separator())
        window.addItem(item("Close", #selector(close), "w"))
        return main
    }

    // MARK: - Building

    private func submenu(in main: NSMenu, title: String) -> NSMenu {
        let holder = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        let menu = NSMenu(title: title)
        holder.submenu = menu
        main.addItem(holder)
        return menu
    }

    private func item(
        _ title: String,
        _ action: Selector,
        _ key: String,
        _ modifiers: NSEvent.ModifierFlags = .command
    ) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.keyEquivalentModifierMask = modifiers
        item.target = self
        return item
    }

    /// An Edit item that goes to the first responder, the focused text field.
    private func responderItem(
        _ title: String,
        _ action: Selector,
        _ key: String,
        _ modifiers: NSEvent.ModifierFlags = .command
    ) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.keyEquivalentModifierMask = modifiers
        return item
    }

    // MARK: - Actions

    /// The key window when it is a normal, titled one. The panel is
    /// borderless and can be key at the same time; then no window item acts.
    private var normalKeyWindow: NSWindow? {
        guard let key = NSApp.keyWindow, key.styleMask.contains(.titled) else { return nil }
        return key
    }

    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool {
        switch menuItem.action {
        case #selector(about), #selector(openSettings), #selector(quit):
            return true
        default:
            return normalKeyWindow != nil
        }
    }

    @objc private func about() { NSApp.orderFrontStandardAboutPanel(nil) }
    @objc private func openSettings() { showSettings() }
    @objc private func hideApp() { NSApp.hide(nil) }
    @objc private func quit() { NSApp.terminate(nil) }
    @objc private func minimize() { normalKeyWindow?.performMiniaturize(nil) }
    @objc private func zoom() { normalKeyWindow?.performZoom(nil) }
    @objc private func close() { normalKeyWindow?.performClose(nil) }
}
