import AppKit
import XCTest
@testable import LocalModelsBar

/// The menu bar a normal window gets, and the rule that decides when the app
/// goes back to being a menu-bar app. Nothing here opens a window.
@MainActor
final class SettingsMenuTests: XCTestCase {

    override func setUp() {
        super.setUp()
        // The menu asks NSApp which window is key. Making the shared app
        // exist is enough; it is never run, and no window is opened.
        _ = NSApplication.shared
    }

    private func items(_ menu: SettingsMenu) -> [NSMenuItem] {
        menu.makeMenu().items.compactMap(\.submenu).flatMap(\.items)
    }

    func testEditItemsGoToTheFirstResponder() throws {
        let all = items(SettingsMenu(showSettings: {}))
        for title in ["Undo", "Redo", "Cut", "Copy", "Paste", "Select All"] {
            let item = try XCTUnwrap(all.first { $0.title == title }, title)
            XCTAssertNil(item.target, "\(title) must go to the first responder")
            XCTAssertNotNil(item.action)
        }
        let copy = try XCTUnwrap(all.first { $0.title == "Copy" })
        XCTAssertEqual(copy.keyEquivalent, "c")
        XCTAssertEqual(copy.keyEquivalentModifierMask, [.command])
    }

    func testWindowItemsExist() throws {
        let all = items(SettingsMenu(showSettings: {}))
        for title in ["Minimize", "Zoom", "Close"] {
            XCTAssertNotNil(all.first { $0.title == title }, title)
        }
        let close = try XCTUnwrap(all.first { $0.title == "Close" })
        XCTAssertEqual(close.keyEquivalent, "w")
    }

    func testPlainCommandQClosesTheWindowAndQuitIsOptionCommandQ() throws {
        let all = items(SettingsMenu(showSettings: {}))
        let plainQ = all.filter { $0.keyEquivalent == "q" && $0.keyEquivalentModifierMask == [.command] }
        XCTAssertEqual(plainQ.map(\.title), [SettingsMenu.closeTitle])
        let quit = try XCTUnwrap(all.first { $0.title == SettingsMenu.quitTitle })
        XCTAssertEqual(quit.keyEquivalentModifierMask, [.command, .option])
    }

    func testWindowItemsRestWhileNoNormalWindowIsKey() throws {
        let menu = SettingsMenu(showSettings: {})
        let all = items(menu)
        // No window is key in a test, so nothing that acts on one is enabled.
        for title in [SettingsMenu.closeTitle, "Close", "Minimize", "Zoom", "Hide \(SettingsMenu.appName)"] {
            let item = try XCTUnwrap(all.first { $0.title == title }, title)
            XCTAssertFalse(menu.validateMenuItem(item), title)
        }
        for title in ["About \(SettingsMenu.appName)", "Settings…", SettingsMenu.quitTitle] {
            let item = try XCTUnwrap(all.first { $0.title == title }, title)
            XCTAssertTrue(menu.validateMenuItem(item), title)
        }
    }

    func testSettingsItemAsksForTheWindow() throws {
        var opened = 0
        let menu = SettingsMenu(showSettings: { opened += 1 })
        let item = try XCTUnwrap(items(menu).first { $0.title == "Settings…" })
        let action = try XCTUnwrap(item.action)
        XCTAssertTrue(NSApp.sendAction(action, to: item.target, from: item))
        XCTAssertEqual(opened, 1)
    }

    func testTheAppStaysRegularOnlyWhileANormalWindowIsShown() {
        XCTAssertFalse(AppActivation.keepsRegularApp(otherWindows: []))
        XCTAssertFalse(AppActivation.keepsRegularApp(
            otherWindows: [WindowPresence(isNormal: false, isShown: true)]
        ))
        XCTAssertFalse(AppActivation.keepsRegularApp(
            otherWindows: [WindowPresence(isNormal: true, isShown: false)]
        ))
        XCTAssertTrue(AppActivation.keepsRegularApp(
            otherWindows: [WindowPresence(isNormal: true, isShown: true)]
        ))
        // A minimised window counts as shown: its Dock tile needs the app.
        XCTAssertTrue(AppActivation.keepsRegularApp(otherWindows: [
            WindowPresence(isNormal: false, isShown: true),
            WindowPresence(isNormal: true, isShown: true),
        ]))
    }
}
