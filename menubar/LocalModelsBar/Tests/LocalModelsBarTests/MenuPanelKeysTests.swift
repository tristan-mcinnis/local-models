import AppKit
import XCTest
@testable import LocalModelsBar
import HouseUIKit

/// The keys the panel controller routes, driven through the real controller
/// and a real model without opening a window or calling the daemon.
@MainActor
final class MenuPanelKeysTests: XCTestCase {

    private func key(_ code: UInt16, _ chars: String = "", flags: NSEvent.ModifierFlags = []) throws -> PanelKeyPress {
        let event = try XCTUnwrap(NSEvent.keyEvent(
            with: .keyDown, location: .zero, modifierFlags: flags, timestamp: 0,
            windowNumber: 0, context: nil, characters: chars, charactersIgnoringModifiers: chars,
            isARepeat: false, keyCode: code
        ))
        return PanelKeyPress(event)
    }

    private func makeController() -> (MenuBarPanelController, PanelModel) {
        let model = PanelModel(defaults: UserDefaults(suiteName: "MenuPanelKeysTests-\(UUID().uuidString)")!)
        return (MenuBarPanelController(model: model), model)
    }

    func testEscapeCloses() throws {
        let (controller, model) = makeController()
        var closed = 0
        model.onClose = { closed += 1 }
        XCTAssertTrue(controller.handle(try key(53)))
        XCTAssertEqual(closed, 1)
    }

    func testDownArrowMovesTheSelection() throws {
        let (controller, model) = makeController()
        XCTAssertTrue(controller.handle(try key(125)))
        XCTAssertEqual(model.selection, 1)
    }

    func testSettingsAndQuitChords() throws {
        let (controller, model) = makeController()
        var settings = 0, quit = 0
        model.onOpenSettings = { settings += 1 }
        model.onQuit = { quit += 1 }
        XCTAssertTrue(controller.handle(try key(43, ",", flags: .command)))
        XCTAssertTrue(controller.handle(try key(12, "q", flags: .command)))
        XCTAssertEqual(settings, 1)
        XCTAssertEqual(quit, 1)
    }

    func testCommandReturnIsHandledAndPlainLettersAreNot() throws {
        let (controller, _) = makeController()
        XCTAssertTrue(controller.handle(try key(36, "\r", flags: .command)))
        XCTAssertFalse(controller.handle(try key(0, "a")))
        XCTAssertFalse(controller.handle(try key(6, "z", flags: .command)))
    }
}
